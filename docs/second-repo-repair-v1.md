# 第二仓库六次修复与当前检索实验收束

## 结果

ItsDangerous 三项任务、两种策略各运行一次，共六次新模型调用。行块与完整函数均通过 **2/3**，全部任务保留。无预算超限、超时、非法补丁或基础设施错误；所有调用 usage 完整，没有新增 Embedding 调用。

| 任务 | Python 行块 | 完整函数 |
| --- | --- | --- |
| none-salt | failed_verification | failed_verification |
| future-age | passed | passed |
| malformed-time | passed | passed |

| 三次调用合计 | Prompt Token | Completion Token | 总 Token | Worker 秒 |
| --- | ---: | ---: | ---: | ---: |
| 行块 | 6754 | 1281 | 8035 | 39.0788 |
| 完整函数 | 6476 | 794 | 7270 | 23.7870 |

完整函数总 Token 约少 9.5%，Worker 时间包含进程开销；每项仅一次调用，不能认定稳定效率收益。passed 仅代表独立 Target/Controls 通过，没有运行完整上游测试。

none-salt 的行块分支只改了文档字符串，函数分支将 make_signer(salt) 改为等价的 make_signer(salt=salt)。二者补丁合法但均没有修复 salt=None 的实际签名行为，不能计分。失败补丁和日志全部保留，本轮不追加反馈、人工提示或重试。

函数分支已提供 Serializer.__init__ 与 Signer.__init__ 的完整代码，不能简单把这次失败归因于没有定位到构造函数。这里只能确认所提供证据没有促成正确的行为补丁，尚不能分离模型理解与缺少依赖上下文的影响。

## 公平性与实现

新增 `docs/experiments/second_repo_repair_v1.py`，桥接此前固定 ItsDangerous 公开投影和独立验证器。未修改 corecoder/evals 引擎、旧检索策略或旧模型 Worker。校验冻结清单、候选、公开任务、准入报告、源码、检查及旧策略摘要；所有任务先生成公开证据并写盘，再打开 after 和评分材料。

沿用公开需求加字面量 `contract contracts` 的查询、Python 40 行块/完整函数、BM25、五个种子、6000 字符证据预算。固定 qwen3.5:27b、temperature=0、reasoning=none、2048 输出 Token、15000 总 Token、16000 窗口、单次片段补丁、无工具和无反馈；任务间交错策略顺序，每次干净工作区。

公开输入仅含需求、允许的整个 src/itsdangerous Python 包及带版本证据，不包含 after、参考修改范围或隐藏测试。补丁仍需符合原片段替换协议；父进程检查范围，在干净评分副本执行 ItsDangerous Target/Controls，并验证包及子模块源代码来源。before/after 准入再次核验，运行结束后检查原快照与评分摘要未变。

新增测试覆盖输入篡改、公开/私有材料隔离、先检索后评分、六次交错新调用、Controls 失败拒绝、干净评分副本及包外修改拒绝。

相关测试 **11 passed**；最终全量回归 **800 passed、1 skipped（77.31 秒）**，新增代码 Ruff 通过，Git diff 空白检查通过。

## 复现与产物

```powershell
python -m pytest tests/test_second_repo_repair.py -q
python -m pytest tests -q
python -m docs.experiments.second_repo_repair_v1 --output .tmp/real-defects/second-repo-repair-rerun
```

需已有冻结的 second-repo-admission-v1-final 产物、记录的隔离测试解释器及身份匹配的 Ollama 模型。输出必须不存在。正式目录 `.tmp/real-defects/second-repo-repair-v1` 保存 protocol、observations、experiment、请求、回答、Trace、patch.diff 和 Target/Controls 日志。产物受 .gitignore 忽略，需独立归档。

```text
experiment:   1c6bfc41e850f98651d00afcb5119f4385ac1470d40e05edfd742f7ae0b04e9a
observations: d9845690ea4a6a0aa155ee866ef8adae851d627f1dd42efeca9f4713be7bd61f
adapter:      af87e726f4a36a66c5d43dd9e53341d7f5ce951312d9b5bcc7848ff9927c3344
```

## 本阶段结论与交付范围

| 独立报告 | 行块 | 完整函数 | 解释 |
| --- | --- | --- | --- |
| Click 七项开发任务、三轮 | 0/21 | 3/21 | 成功只来自 invoke-missing，属于开发结果 |
| Click 三项验证任务、评分 v2 三轮新调用 | 3/9 | 6/9 | 差异只来自颜色校验；任务已被查看 |
| ItsDangerous 三项任务、单轮 | 2/3 | 2/3 | 未复现成功率优势 |

对应前两项报告为 `function-index-repair-repeat-v1.md` 和 `validation-repeat-v2.md`。不同任务池和重复次数不能直接拼成一个统一成功率。当前可以交付可运行检索策略、独立修复验证、受控对照、Trace、成本记录与可追溯失败分析；不能声称普遍提高修复率、优于 Codex/Claude Code、必要多文件修复能力或生产规模可靠性。

**本轮收束最小检索实验交付，不宣称整个 JD 项目已经完成。**计划中的约 20 项真实案例、完整跨文件基准、全部组合消融和每项重复运行尚未全部达成。本批不再继续扩样或调参，函数策略保留为可选实验分支。未来增加数据/模型需要另立协议，不覆盖已有结论。

为尽快形成完整可演示项目，下一阶段直接交付 FastAPI 服务 MVP：任务提交、查询、事件流和取消，独立 Worker/工作区接入已有修复及验证流程；先以现有机制实现端到端演示与并发隔离。PostgreSQL/Redis、LangGraph、自建 MCP Server 和 Docker/Linux 按明确验收逐项补齐，未实现的能力不写成简历成果。
