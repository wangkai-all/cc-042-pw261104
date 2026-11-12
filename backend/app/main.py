"""FastAPI 入口：仓库登记、采集、统计查询。全部本地，不连接任何远程平台。"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import collector, gitops
from .db import Database

DB_PATH = os.environ.get("GITSTATS_DB", str(Path.cwd() / "gitstats.db"))
db = Database(DB_PATH)
collect_locks: dict[int, threading.Lock] = {}
collect_locks_guard = threading.Lock()

app = FastAPI(title="本地 Git 仓库统计")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def get_repo_or_404(conn, repo_id: int):
    repo = conn.execute("SELECT * FROM repos WHERE id=?", (repo_id,)).fetchone()
    if repo is None:
        raise HTTPException(404, "仓库不存在")
    return repo


class RepoIn(BaseModel):
    path: str
    name: str | None = None


@app.get("/api/repos")
def list_repos(conn=Depends(get_conn)):
    out = []
    for r in conn.execute("SELECT * FROM repos ORDER BY id"):
        current = collector.last_successful_batch(conn, r["id"])
        running = conn.execute(
            "SELECT id, started_at FROM batches WHERE repo_id=? AND status='running'"
            " ORDER BY id DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        out.append(
            {
                **dict(r),
                "current_batch": dict(current) if current else None,
                "running_batch": dict(running) if running else None,
            }
        )
    return out


@app.post("/api/repos", status_code=201)
def register_repo(body: RepoIn, conn=Depends(get_conn)):
    path = os.path.abspath(os.path.expanduser(body.path))
    if not os.path.isdir(path):
        raise HTTPException(400, f"路径不存在: {path}")
    try:
        gitops.git_text(path, "rev-parse", "--git-dir")
    except gitops.GitError:
        raise HTTPException(400, f"不是 Git 仓库: {path}")
    name = body.name or os.path.basename(path.rstrip("/")) or path
    try:
        cur = conn.execute(
            "INSERT INTO repos(path, name, created_at) VALUES (?,?,?)",
            (path, name, int(time.time())),
        )
        conn.commit()
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, "该路径已登记")
        raise
    return dict(conn.execute("SELECT * FROM repos WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/api/repos/{repo_id}", status_code=204)
def unregister_repo(repo_id: int, conn=Depends(get_conn)):
    get_repo_or_404(conn, repo_id)
    for table in ("batch_branch_commits", "batch_branches"):
        conn.execute(
            f"DELETE FROM {table} WHERE batch_id IN (SELECT id FROM batches WHERE repo_id=?)",
            (repo_id,),
        )
    for table in ("commit_files", "commit_parents", "commits"):
        conn.execute(f"DELETE FROM {table} WHERE repo_id=?", (repo_id,))
    conn.execute("DELETE FROM batches WHERE repo_id=?", (repo_id,))
    conn.execute("DELETE FROM repos WHERE id=?", (repo_id,))
    conn.commit()


@app.post("/api/repos/{repo_id}/collect")
def collect(repo_id: int, conn=Depends(get_conn)):
    """执行一轮采集。若存在中断(running)的轮次则续采该轮。"""
    repo = get_repo_or_404(conn, repo_id)
    with collect_locks_guard:
        lock = collect_locks.setdefault(repo_id, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "该仓库已有采集在进行中")
    try:
        return collector.run_round(conn, repo)
    except gitops.GitError as exc:
        raise HTTPException(502, f"采集失败（本轮已作废，页面仍显示上一轮成功结果）: {exc}")
    finally:
        lock.release()


def resolve_batch_id(conn, repo_id: int, batch_id: int | None) -> int:
    if batch_id is not None:
        row = conn.execute(
            "SELECT id FROM batches WHERE id=? AND repo_id=?", (batch_id, repo_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "批次不存在")
        return batch_id
    current = collector.last_successful_batch(conn, repo_id)
    if current is None:
        raise HTTPException(404, "尚无成功采集的批次")
    return current["id"]


@app.get("/api/repos/{repo_id}/overview")
def overview(repo_id: int, conn=Depends(get_conn)):
    repo = get_repo_or_404(conn, repo_id)
    current = collector.last_successful_batch(conn, repo_id)
    branches = []
    if current is not None:
        branches = [
            dict(r)
            for r in conn.execute(
                "SELECT name, tip_sha, prev_tip_sha, status, reachable_count"
                " FROM batch_branches WHERE batch_id=? ORDER BY name",
                (current["id"],),
            )
        ]
    running = conn.execute(
        "SELECT id, started_at FROM batches WHERE repo_id=? AND status='running'"
        " ORDER BY id DESC LIMIT 1",
        (repo_id,),
    ).fetchone()
    return {
        "repo": dict(repo),
        "current_batch": dict(current) if current else None,
        "running_batch": dict(running) if running else None,
        "branches": branches,
    }


@app.get("/api/repos/{repo_id}/commits")
def list_commits(repo_id: int, batch_id: int | None = None, conn=Depends(get_conn)):
    get_repo_or_404(conn, repo_id)
    bid = resolve_batch_id(conn, repo_id, batch_id)
    rows = conn.execute(
        "SELECT DISTINCT c.* FROM commits c"
        " JOIN batch_branch_commits bc ON bc.sha=c.sha AND bc.batch_id=?"
        " WHERE c.repo_id=? ORDER BY c.author_time DESC, c.sha",
        (bid, repo_id),
    ).fetchall()
    commits = []
    for r in rows:
        parents = [
            p["parent_sha"]
            for p in conn.execute(
                "SELECT parent_sha FROM commit_parents WHERE repo_id=? AND sha=? ORDER BY position",
                (repo_id, r["sha"]),
            )
        ]
        tips = [
            b["name"]
            for b in conn.execute(
                "SELECT name FROM batch_branches WHERE batch_id=? AND tip_sha=?",
                (bid, r["sha"]),
            )
        ]
        branches = [
            b["branch"]
            for b in conn.execute(
                "SELECT branch FROM batch_branch_commits WHERE batch_id=? AND sha=?",
                (bid, r["sha"]),
            )
        ]
        d = dict(r)
        d["parents"] = parents
        d["tip_of"] = tips
        d["branches"] = sorted(branches)
        commits.append(d)
    return {"batch_id": bid, "commits": commits}


@app.get("/api/repos/{repo_id}/commits/{sha}")
def commit_detail(repo_id: int, sha: str, conn=Depends(get_conn)):
    get_repo_or_404(conn, repo_id)
    row = conn.execute(
        "SELECT * FROM commits WHERE repo_id=? AND sha=?", (repo_id, sha)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "提交不存在")
    parents = [
        p["parent_sha"]
        for p in conn.execute(
            "SELECT parent_sha FROM commit_parents WHERE repo_id=? AND sha=? ORDER BY position",
            (repo_id, sha),
        )
    ]
    files = [
        dict(f)
        for f in conn.execute(
            "SELECT path, old_path, change_type, additions, deletions, is_binary"
            " FROM commit_files WHERE repo_id=? AND sha=? ORDER BY path",
            (repo_id, sha),
        )
    ]
    return {**dict(row), "parents": parents, "files": files}


@app.get("/api/repos/{repo_id}/authors")
def author_stats(
    repo_id: int,
    batch_id: int | None = None,
    since: int | None = None,
    until: int | None = None,
    conn=Depends(get_conn),
):
    """按作者聚合。筛选用作者时间(author_time, unix 秒)，显示带时区。"""
    get_repo_or_404(conn, repo_id)
    bid = resolve_batch_id(conn, repo_id, batch_id)
    cond = ""
    params: list = [bid, repo_id]
    if since is not None:
        cond += " AND c.author_time>=?"
        params.append(since)
    if until is not None:
        cond += " AND c.author_time<=?"
        params.append(until)
    rows = conn.execute(
        "SELECT c.author_name, c.author_email, c.author_tz,"
        " COUNT(DISTINCT c.sha) AS commits,"
        " MIN(c.author_time) AS first_commit, MAX(c.author_time) AS last_commit"
        " FROM commits c"
        " JOIN (SELECT DISTINCT sha FROM batch_branch_commits WHERE batch_id=?) bc"
        "   ON bc.sha=c.sha"
        f" WHERE c.repo_id=?{cond}"
        " GROUP BY c.author_email ORDER BY commits DESC",
        params,
    ).fetchall()
    out = []
    for r in rows:
        fparams: list = [bid, repo_id, r["author_email"]]
        if since is not None:
            fparams.append(since)
        if until is not None:
            fparams.append(until)
        lines = conn.execute(
            "SELECT COALESCE(SUM(f.additions),0) AS adds, COALESCE(SUM(f.deletions),0) AS dels,"
            " COALESCE(SUM(f.is_binary),0) AS binary_files, COUNT(*) AS files"
            " FROM commit_files f JOIN commits c ON c.repo_id=f.repo_id AND c.sha=f.sha"
            " JOIN (SELECT DISTINCT sha FROM batch_branch_commits WHERE batch_id=?) bc"
            "   ON bc.sha=f.sha"
            f" WHERE f.repo_id=? AND c.author_email=?{cond}",
            fparams,
        ).fetchone()
        out.append({**dict(r), **dict(lines)})
    return {"batch_id": bid, "authors": out}


@app.get("/api/repos/{repo_id}/batches")
def list_batches(repo_id: int, conn=Depends(get_conn)):
    get_repo_or_404(conn, repo_id)
    rows = []
    for b in conn.execute(
        "SELECT * FROM batches WHERE repo_id=? ORDER BY id DESC", (repo_id,)
    ):
        branches = [
            dict(r)
            for r in conn.execute(
                "SELECT name, tip_sha, prev_tip_sha, status, reachable_count"
                " FROM batch_branches WHERE batch_id=? ORDER BY name",
                (b["id"],),
            )
        ]
        n = conn.execute(
            "SELECT COUNT(DISTINCT sha) AS n FROM batch_branch_commits WHERE batch_id=?",
            (b["id"],),
        ).fetchone()["n"]
        rows.append({**dict(b), "branches": branches, "commit_count": n})
    return rows


@app.get("/api/repos/{repo_id}/compare")
def compare_batches(repo_id: int, a: int, b: int, conn=Depends(get_conn)):
    """比较两个批次：提交集合差异、分支指向变化、改写记录。"""
    get_repo_or_404(conn, repo_id)
    for bid in (a, b):
        if conn.execute(
            "SELECT 1 FROM batches WHERE id=? AND repo_id=?", (bid, repo_id)
        ).fetchone() is None:
            raise HTTPException(404, f"批次 {bid} 不存在")

    def commit_set(bid):
        return {
            r["sha"]
            for r in conn.execute(
                "SELECT DISTINCT sha FROM batch_branch_commits WHERE batch_id=?", (bid,)
            )
        }

    def commit_rows(shas):
        if not shas:
            return []
        marks = ",".join("?" for _ in shas)
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT sha, message, author_name, author_email, author_time, author_tz"
                f" FROM commits WHERE repo_id=? AND sha IN ({marks})"
                " ORDER BY author_time DESC",
                (repo_id, *shas),
            )
        ]

    def branch_map(bid):
        return {
            r["name"]: dict(r)
            for r in conn.execute(
                "SELECT name, tip_sha, prev_tip_sha, status FROM batch_branches WHERE batch_id=?",
                (bid,),
            )
        }

    sa, sb = commit_set(a), commit_set(b)
    ba, bb = branch_map(a), branch_map(b)
    branch_changes = []
    for name in sorted(set(ba) | set(bb)):
        ta, tb = ba.get(name), bb.get(name)
        if (ta or {}).get("tip_sha") != (tb or {}).get("tip_sha"):
            branch_changes.append(
                {
                    "name": name,
                    "a_tip": (ta or {}).get("tip_sha"),
                    "b_tip": (tb or {}).get("tip_sha"),
                    "b_status": (tb or {}).get("status"),
                }
            )
    lo, hi = min(a, b), max(a, b)
    rewrites = [
        {"batch": b_["id"], "name": br["name"], "from": br["prev_tip_sha"], "to": br["tip_sha"]}
        for b_ in conn.execute(
            "SELECT id FROM batches WHERE repo_id=? AND id>? AND id<=?", (repo_id, lo, hi)
        )
        for br in conn.execute(
            "SELECT name, tip_sha, prev_tip_sha FROM batch_branches"
            " WHERE batch_id=? AND status='rewritten'",
            (b_["id"],),
        )
    ]
    return {
        "added": commit_rows(sb - sa),
        "removed": commit_rows(sa - sb),
        "branch_changes": branch_changes,
        "rewrites": rewrites,
    }


# 已构建的前端（存在时）挂在根路径
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
