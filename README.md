# InnerLife v2.3

InnerLife 是 AI agent 的内部生活系统。

[MIT License](LICENSE)

它让每个 agent 在不同对话窗口之间保留一份持续的内部状态：当前关注、未完成问题、形成的新理解和待分享念头。

它不是定时生成消息的工具，也不是另一套记忆库。

```text
Memoria：发生过什么
Continuity：我们现在站在哪里
InnerLife：Agent 自己正在关注、怀疑和改变什么
```

## 当前已具备

- 每个 agent 独立状态、历史和边界。
- 多窗口输入统一排队，顺序消化。
- 每次变化都有来源，允许没有变化。
- 后台长期运行，自动处理新材料。
- 失败重试和逐步退避，不会持续轰炸模型。
- MCP：支持 MCP 的宿主可直接读写。
- HTTP API 和中文管理页面。
- 显式同步 Memoria 事实和 Continuity 当前位置。
- 本地模型、OpenAI 兼容服务、Anthropic 兼容服务可替换。
- 待分享念头可标记为已使用、延后或放弃。
- 诊断、备份、固定场景和自动测试。
- macOS `launchd` 开机启动配置。
- 自主经历：没有用户输入时，Agent 可以按自己的关注选择真实公开材料。
- 每次自主经历保存来源、读取时间和文本证据，不用模型虚构"生活"。
- Agent 可以认为没有值得看的内容，也可以读完后判断没有形成变化。
- 分享调度：待分享念头会在会话开始或对话相关时重新判断，而不是永久躺在 briefing。
- 支持自然带入、主动开启话题、继续等待和放弃；每次最多选一条。
- 主动开场受每日上限和冷却时间限制，不会变成定时消息机器人。
- 内在状态收敛：旧变化和经历可以整理成稳定认识并退出日常上下文。
- 未完成问题可以降温，历史仍然保留并可追溯。
- 后台按每个 Agent 的阈值自动整理，活跃上下文不会无限增长。
- 主动推送：proactive_allowed 的念头可在无会话时自动推送至飞书等外部渠道。
- 推送由 daemon 评估队列（urgency >= 阈值 + 无活跃会话）配合外部 cronjob 轮询完成。

数据默认保存在：

```text
~/.innerlife/innerlife.db
```

模型不是 Agent 本身。换模型、换机器或重启服务，不会改变已经保存的内部历史。

## 安装

需要 Python 3.10 或更高版本。不要使用 macOS 自带的旧版 Python。

```bash
cd /path/to/innerlife
python -m pip install --upgrade pip setuptools
pip install -e '.[dev]'
cp profiles/example-agent.json profiles/my-agent.json
```

编辑 `profiles/my-agent.json`，至少修改 `agent_id`、`display_name`、
`identity`、`boundaries.can_access_users` 和 `autonomous_sources`。

然后初始化：

```bash
python -m innerlife.cli init --profile profiles/my-agent.json --json
python -m innerlife.cli doctor --json
```

程序不会自动创建任何人格。仓库中的 profile 只是中性示例。

## 配置模型

复制并填写私有配置文件：

```bash
mkdir -p ~/.innerlife
cp config/innerlife.env.example ~/.innerlife/innerlife.env
chmod 600 ~/.innerlife/innerlife.env
```

### 本地 Ollama / LM Studio

```bash
INNERLIFE_LLM_BACKEND=openai_compatible
INNERLIFE_LLM_BASE_URL=http://127.0.0.1:11434/v1
INNERLIFE_LLM_API_KEY=
INNERLIFE_LIGHT_MODEL=gemma3:4b
INNERLIFE_DEEP_MODEL=gemma3:12b
```

### Anthropic Messages 兼容服务

```bash
INNERLIFE_LLM_BACKEND=anthropic_compatible
INNERLIFE_LLM_BASE_URL=https://your-service
INNERLIFE_LLM_API_KEY=your-api-key
INNERLIFE_LIGHT_MODEL=your-light-model
INNERLIFE_DEEP_MODEL=your-deep-model
```

### 线上 DeepSeek

```bash
INNERLIFE_LLM_BACKEND=openai_compatible
INNERLIFE_LLM_BASE_URL=https://api.deepseek.com/v1
INNERLIFE_LLM_API_KEY=your-deepseek-api-key
INNERLIFE_LIGHT_MODEL=deepseek-v4-flash
INNERLIFE_DEEP_MODEL=deepseek-v4-pro
```

## 启动后台和管理页面

```bash
# 安装 launchd 服务
./scripts/install_launchd.sh

# 启动
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/io.innerlife.daemon.plist

launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/io.innerlife.web.plist
```

管理页面：

```text
http://127.0.0.1:8012
```

查看服务状态：

