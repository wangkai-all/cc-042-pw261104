#!/usr/bin/env python3
"""生成本地演示仓库，覆盖：合并提交、文件改名、中文/空格路径、二进制文件、
分支回退、历史改写与分支删除。

用法：
    python3 scripts/make_demo_repo.py <目标路径> --phase 1   # 建初始历史（先采集一轮）
    python3 scripts/make_demo_repo.py <目标路径> --phase 2   # 制造改写/回退/删分支（再采集一轮）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(repo: Path, *args: str, env_extra: dict | None = None) -> str:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "演示者")
    env.setdefault("GIT_AUTHOR_EMAIL", "demo@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "演示者")
    env.setdefault("GIT_COMMITTER_EMAIL", "demo@example.com")
    if env_extra:
        env.update(env_extra)
    out = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env
    )
    if out.returncode != 0:
        sys.exit(f"git {' '.join(args)} 失败:\n{out.stderr}")
    return out.stdout.strip()


def commit(repo: Path, message: str, author: tuple[str, str], date: str, tz: str) -> None:
    run(repo, "add", "-A")
    run(
        repo,
        "commit", "-q", "-m", message,
        env_extra={
            "GIT_AUTHOR_NAME": author[0],
            "GIT_AUTHOR_EMAIL": author[1],
            "GIT_AUTHOR_DATE": f"{date}{tz}",
            "GIT_COMMITTER_DATE": f"{date}{tz}",
        },
    )


def write(repo: Path, rel: str, content: str | bytes) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")


ALICE = ("张晓", "zhangxiao@example.com")
BOB = ("Bob Li", "bob.li@example.com")
CAROL = ("Carol", "carol@example.com")


def phase1(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "core.quotepath", "false")

    write(repo, "README.md", "# 演示项目\n\n本地 Git 统计演示。\n")
    write(repo, "src/main.py", "def main():\n    print('hello')\n")
    write(repo, "docs/设计 文档.md", "# 设计文档\n\n初版设计，路径含空格。\n")
    write(repo, "assets/logo.png", bytes(range(256)) * 4)  # 二进制文件
    commit(repo, "初始提交：项目骨架", ALICE, "2026-10-01T09:30:00", "+0800")

    run(repo, "checkout", "-q", "-b", "feature/login")
    write(repo, "src/login.py", "def login(user):\n    return True\n")
    commit(repo, "登录模块骨架", BOB, "2026-10-03T14:00:00", "-0500")
    write(repo, "src/login.py", "def login(user):\n    return check(user)\n\n\ndef check(user):\n    return bool(user)\n")
    commit(repo, "完善登录校验", BOB, "2026-10-04T10:00:00", "-0500")

    run(repo, "checkout", "-q", "main")
    write(repo, "src/main.py", "def main():\n    print('hello world')\n")
    run(repo, "mv", "docs/设计 文档.md", "docs/设计文档 v2.md")  # 改名：含空格+中文
    commit(repo, "更新主程序并重命名设计文档", ALICE, "2026-10-05T11:20:00", "+0800")

    # 合并 feature/login -> main，产生合并提交
    run(repo, "merge", "--no-ff", "-q", "-m", "合并分支 feature/login", "feature/login",
        env_extra={"GIT_AUTHOR_DATE": "2026-10-06T16:40:00+0800",
                   "GIT_COMMITTER_DATE": "2026-10-06T16:40:00+0800"})

    run(repo, "checkout", "-q", "-b", "hotfix")
    write(repo, "src/hotfix.py", "# 紧急修复 v1\nFIX = 1\n")
    commit(repo, "紧急修复第一步", CAROL, "2026-10-07T08:05:00", "+0200")
    write(repo, "src/hotfix.py", "# 紧急修复 v2\nFIX = 2\n")
    commit(repo, "紧急修复第二步（将被回退）", CAROL, "2026-10-07T09:05:00", "+0200")

    run(repo, "checkout", "-q", "-b", "temp-branch")
    write(repo, "tmp.txt", "临时分支内容，随后整个分支会被删除\n")
    commit(repo, "临时提交（分支将被删除）", CAROL, "2026-10-08T12:00:00", "+0800")
    run(repo, "checkout", "-q", "main")
    print(f"[phase1] 演示仓库已创建: {repo}")
    print("  分支: main, feature/login, hotfix, temp-branch")
    print("  下一步：在页面登记该路径并执行一轮采集，然后运行 --phase 2")


def phase2(repo: Path) -> None:
    if not (repo / ".git").is_dir():
        sys.exit("仓库不存在，请先运行 --phase 1")
    # 1) main 正常前进
    run(repo, "checkout", "-q", "main")
    write(repo, "src/main.py", "def main():\n    print('hello world')\n    print('v2')\n")
    write(repo, "assets/logo.png", bytes(range(255, -1, -1)) * 4)  # 二进制变更
    commit(repo, "主程序 v2 并更新 logo", ALICE, "2026-10-10T10:00:00", "+0800")

    # 2) feature/login 改写历史（amend 最新提交，旧 tip 不再是新 tip 的祖先）
    run(repo, "checkout", "-q", "feature/login")
    write(repo, "src/login.py", "def login(user):\n    return check(user) and user.active\n\n\ndef check(user):\n    return bool(user)\n")
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "--amend", "-m", "完善登录校验（改写版）",
        env_extra={"GIT_AUTHOR_DATE": "2026-10-11T09:00:00-0500",
                   "GIT_COMMITTER_DATE": "2026-10-11T09:00:00-0500"})

    # 3) hotfix 回退到较早提交
    run(repo, "checkout", "-q", "hotfix")
    run(repo, "reset", "-q", "--hard", "HEAD~1")

    # 4) 删除 temp-branch（其提交仍被历史批次引用，数据必须保留）
    run(repo, "checkout", "-q", "main")
    run(repo, "branch", "-q", "-D", "temp-branch")
    print("[phase2] 已制造：main 前进、feature/login 改写、hotfix 回退、temp-branch 删除")
    print("  下一步：在页面再执行一轮采集，观察改写记录与历史批次对比")


def main() -> None:
    ap = argparse.ArgumentParser(description="生成本地演示 Git 仓库")
    ap.add_argument("path", help="目标路径")
    ap.add_argument("--phase", type=int, choices=[1, 2], required=True)
    args = ap.parse_args()
    repo = Path(args.path).resolve()
    if args.phase == 1:
        if (repo / ".git").exists():
            sys.exit(f"{repo} 已是 Git 仓库，请换路径或先删除")
        phase1(repo)
    else:
        phase2(repo)


if __name__ == "__main__":
    main()
