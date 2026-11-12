"""API 端到端测试：登记 -> 采集 -> 查询 -> 改写 -> 再采集 -> 比较。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api.db")
    monkeypatch.setenv("GITSTATS_DB", db_path)
    # 重新加载以使用独立数据库
    import importlib

    import app.main as main_mod

    importlib.reload(main_mod)
    with TestClient(main_mod.app) as c:
        yield c


def test_full_flow(client, demo_repo):
    # 登记
    r = client.post("/api/repos", json={"path": str(demo_repo)})
    assert r.status_code == 201, r.text
    repo_id = r.json()["id"]
    assert r.json()["name"] == "demo"

    # 重复登记
    r = client.post("/api/repos", json={"path": str(demo_repo)})
    assert r.status_code == 409

    # 采集第一轮
    r = client.post(f"/api/repos/{repo_id}/collect")
    assert r.status_code == 200, r.text
    b1 = r.json()
    assert b1["status"] == "success"
    assert {b["name"] for b in b1["branches"]} == {"main", "feature"}

    # 概览
    ov = client.get(f"/api/repos/{repo_id}/overview").json()
    assert ov["current_batch"]["id"] == b1["id"]
    assert len(ov["branches"]) == 2

    # 提交列表（图数据）
    data = client.get(f"/api/repos/{repo_id}/commits").json()
    assert len(data["commits"]) == 5
    merge = [c for c in data["commits"] if len(c["parents"]) == 2][0]
    assert merge["tip_of"] == ["main"]
    assert set(merge["branches"]) == {"main"}

    # 提交详情：改名新旧路径、时区
    detail = client.get(f"/api/repos/{repo_id}/commits/{merge['sha']}").json()
    assert detail["author_tz"] in ("+0800", "-0500")
    files = detail["files"]
    assert files[0]["path"] == "src/feat.py"

    # 作者统计 + 作者时间筛选
    authors = client.get(f"/api/repos/{repo_id}/authors").json()["authors"]
    by_email = {a["author_email"]: a for a in authors}
    assert by_email["yi@example.com"]["commits"] == 2
    assert by_email["yi@example.com"]["author_tz"] == "-0500"
    assert by_email["jia@example.com"]["commits"] == 2  # 初始提交 + 主程序v2
    assert by_email["tester@example.com"]["commits"] == 1  # 合并提交
    # 用作者时间过滤：只留 2026-10-02 之后 => 甲 的初始提交被滤掉
    import datetime

    since = int(datetime.datetime(2026, 10, 2, tzinfo=datetime.timezone.utc).timestamp())
    filtered = client.get(f"/api/repos/{repo_id}/authors", params={"since": since}).json()["authors"]
    fmap = {a["author_email"]: a for a in filtered}
    assert fmap["jia@example.com"]["commits"] == 1
    assert fmap["yi@example.com"]["commits"] == 2

    # 制造改写/回退/删分支
    from conftest import commit, git, head, write

    old_feature_tip = head(demo_repo, "feature")
    git(demo_repo, "checkout", "-q", "feature")
    write(demo_repo, "src/feat.py", "FEAT = 99\n")
    git(demo_repo, "add", "-A")
    git(demo_repo, "commit", "-q", "--amend", "-m", "特性二（改写）")
    git(demo_repo, "checkout", "-q", "main")
    write(demo_repo, "main.txt", "x\n")
    commit(demo_repo, "main 前进", date="2026-10-08T09:00:00")
    git(demo_repo, "checkout", "-q", "-b", "short-lived")
    write(demo_repo, "tmp.txt", "y\n")
    commit(demo_repo, "临时", date="2026-10-08T10:00:00")
    git(demo_repo, "checkout", "-q", "main")

    # 第二轮采集：看到改写与 short-lived
    b2 = client.post(f"/api/repos/{repo_id}/collect").json()
    branches = {b["name"]: b for b in b2["branches"]}
    assert branches["feature"]["status"] == "rewritten"
    assert branches["feature"]["prev_tip_sha"] == old_feature_tip
    assert branches["main"]["status"] == "forward"
    assert branches["short-lived"]["status"] == "new"
    short_lived_tip = head(demo_repo, "short-lived")

    # 删除分支后第三轮采集
    git(demo_repo, "branch", "-q", "-D", "short-lived")
    b3 = client.post(f"/api/repos/{repo_id}/collect").json()
    branches3 = {b["name"]: b for b in b3["branches"]}
    assert branches3["short-lived"]["status"] == "deleted"
    assert branches3["short-lived"]["tip_sha"] is None

    # 历史批次仍可打开；被删分支的提交数据保留
    b2_commits = client.get(
        f"/api/repos/{repo_id}/commits", params={"batch_id": b2["id"]}
    ).json()["commits"]
    assert short_lived_tip in {c["sha"] for c in b2_commits}
    b1_commits = client.get(
        f"/api/repos/{repo_id}/commits", params={"batch_id": b1["id"]}
    ).json()["commits"]
    assert old_feature_tip in {c["sha"] for c in b1_commits}

    # 批次比较（第一轮 vs 第三轮）：改写记录与分支变化
    cmp = client.get(f"/api/repos/{repo_id}/compare", params={"a": b1["id"], "b": b3["id"]}).json()
    added_shas = {c["sha"] for c in cmp["added"]}
    assert len(added_shas) >= 2  # 新提交 + 改写后的提交
    assert any(rw["name"] == "feature" for rw in cmp["rewrites"])
    change_names = {c["name"] for c in cmp["branch_changes"]}
    assert "feature" in change_names and "main" in change_names

    # 批次比较（第二轮 vs 第三轮）：被删分支的提交从可达集合中移除
    cmp23 = client.get(f"/api/repos/{repo_id}/compare", params={"a": b2["id"], "b": b3["id"]}).json()
    removed_shas = {c["sha"] for c in cmp23["removed"]}
    assert short_lived_tip in removed_shas
    change_names23 = {c["name"] for c in cmp23["branch_changes"]}
    assert "short-lived" in change_names23

    # 批次列表
    batches = client.get(f"/api/repos/{repo_id}/batches").json()
    assert [b["status"] for b in batches] == ["success"] * 3
    assert batches[0]["commit_count"] > 0


def test_register_invalid_path(client, tmp_path):
    r = client.post("/api/repos", json={"path": str(tmp_path / "nope")})
    assert r.status_code == 400
    not_git = tmp_path / "plain"
    not_git.mkdir()
    r = client.post("/api/repos", json={"path": str(not_git)})
    assert r.status_code == 400


def test_collect_failure_keeps_current(client, demo_repo):
    from conftest import commit, head, write

    repo_id = client.post("/api/repos", json={"path": str(demo_repo)}).json()["id"]
    b1 = client.post(f"/api/repos/{repo_id}/collect").json()

    write(demo_repo, "x.txt", "x\n")
    commit(demo_repo, "新提交", date="2026-10-09T09:00:00")
    tip = head(demo_repo, "main")
    os.unlink(demo_repo / ".git" / "objects" / tip[:2] / tip[2:])  # 模拟对象被清理

    r = client.post(f"/api/repos/{repo_id}/collect")
    assert r.status_code == 502
    ov = client.get(f"/api/repos/{repo_id}/overview").json()
    assert ov["current_batch"]["id"] == b1["id"]  # 当前结果仍是上一轮
    batches = client.get(f"/api/repos/{repo_id}/batches").json()
    assert batches[0]["status"] == "failed"
    assert batches[0]["error"]
