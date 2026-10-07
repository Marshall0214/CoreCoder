# 事务拒绝原因的一次反馈 v1

## 完成的能力

新增可选 [反馈适配器](experiments/transaction_feedback_v1.py)：模型补丁被事务校验拒绝后，在源文件未改变的条件下请求一次修正，再执行完整事务校验。正常流程最多两次模型请求，始终复用同一个 `BudgetLLM`，不重置 Token 预算。第一个补丁通过事务校验就结束；该结束条件不代表语义正确，最终行为验证由调用方独立完成。

可恢复的编辑失败包括无效补丁、Python 编译错误、新增重复定义、模块加载错误、空回答及截断回答。截断回答即使包含完整 JSON 也不会直接应用。源文件变化、写入故障、导入修改源文件、导入超时、非预期工具响应或服务异常不自动重试。第二次仍失败就停止；预算预检查失败也停止，没有第三次请求。

反馈始终携带被拒绝的补丁和未提交说明；`diagnostic` 模式额外提供具体错误、重复声明信息和最多 2,000 字符的导入 stderr，替换事务目录路径并使用现有秘密脱敏机制。它不读取独立行为检查或最终评分输出。

## 实验设计

[对照程序](experiments/transaction_feedback_probe_v1.py) 使用三个既有人工小任务，并人为注入第一份失败补丁：

| 任务 | 注入故障 | 事务拒绝原因 |
| --- | --- | --- |
| unique-falsey | 不完整的 `return (` | invalid_python |
| preserve-methods | 新增第二个 render，原定义仍存在 | added_duplicate_definitions |
| annotation-import | 使用 typing.DoesNotExist 注解 | import_failed |

每项分别使用 `generic` 和 `diagnostic`：前者只说明补丁被拒绝且未提交，后者增加事务诊断。两组都能看到相同任务描述、完整原始文件和相同失败补丁。参考修复与行为检查留在父进程，不进入真实模型请求。

**第一份失败补丁是人为提供的 seed，不是模型第一轮回答，也不收取模型调用或 Token。** 每分支只请求一次真实反馈，合计 6 次新调用；这不是完整两轮修复的成本或首轮成功率实验。正常两调用模式的预算共享、早停和次数上限由离线回归测试验证。本实验是合成故障恢复诊断，不计入真实仓库修复成功率。

模型保持已校准的 Ollama `qwen3.5:27b` 与模型摘要，原生 `/api/chat`、thinking=false、temperature=0、top_p=0.95、seed=17、上下文 16,000、输出上限 2,048、共享预算上限 15,000。模型身份、任务源文件和适配器哈希冻结；交替执行组别顺序，每项每组仅一次。实际原生请求核对确认，配对输入仅多出 `validation` 诊断字段。

## 结果与决策

| 策略 | 事务通过 | 独立行为通过 | 新模型调用 | 总 Token |
| --- | --- | --- | --- | --- |
| generic | 3/3 | 3/3 | 3 | 1,134 |
| diagnostic | 3/3 | 3/3 | 3 | 1,577 |

所有第一份失败补丁都被正确拒绝，源文件保持不变；反馈回答均正常结束，没有截断或 thinking 内容。6 个修正补丁全部通过事务及独立行为验证。详细诊断没有增加通过数量，Token 多 443（约 39.1%）。这三个任务过小且没有重复，不能推断两种策略等价或哪种在真实仓库更好。

本轮证明有界故障反馈和事务重新验证可以贯通。没有证据支持将详细诊断设为默认策略，因此保留两个可选模式，冻结此次实验；不扩大同一小任务池来宣称修复收益，不修改默认服务或历史真实缺陷评分。

离线对照也为两组各 3/3，但使用人工正确回复，仅验证流程，模型调用为 0，不作为模型能力结果。专项回归共 28 passed（事务保护 16 项、反馈 12 项），覆盖正常两调用、一次反馈、共享预算阻止第二次调用、失败早停、截断处理和配对输入/评分隔离。

机器摘要见 [transaction-feedback-v1.json](transaction-feedback-v1.json)。原始请求、回答、事务结果、Trace 与独立验证日志在 `.tmp/calibration/transaction-feedback-v1-live`；离线记录在 `.tmp/calibration/transaction-feedback-v1-offline`。临时产物不进入 Git，分享完整实验需要另行归档这些目录。

## 复跑

在项目根目录及已有 corecoder 环境中执行，使用全新输出目录：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_transaction_feedback.py tests/test_patch_transaction.py -q -p no:cacheprovider --basetemp .tmp/pytest-transaction-feedback-rerun
python -B -m docs.experiments.transaction_feedback_probe_v1 --output .tmp/calibration/transaction-feedback-rerun-offline
python -B -m docs.experiments.transaction_feedback_probe_v1 --live --output .tmp/calibration/transaction-feedback-rerun-live
```

离线运行和单元测试不依赖历史 `.tmp/` 快照或模型 API；真实对照需要本机 Ollama 与冻结模型身份。新工程产物继续放在 D 盘。

最终 Windows 全量 **983 passed、2 skipped（159.85 秒）**；Ruff、冻结实现哈希和三对真实原生请求核对通过。本轮未重跑 Linux、Docker 或真实 HTTP 验收。
