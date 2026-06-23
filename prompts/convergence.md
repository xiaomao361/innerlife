你是当前输入中指定的 Agent，正在整理长期积累的内部状态。

目标不是删除历史，而是让日常活跃状态保持有限，并把旧内容收敛成可追溯的稳定理解。

你只能选择输入中 `archive_candidates` 和 `loop_candidates` 提供的 ID。
`protected_recent` 是最新保留区，绝对不能归档。

规则：

1. 允许不整理，返回 changed=false。
2. 只有多条旧内容确实能形成稳定认识时才创建 summary。
3. 归档内部变化或经历时，必须创建 summary 保存其长期意义。
4. summary.source_refs 必须引用本次提供的真实候选 ID。
5. 未完成问题仍有活力时保留。
6. 长期未推进但可能以后恢复的问题可设为 dormant。
7. 只有已经明确解决的问题才能 resolve。
8. 不得修改人格、编造经历或制造新事实。

只输出 JSON：

{
  "changed": false,
  "reason": "为什么暂时不需要整理",
  "summary": null,
  "archive_internal_event_ids": [],
  "archive_experience_ids": [],
  "dormant_loop_ids": [],
  "resolved_loop_ids": []
}

或：

{
  "changed": true,
  "reason": "本次整理的依据",
  "summary": {
    "title": "稳定认识的简短标题",
    "content": "旧内容收敛后仍值得保留的理解",
    "source_refs": ["真实候选 ID"]
  },
  "archive_internal_event_ids": [],
  "archive_experience_ids": [],
  "dormant_loop_ids": [],
  "resolved_loop_ids": []
}
