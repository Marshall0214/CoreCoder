# 补丁定位优化与真实对照

2026-10-07。**行号定位减少了原文匹配错误，但没有提高本轮修复率，保留原默认方案。**

## 问题与改动

诊断三组历史实验的 66 次调用，发现 12 次 `invalid_patch`，每次至少有一个 `old` 文本不存在于源码。其余 54 次 `completed` 仅表示输出被应用，不代表修复通过。不同任务池不能合并成统一成功率。计数、错误及原始输入/输出哈希见 [诊断记录](anchored-patch-failure-audit-v1.json)。

新增可选实验适配器 [anchored_patch_v1.py](experiments/anchored_patch_v1.py)：模型返回片段编号、原始绝对行范围和替换文本；不再复制 `old`。应用前验证片段与全文哈希、允许路径、行范围、重叠和全部编辑字段。验证失败时不写入任何文件；实际文件写入不保证跨文件 I/O 事务原子性。

第一轮暴露了完整行替换的边界问题：模型省略末尾换行时，新文本与下一行粘连。已修正为保留源码终止符，空文本按删除处理；LF、CRLF、多行编辑、删除和无换行 EOF 均有测试。初版代码保存在首轮输出的 `implementation/`，结果未覆盖。

引擎、默认工具和评分没有修改。该适配器仍是单次补丁实验，未接入默认服务，未增加重试或扩大预算。

### 已有唯一匹配能力与下一步

原 [edit_file](../corecoder/tools/edit.py) 已采用唯一原文匹配：零匹配返回错误与文件预览，多匹配要求补充上下文，一次匹配才写入并返回 diff。[实验补丁验证](../evals/fixed_evidence.py)也要求 `old` 精确匹配一次；[片段验证](../evals/symbol_context.py)进一步要求原文确实出现在模型收到的证据中。当前缺少的不是唯一匹配规则。

区别在于原工具能够在 Agent 多轮循环中返回反馈；本轮实验固定一次模型调用，失败后不会重新读取源码、重新锚定。后续应保留唯一原文匹配，先解决关键实现缺失，再以独立协议验证有上限的“匹配失败反馈 → 读取公开源码 → 重新锚定”。零匹配或多匹配仍然不写入，不自动选择第一处、不使用模糊替换；重试也必须计入统一预算。唯一匹配保证文本定位没有歧义，不能替代修复语义的独立验证。

## 实测

[配对执行器](experiments/anchored_patch_comparison_v1.py)对六个已有任务开展两轮独立对照，每轮 12 次全新模型调用。每个版本各一次，不把两轮合并为重复实验或更大的任务池。模型为固定 digest 的 Ollama `qwen3.5:27b`，temperature=0、reasoning=none、无工具、一次调用、输出上限 2048、任务 Token 预算 15000。两方案使用相同原始行块证据、最多五片段和 6000 字符上限；行号注释增加了 Prompt Token，所有用量计入。

| 版本 | 原文匹配通过 | 行号定位通过 | 原文匹配 invalid_patch | 行号定位 invalid_patch |
| --- | --- | --- | --- | --- |
| 初版 | 3/6 | 2/6 | 2 | 0 |
| 换行边界修正后，新调用 | 3/6 | 3/6 | 2 | 0 |

修正后原文匹配共 **15,805 Token**，行号方案 **18,533 Token**，增加约 **17.3%**。两种方案修复了同样三项；没有仅行号方案通过的任务。`invalid_patch=0` 包含两次空编辑和一次只修改文档的错误修复，不能表述为六次有效修复。

| 任务 | 修正后原文匹配 | 修正后行号定位 | 失败观察 |
| --- | --- | --- | --- |
| click-usage-empty | invalid_patch | failed_verification | 返回空编辑；证据包含调用者，缺少 formatting.py 中被点名方法的实现 |
| click-echo-empty-bytes | passed | passed | 两方案通过 |
| click-style-color-validation | invalid_patch | failed_verification | 行号方案返回空编辑 |
| itsdangerous-none-salt | failed_verification | failed_verification | 行号方案只修改文档字符串，没有修复行为 |
| itsdangerous-future-age | passed | passed | 两方案通过 |
| itsdangerous-malformed-time | passed | passed | 换行边界修正后行号方案通过 |

摘要及协议/源码/模型/评分/回答哈希见 [版本化结果](anchored-patch-comparison-v1.json)。Worker 耗时也保留在 JSON，但受加载、缓存和调用顺序影响，不据此宣称稳定加速。验收仅覆盖独立 Target/Controls 与修改范围，不等于完整上游测试。

这六项任务已被查看，每个版本只有一次调用，因此结论仅限本次探索。现在更值得优化的是**确保任务明确点名的函数实现进入证据预算**，再检查完整函数和依赖上下文；只改变补丁格式或提高 Token 预算不能补齐缺失的代码。

## 复跑

真实实验依赖 `.tmp/real-defects/validation-admission-v1-final`、`second-repo-admission-v1-final` 的准入快照与隔离环境，以及报告记录的本地模型身份。仅 clone 不包含这些原始产物；条件不满足时执行器拒绝运行。评分、准入快照和原始源码不传入模型输入；这是输入隔离协议，不是操作系统沙箱。

在项目根目录运行，替换输出目录为未使用的 D 盘路径：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_anchored_patch.py -q -p no:cacheprovider --basetemp .tmp/pytest-anchored-user
python -B -m docs.experiments.anchored_patch_comparison_v1 --output .tmp/real-defects/anchored-patch-user --repeat 1
```

协议和全部公共检索结果在调用前落盘；运行中校验哈希，每个分支独立复制工作区，逐项保存结果；中途停止保留 `complete=false`。`--repeat` 可选 1～3，未配对完成的记录单列，缺失用量不当作零。

## 最终验证

- 新方案及已有评测适配器回归：41 passed。
- Windows 全量测试：882 passed、2 skipped，162.85 秒。
- 三个新增 Python 文件 Ruff 检查通过；Git 空白检查通过。
- 两轮均完成 12 次新调用，模型/引擎/证据/评分与实现哈希校验通过。

上述计数是代码回归，不能替代真实缺陷修复率；本轮未重新运行 Docker/Linux 或 HTTP 故障验收，原验收记录保留。
