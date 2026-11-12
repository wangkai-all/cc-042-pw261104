"""构造测试用 Git 仓库的辅助工具。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args, env_extra=None, check=True):
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="测试者",
        GIT_AUTHOR_EMAIL="tester@example.com",
        GIT_COMMITTER_NAME="测试者",
        GIT_COMMITTER_EMAIL="tester@example.com",
    )
    if env_extra:
        env.update(env_extra)
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {p.stderr}")
    return p


def write(repo: Path, rel: str, content):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


def commit(repo: Path, msg: str, author=("甲", "jia@example.com"),
           date="2026-10-01T10:00:00", tz="+0800"):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, env_extra={
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_AUTHOR_DATE": f"{date}{tz}",
        "GIT_COMMITTER_DATE": f"{date}{tz}",
    })


def head(repo: Path, ref="HEAD") -> str:
    return git(repo, "rev-parse", ref).stdout.strip()


@pytest.fixture()
def demo_repo(tmp_path: Path) -> Path:
    """结构：
    main:   c1(根, 含二进制+中文空格路径) -> c2(改名) -> m(合并 feature) -> c4
    feature: c1 -> f1 -> f2
    """
    repo = tmp_path / "demo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "README.md", "# 演示\n")
    write(repo, "src/main.py", "print('v1')\n")
    write(repo, "docs/说明 文档.md", "# 含空格与中文的路径\n")
    write(repo, "assets/data.bin", bytes(range(256)))
    commit(repo, "初始提交", date="2026-10-01T09:00:00")

    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, "src/feat.py", "FEAT = 1\n")
    commit(repo, "特性一", author=("乙", "yi@example.com"),
           date="2026-10-02T10:00:00", tz="-0500")
    write(repo, "src/feat.py", "FEAT = 2\n")
    commit(repo, "特性二", author=("乙", "yi@example.com"),
           date="2026-10-03T10:00:00", tz="-0500")

    git(repo, "checkout", "-q", "main")
    git(repo, "mv", "docs/说明 文档.md", "docs/说明文档 v2.md")
    write(repo, "src/main.py", "print('v2')\n")
    commit(repo, "主程序 v2 并重命名文档", date="2026-10-04T11:00:00")

    git(repo, "merge", "--no-ff", "-q", "-m", "合并 feature", "feature", env_extra={
        "GIT_AUTHOR_DATE": "2026-10-05T12:00:00+0800",
        "GIT_COMMITTER_DATE": "2026-10-05T12:00:00+0800",
    })
    return repo
