# InnerLife v2.2：分享调度层

## 1. 问题

InnerLife 已经能形成 `pending_share`，但 v2.1 只把它放进 briefing。

这会产生一种半完成状态：

```text
Agent 已经有了想说的内容
→ 每次会话都能看见
→ 但没有系统再次判断现在是否适合说
→ 内容可能永久 pending
```

修改 `share_mode` 本身不能解决问题。模式、紧迫度、相关度和新颖度必须被真实调度流程使用。

## 2. v2.2 目标

建立从“想说”到“决定现在说”的闭环：

```text
形成待分享念头
→ 等待
→ 结合时间、模式、当前对话和频率限制重新判断
→ 本次自然带入 / 主动开启话题 / 继续等待 / 放弃
→ 宿主表达
→ 宿主回报结果
```

## 3. 主动性的三个层级

### 自然带入

当前对话与念头直接相关时，宿主可以自然说出。

### 主动开启话题

即使当前没有相关话题，已经成熟的 `proactive_allowed` 内容可以在新会话开始时开启一次话题。

### 会话外打断

通知、消息或其他外部推送不属于 v2.2。

v2.2 不会在用户没有打开会话时主动联系用户。

## 4. 分享模式

- `when_relevant`：只有当前对话相关时才能说。
- `on_user_asks`：只有用户明确询问想法、近况或待分享内容时才能说。
- `proactive_allowed`：等待成熟后，可以在会话开始时主动开启话题。
- `never_push`：只保留内部记录，不进入分享调度。

不新增只有名称、没有行为的模式。

## 5. 二次判断

分享调度器接收：

- Agent profile 和分享政策
- 当前 pending shares
- 分享创建时间和延后次数
- 当日已经主动分享的次数
- 当前会话上下文（有时为空）

每次最多选出一条，并返回：

```json
{
  "decision": "share_now | wait | discard",
  "share_id": "share_xxx",
  "delivery_style": "natural | proactive",
  "reason": "为什么现在说、继续等或放弃",
  "suggested_opening": "给宿主的表达意图，不要求逐字照读"
}
```

模型只能从真实存在的 pending share 中选择。

## 6. 两个判断时机

### 会话开始

检查已经等待足够久的 `proactive_allowed` 内容。

如果选中，`session_start` 返回一条 `proactive_opener`。宿主可以自然表达，但不能机械播报字段。

### 对话进行中

宿主把当前对话摘要交给 `share_check`。

调度器判断 `when_relevant`、`on_user_asks` 和 `proactive_allowed` 内容是否与当前对话形成真实时机。

## 7. 回报闭环

宿主表达后必须回报：

- `used`：已经说出。
- `deferred`：这次没有说，继续等待。
- `discarded`：已经不值得说。

`deferred` 不再等同于从队列移除。它会增加延后次数并回到等待状态。

系统保存每次评估、呈现和最终结果，避免 pending share 永久无记录地悬挂。

## 8. 克制规则

- 每次会话最多主动开启一个话题。
- 每天主动开启次数受 `max_proactive_per_day` 限制。
- 同一条内容不会在短时间内重复呈现。
- 过期内容直接放弃。
- 多次延后或等待过久的内容必须重新判断。
- `urgency` 不能绕过用户边界或每日上限。
- `when_relevant` 不会因为放得久就自动升级为主动打断。

## 9. 完成标准

1. `session_start` 能返回成熟的主动开场内容。
2. 当前没有合适内容时返回空计划。
3. 宿主可在对话中提交上下文进行相关性判断。
4. 每次最多选一条。
5. 每日主动上限真实生效。
6. 已呈现内容短时间内不会重复呈现。
7. `used` 后从 pending 队列消失。
8. `deferred` 后仍保留，但延后次数增加。
9. `discarded` 和过期内容不再出现。
10. 每次评估和结果都有记录。
11. 不支持会话外通知。
12. 旧数据库无需手工迁移。

## 10. v2.3 已知问题与修复（2026-06-24）

### Digest prompt 过于保守

原 prompt: "不要求产生待分享内容。pending_shares 可以为空。" → LLM 几乎从不产出 share。

修复：改为鼓励产出 + 交给 ShareScheduler 二次判断。分享门槛从"重大发现"降到"用户可能感兴趣"。

### source_refs 校验过严

LLM 引用 memoria / autonomous_experience ID 时，evaluator 的 `allowed_refs` 只包含当前 inbox batch 的 ID，导致已验证的系统条目也被拦截。

修复：
- `evaluator.py`: memoria-prefixed refs 放宽校验（匹配 `memoria_agent_uuid` 模式即放行）
- `digest.py`: allowed_refs 加入 `autonomous_experiences` 的 ID
- `digest.py`: LLM 截断 UUID（如 `memoria_lara_abc12345`）自动匹配完整 inbox ID
