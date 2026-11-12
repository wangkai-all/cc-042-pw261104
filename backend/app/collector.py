"""采集器：每轮先快照分支指向，再基于快照完成整轮读取。

关键语义：
- 正常前进只补未采过的提交（提交按仓库全局去重）。
- 旧 tip 不再是新 tip 的祖先（含回退到较早提交）=> 记录分支改写，
  并按新指向重新计算该分支能到达的提交集合。
- 共享提交保留；删分支只是快照里标记 deleted，不删任何提交数据。
- 任何 git 读取失败（如源仓库采集期间清理了对象）=> 整轮 failed，
  不更新页面当前结果（当前结果永远取自最后一个 success 批次）。
- 进程中断后批次停留在 running，可通过 resume 继续：已入库的提交
  会被自动跳过，只补剩余部分。
"""
from __future__ import annotations

import time

from . import gitops

COMMIT_FORMAT = "%H%x00%P%x00%an%x00%ae%x00%at%x00%ai%x00%cn%x00%ce%x00%ct%x00%ci%x00%B"


def now_ts() -> int:
    return int(time.time())


# ---------------------------------------------------------------- 快照

def snapshot_refs(path: str) -> dict:
    """当前所有本地分支 -> tip sha。"""
    out = gitops.git_text(
        path, "for-each-ref", "--format=%(refname:short)%00%(objectname)", "refs/heads"
    )
    tips = {}
    for line in out.splitlines():
        if line:
            name, sha = line.split("\x00")
            tips[name] = sha
    return tips


def last_successful_batch(conn, repo_id: int):
    return conn.execute(
        "SELECT * FROM batches WHERE repo_id=? AND status='success' ORDER BY id DESC LIMIT 1",
        (repo_id,),
    ).fetchone()


def start_batch(conn, repo) -> int:
    """开启一轮：立刻记录各分支指向的提交，整轮读取都基于这份快照。"""
    repo_id = repo["id"]
    path = repo["path"]
    cur = conn.execute(
        "INSERT INTO batches(repo_id, started_at, status) VALUES (?,?,'running')",
        (repo_id, now_ts()),
    )
    batch_id = cur.lastrowid

    tips = snapshot_refs(path)
    prev = {}
    prev_batch = last_successful_batch(conn, repo_id)
    if prev_batch is not None:
        for r in conn.execute(
            "SELECT name, tip_sha FROM batch_branches WHERE batch_id=? AND status!='deleted'",
            (prev_batch["id"],),
        ):
            prev[r["name"]] = r["tip_sha"]

    for name, sha in tips.items():
        prev_sha = prev.get(name)
        if prev_sha is None:
            status = "new"
        elif prev_sha == sha:
            status = "same"
        else:
            anc = gitops.is_ancestor(path, prev_sha, sha)
            # 旧提交不再是新提交的祖先（含回退）=> 改写；对象已缺失同样按改写记录
            status = "forward" if anc is True else "rewritten"
        conn.execute(
            "INSERT INTO batch_branches(batch_id, name, tip_sha, prev_tip_sha, status)"
            " VALUES (?,?,?,?,?)",
            (batch_id, name, sha, prev_sha, status),
        )
    for name, sha in prev.items():
        if name not in tips:
            conn.execute(
                "INSERT INTO batch_branches(batch_id, name, tip_sha, prev_tip_sha, status)"
                " VALUES (?,?,NULL,?,'deleted')",
                (batch_id, name, sha),
            )
    conn.commit()
    return batch_id


# ---------------------------------------------------------------- 提交读取

