# InnerLife v2.1 验证记录

## 目标

证明公开仓库不依赖作者的设备、用户名或私人 Agent，并且新用户可以从空白环境完成首次运行。

## 验收范围

- 仓库只包含中性示例 profile。
- 程序不会自动创建任何 Agent。
- 用户必须明确提供 profile 和 user ID。
- 启动脚本自动识别项目目录和 Python。
- 私有密钥只能从用户指定的配置文件读取。
- 旧数据库中的 Agent 和旧数据保持可用。
- 从空目录完成安装、初始化、诊断、会话闭环、后台循环和 MCP 调用。

## 验证命令

```bash
python -m pytest -q
python server/test_mcp_smoke.py
python -m innerlife.cli run-scenarios scenarios/phase0_cases.jsonl --json
```

## 结果

- 36 项自动测试全部通过。
- 9 项边界场景全部通过。
- MCP 真实连接检查通过，共 14 个工具。
- 使用全新的 Python 3.10 虚拟环境完成依赖安装。
- 空白数据库运行 `doctor` 时保持 0 个 Agent，没有暗中创建人格。
- 使用中性 profile 完成初始化。
- 完成会话开始、会话结束和后台单次循环。
- 将项目复制到另一目录后，启动文件正确使用新位置，没有作者设备路径。
- 两个 launchd 文件格式检查通过。
- Python 3.9 会被明确拒绝，避免安装到一半才失败。
- 旧数据目录兼容逻辑保留。

## 结论

v2.1 已满足开源首次使用要求：新用户需要明确创建自己的 Agent 和用户边界，
项目不再依赖作者的私人 profile、用户名、Python 路径或项目位置。
