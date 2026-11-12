# 本地 Git 仓库统计

面向本地 Git 仓库的统计系统：仓库分支被**回退、改写或删除**后，统计页会跟随更新，且改写前的关系仍可在历史批次中查询。只读取本地仓库，不连接任何远程平台。

## 功能

- **登记仓库路径**：页面登记本地仓库，展示分支、提交图、作者统计与文件变更。
- **快照式采集**：每轮采集先记录各分支当时指向的提交，整轮读取都基于这份快照。
- **增量采集**：正常前进只补未采过的提交（提交按仓库全局去重）。
- **改写追踪**：旧 tip 不再是新 tip 的祖先（含回退到较早提交）即记录为分支改写，并按新指向重新计算该分支可达的提交集合。
- **数据保留**：共享提交只存一份；删除分支不会删除任何提交数据，历史批次仍可打开比较。
- **整轮成败**：采集期间源仓库清理了所需对象 → 本轮标记失败并报错，页面当前结果仍是上一轮成功批次，绝不展示半份结果。
- **断点续采**：进程中断后批次停留在 running 状态，再次采集会续跑同一轮，已采提交自动跳过。
- **变更口径**：合并提交相对第一父提交计算增删行；根提交相对空树；二进制文件单独列出；改名保留新旧两个路径（含空格、中文路径）。
- **三种时间**：作者时间、提交者时间、采集时间分别保存；统计筛选用作者时间，显示带时区。

## 技术栈

Python + Git（命令行）+ FastAPI + SQLite ｜ React + Vite

## 目录结构

```
backend/
  app/
    db.py         # SQLite schema（repos / batches / commits / commit_parents / commit_files / batch_branches / batch_branch_commits）
    gitops.py     # git 命令封装，失败抛 GitError
    collector.py  # 采集轮：快照 → 增量读取 → 可达集合重算 → 整轮成败
    main.py       # FastAPI：登记、采集、概览、提交、作者、批次、比较
  tests/          # pytest：13 个用例覆盖全部核心语义
scripts/
  make_demo_repo.py  # 演示仓库生成（合并/改名/回退/改写/删分支）
frontend/
  src/            # React：提交图(SVG 车道)、分支、作者统计、批次历史与比较
```

## 运行

```bash
# 后端（Python 3.11+）
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
GITSTATS_DB=./gitstats.db .venv/bin/python -m uvicorn app.main:app \
    --host 127.0.0.1 --port 8000 --app-dir backend

# 前端（开发模式，代理 /api 到 8000）
cd frontend && npm install && npm run dev

# 或构建后由后端直接托管（http://127.0.0.1:8000/）
cd frontend && npm run build
```

## 演示流程

```bash
# 1. 生成演示仓库（含合并提交、中文/空格路径、改名、二进制文件）
python3 scripts/make_demo_repo.py /tmp/demo-repo --phase 1

# 2. 在页面登记 /tmp/demo-repo，点击「采集一轮」

# 3. 制造 main 前进、feature/login 改写、hotfix 回退、temp-branch 删除
python3 scripts/make_demo_repo.py /tmp/demo-repo --phase 2

# 4. 再点「采集一轮」：分支页出现「改写」「已删除」标记；
#    批次历史里勾选两轮可比较提交集合差异；批次 #1 仍可打开查看改写前的关系
```

## 测试

```bash
cd backend && ../.venv/bin/python -m pytest tests/ -q
```

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/repos` | 仓库列表 / 登记 `{path, name?}` |
| DELETE | `/api/repos/{id}` | 取消登记（连同统计数据） |
| POST | `/api/repos/{id}/collect` | 采集一轮；有中断轮次则续采 |
| GET | `/api/repos/{id}/overview` | 当前批次 + 分支快照 |
| GET | `/api/repos/{id}/commits?batch_id=` | 某批次可达提交（含父指针，用于提交图） |
| GET | `/api/repos/{id}/commits/{sha}` | 提交详情 + 文件变更（改名新旧路径、二进制标记） |
| GET | `/api/repos/{id}/authors?since=&until=` | 作者统计，按作者时间筛选 |
| GET | `/api/repos/{id}/batches` | 全部批次（含失败/中断） |
| GET | `/api/repos/{id}/compare?a=&b=` | 两批次比较：提交差异、分支变化、改写记录 |