def parse_numstat(data: bytes) -> dict:
    """解析 `diff-tree --numstat -z`。
    改名条目为 `adds\\tdels\\t\\0old\\0new\\0`；二进制 adds/dels 为 '-'。
    返回 {(old_path|None, new_path): (adds, dels, is_binary)}，键为 bytes。
    """
    tokens = data.split(b"\x00")
    out = {}
    i = 0
    while i < len(tokens):
        rec = tokens[i]
        i += 1
        if not rec:
            continue
        adds_b, dels_b, p = rec.split(b"\t", 2)
        if p == b"":
            old, new = tokens[i], tokens[i + 1]
            i += 2
        else:
            old, new = None, p
        is_binary = adds_b == b"-"
        adds = None if is_binary else int(adds_b)
        dels = None if is_binary else int(dels_b)
        out[(old, new)] = (adds, dels, is_binary)
    return out


def parse_name_status(data: bytes) -> list:
    """解析 `diff-tree --name-status -z -M`。返回 [(change_type, old|None, new)]，bytes。"""
    tokens = data.split(b"\x00")
    out = []
    i = 0
    while i < len(tokens):
        rec = tokens[i]
        i += 1
        if not rec:
            continue
        code = rec[:1].decode("ascii", "replace")
        if code in ("R", "C"):
            old, new = tokens[i], tokens[i + 1]
            i += 2
            out.append(("R", old, new))
        else:
            p = tokens[i]
            i += 1
            out.append((code, None, p))
    return out


def _decode(b: bytes) -> str:
    return b.decode("utf-8", "replace")


def read_file_changes(path: str, sha: str, parents: list) -> list:
    """相对第一父提交（根提交相对空树）计算文件变更，含改名新旧路径与二进制标记。"""
    if parents:
        extra, revs = [], [parents[0], sha]
    else:
        extra, revs = ["--root", "--no-commit-id"], [sha]
    numstat = gitops.git(path, "diff-tree", "-r", "-M", "-z", "--numstat", *extra, *revs)
    name_status = gitops.git(path, "diff-tree", "-r", "-M", "-z", "--name-status", *extra, *revs)
    stats = parse_numstat(numstat)
    changes = []
    for change_type, old, new in parse_name_status(name_status):
        adds, dels, is_binary = stats.get((old, new), (None, None, False))
        changes.append(
            {
                "path": _decode(new),
                "old_path": _decode(old) if old is not None else None,
                "change_type": change_type,
                "additions": adds,
                "deletions": dels,
                "is_binary": 1 if is_binary else 0,
            }
        )
    return changes


def read_commit_meta(path: str, sha: str) -> dict:
    raw = gitops.git(path, "show", "-s", f"--format={COMMIT_FORMAT}", sha)
    parts = raw.split(b"\x00", 10)
    if len(parts) != 11:
        raise gitops.GitError(["show", sha], 0, f"无法解析提交元数据 {sha}")
    (h, parents, an, ae, at, ai, cn, ce, ct, ci, message) = [_decode(p) for p in parts]
    return {
        "sha": h.strip(),
        "parents": parents.split() if parents.strip() else [],
        "author_name": an,
        "author_email": ae,
        "author_time": int(at),
        "author_tz": ai.rsplit(" ", 1)[-1].strip(),
        "committer_name": cn,
        "committer_email": ce,
        "committer_time": int(ct),
        "committer_tz": ci.rsplit(" ", 1)[-1].strip(),
        "message": message.rstrip("\n"),
    }


def collect_commit(conn, repo, sha: str) -> bool:
    """采集单个提交（含父指针与文件变更）。已存在则跳过。返回是否新采。"""
    repo_id, path = repo["id"], repo["path"]
    exists = conn.execute(
        "SELECT 1 FROM commits WHERE repo_id=? AND sha=?", (repo_id, sha)
    ).fetchone()
    if exists:
        return False
    meta = read_commit_meta(path, sha)
    files = read_file_changes(path, sha, meta["parents"])
    with conn:  # 每个提交一个事务：中断后已采部分保留，续采自动跳过
        conn.execute(
            "INSERT INTO commits(repo_id, sha, message, author_name, author_email,"
            " author_time, author_tz, committer_name, committer_email, committer_time,"
            " committer_tz, collected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                repo_id, meta["sha"], meta["message"], meta["author_name"],
                meta["author_email"], meta["author_time"], meta["author_tz"],
                meta["committer_name"], meta["committer_email"],
                meta["committer_time"], meta["committer_tz"], now_ts(),
            ),
        )
        for pos, p in enumerate(meta["parents"]):
            conn.execute(
                "INSERT INTO commit_parents(repo_id, sha, parent_sha, position) VALUES (?,?,?,?)",
                (repo_id, meta["sha"], p, pos),
            )
        for f in files:
            conn.execute(
                "INSERT INTO commit_files(repo_id, sha, path, old_path, change_type,"
                " additions, deletions, is_binary) VALUES (?,?,?,?,?,?,?,?)",
                (
                    repo_id, meta["sha"], f["path"], f["old_path"], f["change_type"],
                    f["additions"], f["deletions"], f["is_binary"],
                ),
            )
    return True