```bash
python -m innerlife.cli doctor --json
tail -f ~/.innerlife/logs/daemon.log
```

停止和移除：

```bash
./scripts/uninstall_launchd.sh
```

数据不会被删除。

## 会话闭环

InnerLife 不依赖特定宿主才能完成闭环。

### CLI

```bash
# 开始会话
python -m innerlife.cli session-start \
  --agent my-agent \
  --user my-user \
  --host my-host \
  --external-session-id session-001 \
  --json

# 结束会话
python -m innerlife.cli session-end \
  --agent my-agent \
  --session-id session_xxx \
  --conversation-file conversation.json \
  --json
```

### HTTP API

```text
POST /api/agents/{agent_id}/sessions/start
POST /api/agents/{agent_id}/sessions/{session_id}/end
GET  /api/agents/{agent_id}/sessions
```

系统会自动完成：

```text
判断是否真的留下余韵
→ 无余韵：关闭会话，不写内部变化
→ 有余韵：形成 afterthought
→ 消化并更新内部状态
→ 下一次 session-start 返回更新后的状态
```

重复开始（相同 external_session_id）和重复结束（相同 session_id）都不会重复写入。多个会话并行时，系统会识别期间发生的其他状态变化，避免无感覆盖。

## MCP 接入

为每个 agent 配置一个 MCP server：

```json
{
  "mcpServers": {
    "innerlife-my-agent": {
      "command": "/path/to/innerlife/scripts/run_mcp.sh",
      "args": [],
      "env": {
        "INNERLIFE_AGENT_ID": "my-agent"
      }
    }
  }
}
```

调用 `innerlife_session_start` 时，宿主必须明确传入自己的 `user_id`；
InnerLife 不预设用户身份。

MCP 工具列表：

- `innerlife_session_start` / `innerlife_session_end` — 会话闭环
- `innerlife_sessions` — 列出最近会话
- `innerlife_briefing` — 对话开始时读取当前内部状态
- `innerlife_submit_fact` — 显式提交事实材料
- `innerlife_submit_continuity` — 显式提交共同线当前位置
- `innerlife_digest` — 手动触发消化
- `innerlife_explore` — 手动触发自主探索
- `innerlife_experiences` — 查看已形成的自主经历
- `innerlife_pending_shares` — 读取待分享念头
- `innerlife_share_check` — 结合当前对话判断是否出现自然分享时机
- `innerlife_share_actions` — 查看评估、呈现、延后和处理记录
- `innerlife_mark_share` — 标记已使用、延后或放弃
- `innerlife_converge` — 手动运行一次内在状态整理
- `innerlife_summaries` — 查看收敛形成的稳定认识
- `innerlife_history` — 查看内部变化历史
- `innerlife_status` — 查看系统状态
- `innerlife_delivery_queue` — 查看等待外部推送的待分享内容
- `innerlife_mark_delivered` — 标记推送结果（delivered/failed/queued）

宿主的标准闭环：

```text
对话开始
→ innerlife_session_start
→ 如果 share_plan 选中 proactive 内容，可自然开启一次话题

对话进行中
→ 话题形成后可调用 innerlife_share_check
→ 如果选中 natural 内容，可自然带入
→ 表达后用 innerlife_mark_share 回报 used
→ 没说则回报 deferred，内容继续等待

对话结束
→ innerlife_session_end
→ 后台自动消化
→ 下次对话重新读取
```

## Memoria 和 Continuity 同步

默认不自动导入，避免首次启动灌入整个历史。

先设同步游标：

```bash
python -m innerlife.cli sync-memoria --agent my-agent --bootstrap-from-now
python -m innerlife.cli sync-continuity --agent my-agent --bootstrap-from-now
```

再在 `innerlife.env` 中启用：

```bash
INNERLIFE_MEMORIA_SYNC_AGENTS=agent-a,agent-b
INNERLIFE_CONTINUITY_SYNC_AGENTS=agent-a,agent-b
```

- Memoria 只导入有效的可观察事实。
- Continuity 只作为当前位置材料。
- InnerLife 不会把内部想法写回 Memoria。

## 命令行管理

