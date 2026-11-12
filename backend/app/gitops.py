"""Git 命令封装。任何 git 失败都抛 GitError —— 采集轮据此整轮报错。"""
from __future__ import annotations

import subprocess


class GitError(RuntimeError):
    def __init__(self, args, returncode: int, stderr: str):
        self.cmd_args = [str(a) for a in args]
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"git {' '.join(self.cmd_args)} 失败 (exit {returncode}): {stderr.strip()[:500]}"
        )


def git(repo_path: str, *args) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *[str(a) for a in args]],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise GitError(args, proc.returncode, proc.stderr.decode("utf-8", "replace"))
    return proc.stdout


def git_text(repo_path: str, *args) -> str:
    return git(repo_path, *args).decode("utf-8", "replace")


def is_ancestor(repo_path: str, old_sha: str, new_sha: str):
    """old 是否为 new 的祖先。True/False；对象缺失无法判断时返回 None。"""
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "merge-base", "--is-ancestor", old_sha, new_sha],
        capture_output=True,
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None