# ---------------------------------------------------------------- 整轮

def run_round(conn, repo) -> dict:
    """执行一轮采集；失败时批次标记 failed 并抛错，当前结果不变。"""
    batch = conn.execute(
        "SELECT * FROM batches WHERE repo_id=? AND status='running' ORDER BY id DESC LIMIT 1",
        (repo["id"],),
    ).fetchone()
    if batch is not None:
        batch_id = batch["id"]  # 续采中断的轮次
    else:
        batch_id = start_batch(conn, repo)
    try:
        _collect_batch(conn, repo, batch_id)
    except Exception as exc:
        conn.execute(
            "UPDATE batches SET status='failed', error=?, finished_at=? WHERE id=?",
            (str(exc), now_ts(), batch_id),
        )
        conn.commit()
        raise
    return get_batch(conn, batch_id)


def _collect_batch(conn, repo, batch_id: int) -> None:
    repo_id, path = repo["id"], repo["path"]
    tips = {
        r["name"]: r["tip_sha"]
        for r in conn.execute(
            "SELECT name, tip_sha FROM batch_branches WHERE batch_id=? AND status!='deleted'",
            (batch_id,),
        )
    }
    known = {
        r["sha"] for r in conn.execute("SELECT sha FROM commits WHERE repo_id=?", (repo_id,))
    }
    # 只补未采过的提交。注意不能用 rev-list --not <已采> 做排除：
    # 中断续采时已采的是最新提交，其祖先可能尚未采集，--not 会把它们一并排除。
    # 这里取全量可达集合后在本地过滤（提交按仓库全局去重，代价可接受）。
    # 源仓库若清理了所需对象，rev-list/cat-file 会报错 => 整轮失败。
    tips_sorted = sorted(set(tips.values()))
    out = gitops.git_text(path, "rev-list", *tips_sorted) if tips_sorted else ""
    for sha in out.split():
        if sha not in known:
            collect_commit(conn, repo, sha)
            known.add(sha)

    # 按本轮快照的指向，重新计算每个分支能到达的提交集合
    conn.execute("DELETE FROM batch_branch_commits WHERE batch_id=?", (batch_id,))
    for name, tip in tips.items():
        reachable = gitops.git_text(path, "rev-list", tip).split()
        conn.executemany(
            "INSERT OR IGNORE INTO batch_branch_commits(batch_id, branch, sha) VALUES (?,?,?)",
            [(batch_id, name, s) for s in reachable],
        )
        conn.execute(
            "UPDATE batch_branches SET reachable_count=? WHERE batch_id=? AND name=?",
            (len(reachable), batch_id, name),
        )
    conn.execute(
        "UPDATE batches SET status='success', finished_at=? WHERE id=?",
        (now_ts(), batch_id),
    )
    conn.commit()


def get_batch(conn, batch_id: int) -> dict:
    batch = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    branches = [
        dict(r)
        for r in conn.execute(
            "SELECT name, tip_sha, prev_tip_sha, status, reachable_count"
            " FROM batch_branches WHERE batch_id=? ORDER BY name",
            (batch_id,),
        )
    ]
    return {**dict(batch), "branches": branches}
