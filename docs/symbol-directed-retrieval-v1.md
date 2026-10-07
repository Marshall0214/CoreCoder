# 符号定向检索与唯一原文匹配

2026-10-07。本轮实现任务描述驱动的函数优先排序，保持唯一原文匹配、单次调用和独立验证。默认引擎、服务、冻结评分与历史实验没有修改。

## 实现

[检索适配器](experiments/symbol_directed_retrieval_v1.py)从允许的 Python 源文件构建 AST 函数索引，不执行源码。

- 优先解析 `HelpFormatter.write_usage` 等限定名、带下划线标识符、反引号及调用语法中的名字。
- 对 `echo must ...`、`style and secho must ...` 等要求的主语识别裸函数名；普通词与函数同名不自动提升。
- 同名裸方法结合描述中的类名消歧；限定名仍重复时也不任意选择文件。
- 未解析或仍有歧义时不提升候选，保留 BM25 排序；只有类名时不猜测构造方法。
- 完整函数按原规则装填：最多五片段、6000 原始字符、无依赖扩展；超大函数跳过并记录，不截断或扩大预算。
- 所有证据带源码路径、原始行范围及全文哈希，生成 Worker 输入前校验版本和精确引用。

名称识别是确定性规则，不是语义理解或别名解析器；裸名主语规则仍可能误判业务名词，也可能漏掉其他自然语言表达。当前不解析再导出的模块别名、动态方法或非 Python 代码。只保证静态候选的身份与版本，不保证点名函数就是缺陷的根因。

## 对照协议

[执行器](experiments/symbol_directed_repair_v1.py)对既有 Click/ItsDangerous 六项任务，每种方案三次新调用，总计 36 分支。

| 固定项 | 条件 |
| --- | --- |
| 模型 | Ollama qwen3.5:27b，固定 digest，temperature=0、reasoning=none |
| 语料与装填 | 同一 AST 完整函数索引，同一 BM25 查询、字符上限、片段数和装填算法 |
| 补丁 | 同一冻结 Worker/Prompt，`old` 必须来自证据且在源文件唯一出现 |
| 调用与预算 | 每分支一次模型调用、无工具，15000 Token，输出最多 2048 Token |
| 工作区与评分 | 独立 before 副本、相同 Target/Controls、相同修改范围限制 |
| 变化项 | 公开描述中无歧义符号的排序优先级 |

基线选用原完整函数 BM25，而不是行块，避免将完整函数边界的收益归因于符号排序。先保存全部公共检索结果，再进行独立预检与模型修复；评分信息不进入检索或 Worker 输入。这是输入隔离协议，不是操作系统沙箱。

原型诊断曾把 `argument`、`output` 等普通词误认成函数。该尝试已停止并保留 `complete=false` 和实现快照，不纳入正式对照，也不把停止的调用用量当作零。正式对照使用收紧后的规则和新输出目录。

## 检索诊断

| 任务 | 原完整函数检索覆盖 | 符号定向覆盖 |
| --- | --- | --- |
| click-usage-empty | 1/1 | 1/1 |
| click-echo-empty-bytes | 1/1 | 1/1 |
| click-style-color-validation | 2/2 | 2/2 |
| itsdangerous-none-salt | 不适用：仅点名类 | 不适用：仅点名类 |
| itsdangerous-future-age | 1/1 | 1/1 |
| itsdangerous-malformed-time | 0/2 | 2/2 |
| 合计 | 5/7（71.43%） | 7/7（100%） |

这里的分母是规则明确解析出的七个不同函数引用，不是参考补丁涉及函数、完整缺陷覆盖率或修复成功率。引用集合每项任务只统计一次，不因三轮修复而扩大为 21 个不同函数。改善来自 `TimestampSigner.validate`、`TimedSerializer.loads_unsafe` 两个被点名的方法进入上下文。

`HelpFormatter.write_usage` 在原完整函数策略中已经出现，新方案将它提升到首位。这一点与上轮行块方案遗漏实现的诊断分别报告，不能声称本轮新找到了原完整函数方案没有找到的方法。

## 三轮修复结果与决策

正式对照完整完成 36 次新调用，没有补丁匹配错误、预算停止或缺失用量；详见 [版本化结果与哈希](symbol-directed-repair-v1.json)。

| 指标 | 原完整函数 BM25 | 符号定向 |
| --- | --- | --- |
| 独立验证通过 | 12/18（66.67%） | 12/18（66.67%） |
| 每轮通过 | 4/6、4/6、4/6 | 4/6、4/6、4/6 |
| invalid_patch | 0 | 0 |
| 总 Prompt + Completion Token | 47,886 | 47,697 |
| Worker 总秒数 | 194.9652 | 195.6127 |

全部 18 对结果一致：12 对两方案通过，6 对两方案失败，没有仅新方案通过或仅基线通过的配对。Token 差 189（约 0.39%），不宣称实质成本或速度优势；Worker 时间受加载、缓存及调用顺序影响。

四个成功任务是 echo-empty-bytes、style-color-validation、future-age、malformed-time。两个失败任务是 usage-empty 和 none-salt，各方案三轮均未通过 Target；Controls 和修改范围检查通过，Worker 状态均为 completed。

失败案例区分：

- `usage-empty`：两方案都已提供完整 `HelpFormatter.write_usage`。补丁调整了空参数分隔符，却仍把空参数交给会产生空结果的包装逻辑，未正确生成所需 usage 行；排序提升没有解决这个语义缺口。
- `none-salt`：新方案与基线证据相同；生成补丁仅把 `make_signer(salt)` 改为 `make_signer(salt=salt)`，没有改变 None 与默认盐值的行为。该任务只有类名，不计入显式函数覆盖分母，不能声称已覆盖其全部关键实现。

**决策：保留可选实验，不替换默认策略。** 本轮完成可追溯的符号检索机制和误识别防护，但没有成功率改善证据。后续应针对两个失败任务分析补丁语义及实际必要上下文，再单独设计有预算上限的公开自检/反馈协议；独立评分仍不能作为模型可见反馈，也不继续无依据扩大 Token 预算或堆叠检索变体。

## 复跑

真实实验仍依赖两套冻结准入快照与隔离环境，位于 `.tmp/real-defects/validation-admission-v1-final`、`second-repo-admission-v1-final`；仅 clone 不包含这些产物。模型身份、输入或评分哈希变化时执行器拒绝继续。

在项目根目录及已有 corecoder 环境中，选择未使用的 D 盘输出目录：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_symbol_directed_retrieval.py -q -p no:cacheprovider --basetemp .tmp/pytest-symbol-directed-user
python -B -m docs.experiments.symbol_directed_repair_v1 --output .tmp/real-defects/symbol-directed-user --repeat 3
```

`--repeat` 可选 1～3。中途停止保留逐项结果和未完成标记；缺失用量不计为零，不完整配对单列。任务已经被查看，结果属于小样本探索；评分只覆盖独立 Target/Controls，不代表完整上游回归。

## 验证

相关回归 47 passed；最终 Windows 全量 901 passed、2 skipped，163.05 秒。新增三个 Python 文件 Ruff 检查通过。三轮协议、模型/源码/证据/评分哈希及每分支单调用检查通过；本轮未重跑 Linux/容器/HTTP 故障验收。

原始快照、日志和暂停原型源码位于被 Git 忽略的 `.tmp/`；版本化 JSON 保存结果、协议、回答与补丁哈希，没有打包全部原始产物。
