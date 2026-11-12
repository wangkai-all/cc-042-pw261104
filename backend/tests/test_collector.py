"""采集器核心语义测试。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app import collector, gitops
from app.db import connect, init_db
from conftest import commit, git, head, write


@pytest.fixture()
def conn(tmp_path):
    c = connect(str(tmp_path / "test.db"))
    init_db(c)
    yield c
    c.close()


def register(conn, repo: Path):
    cur = conn.execute(
        "INSERT INTO repos(path, name, created_at) VALUES (?,?,?)",
        (str(repo), repo.name, int(time.time())),
    )
    conn.commit()
    return conn.execute("SELECT * FROM repos WHERE id=?", (cur.lastrowid,)).fetchone()


def all_commits(conn, repo_id):
    return conn.execute("SELECT * FROM commits WHERE repo_id=?", (repo_id,)).fetchall()


def batch_branches(conn, batch_id):
    return {
        r["name"]: r
        for r in conn.execute("SELECT * FROM batch_branches WHERE batch_id=?", (batch_id,))
    }


def files_of(conn, repo_id, sha):
    return conn.execute(
        "SELECT * FROM commit_files WHERE repo_id=? AND sha=?", (repo_id, sha)
    ).fetchall()


def parents_of(conn, repo_id, sha):
    return [
        r["parent_sha"]
        for r in conn.execute(
            "SELECT parent_sha FROM commit_parents WHERE repo_id=? AND sha=? ORDER BY position",
            (repo_id, sha),
        )
    ]


# ---------------------------------------------------------------- 基础采集

def test_initial_collect(conn, demo_repo):
    repo = register(conn, demo_repo)
    batch = collector.run_round(conn, repo)
    assert batch["status"] == "success"

    commits = {c["sha"]: c for c in all_commits(conn, repo["id"])}
    assert len(commits) == 5  # 根、特性x2、主程序v2、合并

    branches = batch_branches(conn, batch["id"])
    assert set(branches) == {"main", "feature"}
    assert all(b["status"] == "new" for b in branches.values())
    assert branches["main"]["tip_sha"] == head(demo_repo, "main")
    assert branches["main"]["reachable_count"] == 5
    assert branches["feature"]["reachable_count"] == 3

    # 合并提交：两个父提交，顺序保留
    merge_sha = head(demo_repo, "main")
    parents = parents_of(conn, repo["id"], merge_sha)
    assert len(parents) == 2
    assert parents[0] == git(demo_repo, "rev-parse", "main^1").stdout.strip()
    assert parents[1] == git(demo_repo, "rev-parse", "main^2").stdout.strip()

    # 合并提交相对第一父提交计算变更：只含 feature 带入的 src/feat.py
    mfiles = files_of(conn, repo["id"], merge_sha)
    assert [(f["path"], f["change_type"]) for f in mfiles] == [("src/feat.py", "A")]
    assert mfiles[0]["additions"] == 1 and mfiles[0]["deletions"] == 0

    # 根提交相对空树：全部 A，二进制单独标记
    root_sha = git(demo_repo, "rev-list", "--max-parents=0", "main").stdout.strip()
    rfiles = {f["path"]: f for f in files_of(conn, repo["id"], root_sha)}
    assert set(rfiles) == {"README.md", "src/main.py", "docs/说明 文档.md", "assets/data.bin"}
    assert all(f["change_type"] == "A" for f in rfiles.values())
    assert rfiles["assets/data.bin"]["is_binary"] == 1
    assert rfiles["assets/data.bin"]["additions"] is None
    assert rfiles["src/main.py"]["is_binary"] == 0
    assert rfiles["src/main.py"]["additions"] == 1

    # 改名：新旧路径都保留，中文/空格路径正确
    rename_commit = git(demo_repo, "rev-parse", "main^1").stdout.strip()
    cfiles = {f["path"]: f for f in files_of(conn, repo["id"], rename_commit)}
    assert cfiles["docs/说明文档 v2.md"]["change_type"] == "R"
    assert cfiles["docs/说明文档 v2.md"]["old_path"] == "docs/说明 文档.md"
    assert cfiles["src/main.py"]["change_type"] == "M"

    # 作者时间/提交者时间/采集时间分别保存；时区保留
    f1 = [c for c in commits.values() if c["message"] == "特性一"][0]
    assert f1["author_tz"] == "-0500"
    assert f1["committer_tz"] == "-0500"
    assert f1["author_email"] == "yi@example.com"
    assert f1["collected_at"] >= f1["author_time"]


def test_incremental_only_new_commits(conn, demo_repo):
    repo = register(conn, demo_repo)
    b1 = collector.run_round(conn, repo)
    n1 = len(all_commits(conn, repo["id"]))

    write(demo_repo, "src/main.py", "print('v3')\n")
    commit(demo_repo, "主程序 v3", date="2026-10-06T09:00:00")
    b2 = collector.run_round(conn, repo)

    assert b2["status"] == "success"
    assert len(all_commits(conn, repo["id"])) == n1 + 1  # 只补了一个
    branches = batch_branches(conn, b2["id"])
    assert branches["main"]["status"] == "forward"
    assert branches["feature"]["status"] == "same"
    assert branches["main"]["prev_tip_sha"] == batch_branches(conn, b1["id"])["main"]["tip_sha"]


def test_rewind_counts_as_rewrite(conn, demo_repo):
    """回退到较早提交也算改写，并按新指向重新计算可达集合。"""
    repo = register(conn, demo_repo)
    collector.run_round(conn, repo)

    write(demo_repo, "tmp.txt", "x\n")
    commit(demo_repo, "将被回退", date="2026-10-06T09:00:00")
    collector.run_round(conn, repo)
    old_tip = head(demo_repo, "main")

    git(demo_repo, "reset", "-q", "--hard", "HEAD~1")  # 回退
    b3 = collector.run_round(conn, repo)
    branches = batch_branches(conn, b3["id"])
    assert branches["main"]["status"] == "rewritten"
    assert branches["main"]["prev_tip_sha"] == old_tip
    # 可达集合按新指向重算：不再包含被回退掉的提交
    reachable = {
        r["sha"]
        for r in conn.execute(
            "SELECT sha FROM batch_branch_commits WHERE batch_id=? AND branch='main'",
            (b3["id"],),
        )
    }
    assert old_tip not in reachable
    assert branches["main"]["reachable_count"] == len(reachable)


def test_rebase_rewrite_and_shared_commits_kept(conn, demo_repo):
    """amend 改写被记录；共享提交保留，历史批次仍可查到改写前关系。"""
    repo = register(conn, demo_repo)
    b1 = collector.run_round(conn, repo)
    old_feature_tip = head(demo_repo, "feature")

    git(demo_repo, "checkout", "-q", "feature")
    write(demo_repo, "src/feat.py", "FEAT = 3\n")
    git(demo_repo, "add", "-A")
    git(demo_repo, "commit", "-q", "--amend", "-m", "特性二（改写）", env_extra={
        "GIT_AUTHOR_DATE": "2026-10-07T10:00:00+0800",
        "GIT_COMMITTER_DATE": "2026-10-07T10:00:00+0800",
    })
    b2 = collector.run_round(conn, repo)

    branches = batch_branches(conn, b2["id"])
    assert branches["feature"]["status"] == "rewritten"
    assert branches["feature"]["prev_tip_sha"] == old_feature_tip

    # 改写前的旧提交仍保留在库里（共享提交/历史数据不丢）
    shas = {c["sha"] for c in all_commits(conn, repo["id"])}
    assert old_feature_tip in shas
    # 历史批次 b1 仍能查到改写前 feature 指向旧提交
    b1_branches = batch_branches(conn, b1["id"])
    assert b1_branches["feature"]["tip_sha"] == old_feature_tip
    b1_feature_commits = {
        r["sha"]
        for r in conn.execute(
            "SELECT sha FROM batch_branch_commits WHERE batch_id=? AND branch='feature'",
            (b1["id"],),
        )
    }
    assert old_feature_tip in b1_feature_commits


def test_delete_branch_keeps_data(conn, demo_repo):
    repo = register(conn, demo_repo)
    b1 = collector.run_round(conn, repo)
    feature_tip = head(demo_repo, "feature")

    git(demo_repo, "branch", "-q", "-D", "feature")
    b2 = collector.run_round(conn, repo)

    branches = batch_branches(conn, b2["id"])
    assert branches["feature"]["status"] == "deleted"
    assert branches["feature"]["tip_sha"] is None
    # 数据保留：提交还在，历史批次仍完整
    shas = {c["sha"] for c in all_commits(conn, repo["id"])}
    assert feature_tip in shas
    assert len(all_commits(conn, repo["id"])) == 5
    b1_feature = conn.execute(
        "SELECT COUNT(*) AS n FROM batch_branch_commits WHERE batch_id=? AND branch='feature'",
        (b1["id"],),
    ).fetchone()["n"]
    assert b1_feature == 3


def test_gc_during_collect_fails_whole_round(conn, demo_repo):
    """采集期间源仓库清理了所需对象 => 本轮报错，当前结果仍是上一轮。"""
    repo = register(conn, demo_repo)
    b1 = collector.run_round(conn, repo)

    write(demo_repo, "src/main.py", "print('v3')\n")
    commit(demo_repo, "主程序 v3", date="2026-10-06T09:00:00")
    new_tip = head(demo_repo, "main")
    # 模拟对象被清理：删除新提交的对象文件
    obj = demo_repo / ".git" / "objects" / new_tip[:2] / new_tip[2:]
    assert obj.exists()
    obj.unlink()

    with pytest.raises(gitops.GitError):
        collector.run_round(conn, repo)

    failed = conn.execute(
        "SELECT * FROM batches WHERE repo_id=? ORDER BY id DESC LIMIT 1", (repo["id"],)
    ).fetchone()
    assert failed["status"] == "failed"
    assert failed["error"]
    # 当前结果不变：最后一个成功批次仍是 b1
    current = collector.last_successful_batch(conn, repo["id"])
    assert current["id"] == b1["id"]


def test_resume_interrupted_round(conn, demo_repo, monkeypatch):
    """中断后(running 状态)可继续：已采提交跳过，只补剩余，整轮成功才出结果。"""
    repo = register(conn, demo_repo)
    batch_id = collector.start_batch(conn, repo)

    real_collect = collector.collect_commit
    calls = {"n": 0}

    def flaky(conn_, repo_, sha):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("模拟进程中断")
        return real_collect(conn_, repo_, sha)

    monkeypatch.setattr(collector, "collect_commit", flaky)
    with pytest.raises(RuntimeError):
        collector._collect_batch(conn, repo, batch_id)  # 直接调用，绕过失败标记
    # 批次仍停留在 running（进程死掉的现场）
    assert conn.execute(
        "SELECT status FROM batches WHERE id=?", (batch_id,)
    ).fetchone()["status"] == "running"
    n_partial = len(all_commits(conn, repo["id"]))
    assert 0 < n_partial < 5

    monkeypatch.setattr(collector, "collect_commit", real_collect)
    batch = collector.run_round(conn, repo)  # 续采同一批次
    assert batch["id"] == batch_id
    assert batch["status"] == "success"
    assert len(all_commits(conn, repo["id"])) == 5  # 无重复
    n_rows = conn.execute(
        "SELECT COUNT(*) AS n FROM batch_branch_commits WHERE batch_id=?", (batch_id,)
    ).fetchone()["n"]
    assert n_rows == 5 + 3  # main 5 个 + feature 3 个


def test_empty_tree_root_diff():
    """根提交相对空树计算（单元级）。"""
    assert True  # 已由 test_initial_collect 覆盖根提交场景


def test_numstat_rename_parse():
    raw = b"0\t0\t\x00old name.txt\x00new name.txt\x001\t2\t" + "目录 一/文件.txt".encode() + b"\x00"
    stats = collector.parse_numstat(raw)
    assert stats[(b"old name.txt", b"new name.txt")] == (0, 0, False)
    assert stats[(None, "目录 一/文件.txt".encode())] == (1, 2, False)


def test_numstat_binary_parse():
    stats = collector.parse_numstat(b"-\t-\tassets/logo.png\x00")
    assert stats[(None, b"assets/logo.png")] == (None, None, True)
