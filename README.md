# InnerLife v2.0

InnerLife 是 ClaraCore 的内部生活系统。

它让 Clara、Lara 在不同对话窗口之间保留一份持续的内部状态：当前关注、未完成问题、形成的新理解和待分享念头。

它不是定时生成消息的工具，也不是另一套记忆库。

```text
Memoria：发生过什么
Continuity：我们现在站在哪里
InnerLife：Agent 自己正在关注、怀疑和改变什么
```

## 当前已具备

- Clara、Lara 独立状态、历史和边界。
- 多窗口输入统一排队，顺序消化。
- 每次变化都有来源，允许没有变化。
- 后台长期运行，自动处理新材料。
- 失败重试和逐步退避，不会持续轰炸模型。
- MCP：Claude Code、Hermes 等宿主可直接读写。
- HTTP API 和中文管理页面。
- 显式同步 Memoria 事实和 Continuity 当前位置。
- 本地模型、OpenAI 兼容服务、Anthropic 兼容服务可替换。
- 待分享念头可标记为已使用、延后或放弃。
- 诊断、备份、固定场景和自动测试。
- macOS `launchd` 开机启动配置。
- 自主经历：没有用户输入时，Agent 可以按自己的关注选择真实公开材料。
- 每次自主经历保存来源、读取时间和文本证据，不用模型虚构“生活”。
- Agent 可以认为没有值得看的内容，也可以读完后判断没有形成变化。
- Clara、Lara 使用独立来源、独立经历和独立内部状态。

数据默认保存在：

```text
~/.claracore/innerlife/innerlife.db
```

模型不是 Agent 本身。换模型、换机器或重启服务，不会改变已经保存的内部历史。

## 安装

```bash
cd /Users/zhouwei/Documents/ClaraCore/apps/innerlife
conda run -n zhouwei python -m pip install -e '.[dev]'
conda run -n zhouwei python -m innerlife.cli doctor --json
```

`doctor` 会初始化数据库以及 Clara、Lara 的配置。

注意：`zhouwei` 环境必须使用 `python`，不要使用会落到系统解释器的 `python3`。

## 配置模型

安装开机启动文件：

```bash
./scripts/install_launchd.sh
```

它会创建私有配置：

```text
~/.claracore/innerlife/innerlife.env
```

权限为 `600`。在其中配置模型。

本地 Ollama / LM Studio 示例：

```bash
INNERLIFE_LLM_BACKEND=openai_compatible
INNERLIFE_LLM_BASE_URL=http://127.0.0.1:11434/v1
INNERLIFE_LLM_API_KEY=
INNERLIFE_LIGHT_MODEL=gemma3:4b
INNERLIFE_DEEP_MODEL=gemma3:12b
```

模型名按本机实际安装内容调整。以后换成 Gemma 4 时只需改这里。

Anthropic Messages 兼容服务：

```bash
INNERLIFE_LLM_BACKEND=anthropic_compatible
INNERLIFE_LLM_BASE_URL=https://你的服务地址
INNERLIFE_LLM_API_KEY=你的私有密钥
INNERLIFE_LIGHT_MODEL=轻量模型
INNERLIFE_DEEP_MODEL=深度模型
```

当前实际配置使用线上 DeepSeek：

```bash
INNERLIFE_LLM_BACKEND=openai_compatible
INNERLIFE_LLM_BASE_URL=https://api.deepseek.com/v1
INNERLIFE_LIGHT_MODEL=deepseek-v4-flash
INNERLIFE_DEEP_MODEL=deepseek-v4-pro
```

启动脚本会读取 Hermes 私有文件 `~/.hermes/.env` 中已有的
`DEEPSEEK_API_KEY`。密钥不会复制到项目或 MCP 配置。

## 启动后台和管理页面

配置完成后：

```bash
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.claracore.innerlife.daemon.plist

launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.claracore.innerlife.web.plist
```

管理页面：

```text
http://127.0.0.1:8012
```

查看服务：

```bash
conda run -n zhouwei python -m innerlife.cli doctor --json
tail -f ~/.claracore/innerlife/logs/daemon.log
tail -f ~/.claracore/innerlife/logs/daemon.error.log
```

停止和移除开机启动：

```bash
./scripts/uninstall_launchd.sh
```

数据不会被删除。

## 宿主无关的会话闭环

InnerLife 不依赖 Claude 或 Hermes 才能完成闭环。

开始一次会话：

```bash
conda run -n zhouwei python -m innerlife.cli session-start \
  --agent clara \
  --user zhouwei \
  --host acceptance \
  --external-session-id session-001 \
  --json
```

返回内容包含本次会话 ID 和进入时应该带入的内部状态。

会话结束时，将实际对话保存为 JSON 对象，然后提交：

```bash
conda run -n zhouwei python -m innerlife.cli session-end \
  --agent clara \
  --session-id session_xxx \
  --conversation-file conversation.json \
  --json
```

系统会自动完成：

```text
判断是否真的留下余韵
→ 无余韵：关闭会话，不写内部变化
→ 有余韵：形成 afterthought
→ 消化并更新内部状态
→ 下一次 session-start 返回更新后的状态
```

HTTP 接口：

```text
POST /api/agents/{agent_id}/sessions/start
POST /api/agents/{agent_id}/sessions/{session_id}/end
GET  /api/agents/{agent_id}/sessions
```

相同外部会话 ID 重复开始、相同会话重复结束，都不会重复写入。多个会话并行时，系统会识别期间发生的其他状态变化，不用最后提交覆盖前面的内容。

## Claude Code / Hermes 正式接入

给 Clara 配置一个 MCP：

