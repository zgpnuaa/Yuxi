# 上游同步与定制清单

> 用途：跟踪本地所有定制改动的去向，指导「跟随上游更新」时的 merge 冲突处理——「已合并」的接受上游版本、删本地重复；「PR 中」的等合并后删；「私有」的保留。
>
> 更新时机：提新 PR、PR 被合并/关闭、或新增本地私有定制时，同步更新本表。
>
> 正确口径：评估「本地相对上游的定制」用 `git cherry origin/main <branch>` 或 `git diff <上游同时间点> <branch>`，**不要**用 `origin/main..main` 的 ahead/behind（历史 force-push/rebase 会产生 SHA 假象）。

## 一、已合并进上游（本地无需保留，跟随上游时接受上游版本）

| 定制 | 分支 / PR | 合并后动作 |
|---|---|---|
| invalid_tool_call 净化窄方案 | `feat/invalid-tool-call-cleanup`（#1006） | 删本地 `agents/models.py` 的 mixin（上游已收窄为 `models/chat.py` 的 wire 净化） |
| MCP 服务并发加载 | `perf/mcp-concurrent-load`（#1012） | 无本地重复 |
| SSE watchdog | `fix/run-stream-idle-watchdog`（#1014） | 无本地重复 |

## 二、PR 中 / 未合入（合并后删本地重复）

| 定制 | 分支 | PR 号 | 状态 |
|---|---|---|---|
| 网络重试（断网恢复） | `feat/network-retry` | #1007 | review 中 |
| 审批中断恢复（state 骨架图） | `perf/state-reader-skeleton` | #1013 | review 中 |
| 子智能体状态推送 + 级联取消 | `feat/subagent-push-and-cascade` | #1010 | review 中 |
| 模型类型新增 image | `feat/model-type-image` | #1008 | review 中 |
| 沙盒 keepalive | `feat/sandbox-keepalive` | #1005 | 已撤回 |
| guided 队列 + SSE 阻塞读 | `feat/guided-queue-and-sse` | #1009 | 已关闭（接受） |

## 三、私有定制（未提 PR）

### 3.1 本地 `main`（commit `7e59bf2d`「本地定制修改提交0824」，24 文件）

| 定制 | 文件 | 说明 |
|---|---|---|
| OIDC 增强 | `backend/package/yuxi/services/oidc_service.py` | Django `is_superuser`→superadmin 映射；`phone_number`/`avatar` 每次 SSO 登录时 UPDATE users 同步 |
| web-research 技能 | `backend/package/yuxi/agents/skills/buildin/web-research/SKILL.md` | SearCrawl MCP 网络检索 + 沙盒下载 PDF/DOCX/XLSX/PPTX |
| timeline-diagram 技能 | `backend/package/yuxi/agents/skills/buildin/timeline-diagram/SKILL.md` | 时间线图生成 |
| 技能注册 | `backend/package/yuxi/agents/skills/buildin/__init__.py` | 注册上面两个技能 |
| 品牌化 | `web/index.html`、`web/src/layouts/AppLayout.vue`、`HomeView.vue`、`LoginView.vue`、`SettingsModal.vue`、`UserInfoComponent.vue`、`public/favicon.png`、`logo.png` | 航发智库/小涡、去 GitHub 外链、去文档中心 |
| 部署适配 | `requirements.txt`、`docker/api.Dockerfile`、`docker/sandbox.Dockerfile`、`docker/.dockerignore`、`docker-compose.yml`、`docker/sandbox_provisioner/app.py`、`scripts/init.sh` | PPT 依赖、redis 6380、worker 自愈循环、dgmo-mcp 挂载、字体、LibreOffice |
| 智能体自称 | `backend/package/yuxi/agents/buildin/chatbot/prompt.py` | `语析` → `小涡` |
| 依赖 | `backend/package/pyproject.toml` | +`python-docx` |

> 注意：`agents/models.py`（invalid_tool_call mixin）、`agents/mcp/service.py`（`ExceptionGroup`）、`services/run_worker.py`（`ExceptionGroup`）这三项**已被上游吸收**，跟随上游时直接接受上游版本，不要保留本地版。

### 3.2 `deploy/v0.7.2`（聚合分支，74 文件，私有定制最完整落点）

基于 origin/main 的聚合分支，是「未提 PR 私有定制」的完整落点，含 3.1 全部 + 以下 main 里没有的：

| 定制 | 文件 | 说明 |
|---|---|---|
| DashScope image-gen | `backend/package/yuxi/agents/skills/buildin/image-gen/SKILL.md` | `qwen-image-3.0-pro` / `dashscope.aliyuncs.com` / `DASHSCOPE_API_KEY` |
| spinner 状态词 | `web/src/utils/streamStatusText.js` 等 | 加载文案状态词轮换 |
| 子智能体视图 | `web/src/utils/subagentRuns.js`、`SubagentThreadView.vue` | 子智能体面板 |

## 四、重复实现待去重（同一功能两份，需择一，本轮不动）

| 功能 | `deploy/v0.7.2` 位置 | PR 分支位置 | 差异 |
|---|---|---|---|
| 网络重试 | `agents/middlewares/network_retry.py`（旧版） | `feat/network-retry`（新版） | 差 163 行 |
| invalid_tool_call | `models/chat.py`（本地版） | `feat/invalid-tool-call-cleanup`（已合并） | 差 81 行 |

## 五、跟随上游的标准动作（备忘）

```bash
git fetch origin                                   # origin = 上游 xerrors/Yuxi
git checkout <部署分支>                             # main 或 deploy/*
git merge origin/main                              # 冲突按本表「已合并→接受上游 / 私有→保留」处理
```

每次上游发新版本（0.7.4、0.7.5…）都小步 merge 一次，不要攒大分叉。