```bash
# 系统诊断
python -m innerlife.cli doctor --json

# 查看对话前简报
python -m innerlife.cli briefing --agent my-agent --json

# 查看输入队列
python -m innerlife.cli inbox --agent my-agent --json

# 手动消化
python -m innerlife.cli digest --agent my-agent --mode light --json

# 查看历史和待分享内容
python -m innerlife.cli history --agent my-agent --json
python -m innerlife.cli pending --agent my-agent --json

# 结合当前对话重新判断分享时机
python -m innerlife.cli share-check \
  --agent my-agent \
  --session-id session_xxx \
  --context-file conversation-context.json \
  --json

# 查看分享判断和处理记录
python -m innerlife.cli share-actions --agent my-agent --json

# 查看活跃状态规模和收敛记录
python -m innerlife.cli convergence-runs --agent my-agent --json

# 手动整理；正常情况下由后台按阈值自动运行
python -m innerlife.cli converge --agent my-agent --json

# 查看稳定认识；归档历史仍可单独查询
python -m innerlife.cli summaries --agent my-agent --json
python -m innerlife.cli history \
  --agent my-agent --include-archived --json

# 手动运行一次自主探索
python -m innerlife.cli explore --agent my-agent --json

# 查看来源、探索记录和经历
python -m innerlife.cli sources --agent my-agent --json
python -m innerlife.cli explorations --agent my-agent --json
python -m innerlife.cli experiences --agent my-agent --json

# 备份
python -m innerlife.cli backup \
  --output ~/.innerlife/backups/innerlife-$(date +%F).db
```

## 模型分层

24 小时在线不等于持续调用大模型：

- 排序、去重、权限、来源和是否有新材料：不用模型。
- 日常 `light digest`：轻量模型。
- 长期冲突、自我修正和深度整理：强模型。

## 验证

```bash
python -m pytest -q
python server/test_mcp_smoke.py

INNERLIFE_DB_PATH=/tmp/innerlife-smoke/innerlife.db \
  python -m innerlife.cli run-scenarios scenarios/phase0_cases.jsonl --json
```

## 自主经历

后台只会在没有活跃对话、间隔足够且没有超过当天上限时探索：

```text
读取公开来源的候选
→ 按 Agent 自己的兴趣和未完成问题选择，或跳过
→ 实际读取原文
→ 判断是否真的带来变化
→ 保存证据
→ 进入 InnerLife 消化
→ 下一次会话可自然带入
```

Agent profile 中通过 `autonomous_sources` 配置订阅的 RSS / 网页来源。每个 agent 可以订阅不同来源。默认示例 profile 预置了哲学与 AI 新闻来源，可自由调整。

## 分享调度

`pending_share` 不再只是被动放进 briefing。

- `when_relevant`：当前对话相关时，经二次判断后自然带入。
- `on_user_asks`：用户明确询问时才考虑。
- `proactive_allowed`：等待成熟后，可以在新会话主动开启一次话题。
- `never_push`：只保留内部记录。

`session_start` 会返回精简 briefing（含 `share_plan`、`open_loops`、
`recent_internal_events`），去掉 `pending_shares` 和 `recent_autonomous_experiences`
以控制返回体积。完整待分享列表请调用 `innerlife_pending_shares`；完整经历列表
请调用 `innerlife_experiences`。对话过程中，宿主可以带当前上下文调用
`share_check`。系统每次最多选择一条，宿主表达后必须回报 `used`、
`deferred` 或 `discarded`。

v2.2 不做会话外通知，也不会在用户没有打开会话时主动联系用户。

v2.4 新增外部推送：`proactive_allowed` + `urgency >= 阈值` 且无活跃会话时，daemon
自动标记 `delivery_status=queued`。外部 cronjob 轮询 `delivery_queue` 并通过
Hermes send_message 发送到飞书等渠道。发送后标记 delivered。

## 内在状态收敛

v2.3 把长期数据分成活跃、摘要和归档三层：

```text
持续形成内部变化和经历
→ 活跃数量超过 profile 阈值
→ 后台选择旧候选进行整理
→ 形成有真实来源的稳定认识
→ 旧内容进入归档
→ briefing 只保留有限的活跃状态
```

归档不是删除。原始内部变化、经历和来源证据仍可查询。

未完成问题可以从 `open` 变为 `dormant`，暂时退出日常 briefing；只有已经明确
解决的问题才会移出状态。

每个 Agent 可以通过 profile 的 `convergence` 配置独立阈值。

## 当前边界

v2 已经可以长期运行，但仍然坚持克制：

- 不主动替用户发送消息。
- 不自动把内部变化写成事实。
- 不允许不同 Agent 读取彼此私有状态。
- 不保证本地小模型能处理所有复杂矛盾；复杂情况应升级到强模型。
- 管理页面是状态管理入口，不是最终视觉产品。

## 从旧版本升级

v2.1 不再自动创建内置人格，也不再包含私人 profile。

旧数据库中的 Agent 会原样保留，不需要重新创建。为保持兼容，如果
`~/.claracore/innerlife` 已经存在，程序仍会继续使用它；全新安装默认使用
`~/.innerlife`。

如果旧配置依赖另一个私有文件提供密钥，请显式设置：

```bash
INNERLIFE_SECRET_ENV_FILE=/path/to/private.env
```