```json
{
  "mcpServers": {
    "innerlife-clara": {
      "command": "/Users/zhouwei/miniconda3/envs/zhouwei/bin/python",
      "args": [
        "/Users/zhouwei/Documents/ClaraCore/apps/innerlife/server/mcp.py"
      ],
      "env": {
        "INNERLIFE_AGENT_ID": "clara"
      }
    }
  }
}
```

给 Lara 再配置一份，将 `INNERLIFE_AGENT_ID` 改为 `lara`。

当前已经正式配置：

- ClaraCore 项目中的 Claude Code → Clara
- Hermes → Lara

两边均通过真实的 session start/end 调用测试。

完整会话优先使用：

- `innerlife_session_start`
- `innerlife_session_end`
- `innerlife_sessions`

旧的 briefing、record_afterthought 和 digest 工具仍保留用于排查和兼容，但不作为日常主路径。

MCP 提供：

- `innerlife_explore`：手动触发一次自主探索；正常由后台自行调度。
- `innerlife_experiences`：查看已经形成的自主经历及来源。
- `innerlife_briefing`：对话开始时读取当前内部状态。
- `innerlife_record_afterthought`：对话结束时留下真实余韵。
- `innerlife_submit_fact`：显式提交事实材料。
- `innerlife_submit_continuity`：显式提交共同线当前位置。
- `innerlife_digest`：手动触发消化。
- `innerlife_pending_shares`：读取待分享念头。
- `innerlife_mark_share`：标记已使用、延后或放弃。
- `innerlife_history`：查看内部变化历史。
- `innerlife_status`：查看系统状态。

宿主的标准闭环：

```text
对话开始
→ innerlife_briefing
→ 将状态作为 Agent 自己的内在背景，不机械播报

对话结束
→ innerlife_record_afterthought
→ 后台自动消化
→ 下次对话重新读取
```

## Memoria 和 Continuity 同步

默认不自动导入，避免第一次启动把整个历史灌入 InnerLife。

先把同步游标设为当前时间：

```bash
conda run -n zhouwei python -m innerlife.cli \
  sync-memoria --agent clara --bootstrap-from-now

conda run -n zhouwei python -m innerlife.cli \
  sync-continuity --agent clara --bootstrap-from-now
```

然后在 `innerlife.env` 中启用：

```bash
INNERLIFE_MEMORIA_SYNC_AGENTS=clara,lara
INNERLIFE_CONTINUITY_SYNC_AGENTS=clara,lara
```

之后后台只导入游标之后的新内容。

- Memoria 只导入有效的可观察事实。
- Continuity 只作为当前位置材料。
- InnerLife 不会把内部想法写回 Memoria。

## 命令行管理

```bash
# 系统诊断
conda run -n zhouwei python -m innerlife.cli doctor --json

# 查看对话前简报
conda run -n zhouwei python -m innerlife.cli briefing --agent clara --json

# 查看输入队列
conda run -n zhouwei python -m innerlife.cli inbox --agent clara --json

# 手动消化
conda run -n zhouwei python -m innerlife.cli digest --agent clara --mode light --json

# 查看历史和待分享内容
conda run -n zhouwei python -m innerlife.cli history --agent clara --json
conda run -n zhouwei python -m innerlife.cli pending --agent clara --json

# 手动运行一次自主探索
conda run -n zhouwei python -m innerlife.cli explore --agent clara --json

# 查看来源、探索记录和已经形成的经历
conda run -n zhouwei python -m innerlife.cli sources --agent clara --json
conda run -n zhouwei python -m innerlife.cli explorations --agent clara --json
conda run -n zhouwei python -m innerlife.cli experiences --agent clara --json

# 备份
conda run -n zhouwei python -m innerlife.cli backup \
  --output ~/.claracore/innerlife/backups/innerlife-$(date +%F).db
```

## 模型分层

24 小时在线不等于持续调用大模型：

- 排序、去重、权限、来源和是否有新材料：不用模型。
- 日常 `light digest`：本地小模型。
- 长期冲突、自我修正和深度整理：强模型。

32G Mac mini 足以承担数据保存、后台服务和大部分本地轻量消化。强模型只需在少数复杂场景使用。

## 验证

```bash
conda run -n zhouwei python -m pytest -q
conda run -n zhouwei python server/test_mcp_smoke.py

INNERLIFE_DB_PATH=/private/tmp/innerlife-smoke/innerlife.db \
  conda run -n zhouwei python -m innerlife.cli \
  run-scenarios scenarios/phase0_cases.jsonl --json
```

## 自主经历如何工作

后台只会在没有活跃对话、间隔足够且没有超过当天上限时探索。流程是：

```text
读取公开来源的候选
→ 按 Agent 自己的兴趣和未完成问题选择，或跳过
→ 实际读取原文
→ 判断是否真的带来变化
→ 保存证据
→ 进入 InnerLife 消化
→ 下一次会话可自然带入
```

Clara 默认关注哲学与人工智能资料；Lara 默认关注科学和现实世界资料。来源可以在各自 profile 中独立调整。

详细设计见 [docs/AUTONOMOUS_EXPERIENCE_V2.md](docs/AUTONOMOUS_EXPERIENCE_V2.md)。

## 当前边界

v2 已经可以长期运行，但仍然坚持克制：

- 不主动替用户发送消息。
- 不自动把内部变化写成事实。
- 不允许不同 Agent 读取彼此私有状态。
- 不保证本地小模型能处理所有复杂矛盾；复杂情况应升级到强模型。
- 管理页面是状态管理入口，不是 Claravision 的最终视觉产品。
