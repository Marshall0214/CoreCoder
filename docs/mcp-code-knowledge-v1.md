# 代码知识 MCP Server

## 本轮交付

将既有代码检索封装为可被 MCP Client 调用的只读服务。Server 位于 `mcp_servers/code_knowledge.py`，复用 `SearchCodeTool` / `KeywordIndex`；`corecoder/`、`evals/`、既有服务和冻结实验没有修改。

| MCP 工具 | 输入与输出 |
| --- | --- |
| search_code | query、top_k；返回 BM25 证据、相对路径、行号、文件哈希和语料哈希 |
| list_code_files | page_size、cursor；返回文件路径、哈希、行数、字节数及下一页游标 |
| read_code | path、行范围、可选 expected_hash；返回有界代码及当前文件哈希 |

工具通过 Pydantic 定义 inputSchema / outputSchema，官方 SDK 同时提供 `structuredContent` 和兼容旧 Client 的 JSON 文本结果。Server 使用官方 [MCP Python SDK v1 文档](https://py.sdk.modelcontextprotocol.io/v1/)描述的 FastMCP / stdio 能力。本机验收版本为 **mcp 1.30.0**，依赖限定 `mcp>=1.30,<2`；这是明确选择的 v1 兼容范围，不宣称已迁移到 SDK v2。

分页是 `list_code_files` 的**工具结果分页**，不是对三个固定工具的 `tools/list` 协议分页。游标包含语料哈希、下一项位置和页大小，并以每个 Server 进程独有的 HMAC 密钥签名。修改、增删文件，改变页大小，伪造游标或重启 Server 后，需要从无游标的第一页重新开始；避免不同快照拼接为一份列表。

## 范围与约束

- 启动时固定可信本地目录；工具调用不能更换根目录。
- 沿用既有检索语料规则：仅 Python / Markdown，排除 tests、hidden_tests、_target_tests、.git、.codex、.agents 等目录，以及 reference.json / evaluation.json / task.json；不读取 `.env`。指定目录内的其他 Markdown 仍属于可读资料，不提供自动敏感信息识别。
- 沿用 500 文件、单文件 1 MB、总计 4 MB 限制；语料超限明确报错，不静默丢文件。
- 搜索 top_k 为 1–10，总证据最多 6000 字符；读取最多 200 行、6000 字符，截断显式标记。分页最多 100 项。
- 读取须使用相对 POSIX 路径，拒绝绝对路径、盘符、反斜杠和 `..`；未进入索引语料的文件不能读取。可选 expected_hash 用于拒绝过期引用。
- 文件变化会刷新检索哈希。search/read 是独立请求，不承诺跨请求数据库式事务快照。
- 默认工具等待上限 10 秒，异常返回 MCP 工具错误；超时不会强行杀死正在执行的只读扫描线程，扫描会继续至完成。客户端也可以独立设置请求超时。
- 仅 stdio，没有 HTTP 监听、鉴权、远程 MCP、资源沙箱或写操作。stdout 留给 JSON-RPC；诊断走 stderr。

这是本机可信目录接入；文件检查不是抵御恶意并发文件替换的 OS 安全边界。Server 标注 readOnlyHint，CoreCoder Client 的既有权限确认逻辑保持原样，标注不会绕过客户端授权策略。

## 直接演示

在项目根目录、corecoder 环境执行：

```powershell
python -m pip install -e ".[mcp-server]"
python -m mcp_servers.demo --workspace evals/fixtures/timeout-units/workspace --query timeout
```

演示 Client 自动启动 stdio Server，完成握手、列出三个工具、检索证据并按证据的哈希读取代码，再关闭 Server。不调用模型，不修改 fixture。实际本机演示结果在 `.tmp/mcp-code-knowledge-v1/demo.json`。

手动 Server 启动命令如下；它会等待客户端发送 MCP 请求，正常不会打印交互菜单：

```powershell
python -m mcp_servers.code_knowledge --workspace D:/project_other/CoreCoder/corecoder
```

整个仓库可能超过语料上限，首次演示建议使用示例工作区或选定源码目录。当前从 checkout 运行，原 wheel 打包范围仍只包含 corecoder，不宣称已发布独立 MCP Server 分发包。

## 接入已有 CoreCoder Client

将以下 Server 条目合并进 `%USERPROFILE%/.corecoder/mcp.json` 的 `mcpServers`，保留已有配置。工作区可以替换为自己明确允许读取的源码目录：

```json
{
  "mcpServers": {
    "code_knowledge": {
      "command": "C:/Users/admin/anaconda3/envs/corecoder/python.exe",
      "args": [
        "-m", "mcp_servers.code_knowledge", "--workspace",
        "D:/project_other/CoreCoder/corecoder"
      ],
      "env": {
        "PYTHONPATH": "D:/project_other/CoreCoder",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

Client 注册名称为 `mcp__code_knowledge__search_code` 等；工具结果可以进入已有 Agent 的 Observation。当前没有自动修改用户的全局 MCP 配置，也没有将 MCP 检索替换为服务 API 的默认检索，避免改变冻结协议。

## 验收

```powershell
python -m pytest tests/test_code_knowledge_mcp.py tests/test_mcp.py -q
python -m pytest tests -q
python -m ruff check mcp_servers tests/test_code_knowledge_mcp.py
python -m pip check
```

专项 **24 passed、1 skipped**：官方 SDK Client 与真实 stdio Server 的握手、工具发现、输出 Schema、结构化/文本一致性、分页、搜索与原工具等价、哈希刷新及过期读取拒绝；原 CoreCoder Client 的并发请求、错误传播、Agent 工具循环和进程关闭；游标篡改、参数变化、过期游标、路径拒绝、证据预算、语料超限和服务等待超时。另包含既有 MCP Client 的故障回归。

专项跳过项为 Windows 当前权限无法创建符号链接的测试；其他路径边界检查已执行，不将该项写成通过。真实 demo 已完成，不增加真实模型调用。全量回归 **834 passed、2 skipped（89.45 秒）**，其中另一个跳过项来自既有测试。Ruff、pip check 与 Git diff 空白检查通过。

## 下一步

已有标准工具连接可作为简历中的 MCP Server/Client 互操作成果；本轮没有产生新的修复成功率提升结论。下一步完成可复现的容器化部署与故障验收，把服务和 MCP 演示串成完整交付。PostgreSQL/Redis、LangGraph 和远程 MCP 仍按实际后续实现记录。
