# 完整种子依赖分析：离线对照 v1

## 本次改动

新增可选 `dependency_scope=full-seed`：已选中的检索种子即使只展示局部窗口，也从该符号的完整 AST 行范围发现本地引用。依赖仍按现有预算独立装填，扩展深度不增加。只对已展示的种子启动完整分析；预算拒绝的种子不分析，普通行窗口不扩成整个文件，后续依赖也不会额外扩大分析范围。

默认 `displayed` 继续只分析展示范围。Trace 中每条可解析依赖边携带分析范围、展示范围、引用是否在展示范围内。`reference_in_displayed_range` 表示同一引用在该范围出现过，不表示每个引用位置均已展示，也不保证依赖最终装得下。

源码范围、路径和版本校验继续适用。分析源码不执行模块，也不赋予修改权限：补丁的 old 文本必须包含在实际展示片段中，并满足原有完整文件版本与唯一匹配检查。测试覆盖“从未展示的引用取回依赖，但拒绝修改该引用”。

## 固定条件与结果

使用已准入 `click-flag-envvar` 开发案例，固定 Python 符号索引、公开查询 `envvar bool flag_value`、5 个种子、6,000 字符正文预算、50% 种子预算上限与依赖深度 1。只有依赖分析范围不同，选择过程不接收官方修复路径、修复后源码或隐藏验收内容。

| 分析范围 | 种子正文 | 依赖正文 | 合计 | BoolParamType |
| --- | ---: | ---: | ---: | --- |
| displayed | 2,214 | 576 | 2,790 | 未发现 |
| full-seed | 2,214 | 3,550 | 5,764 | 发现并完整展示，types.py 661–683 |

两组保留相同种子：完整 Option.resolve_envvar_value、Option.value_from_envvar、Parameter.value_from_envvar，以及局部 Option.__init__。完整分析组额外展示 BoolParamType、IntRange、convert_type，仍包含 batch、Parameter.resolve_envvar_value。大符号 Context、prompt、ParamType 继续被预算拒绝。

BoolParamType 引用来自 Option.__init__ 的完整 2533–2663 行，展示范围仅为 2533–2561 行；Trace 标记该引用未展示。说明此次策略修复了前一步“窗口截断导致引用丢失”的具体问题，没有扩大正文预算。

**这是上下文诊断上的改善，还不是缺陷修复成功。** 本次没有调用模型或生成补丁。完整分析也引入了未必必要的 IntRange 等引用；静态引用并非完整调用图，初始化函数仍不完整。结果只来自已知开发案例的事后检查，不计正式 Recall、留出效果或成功率提升。

## 验证与复现

相关测试 19 passed，覆盖范围切换、预算、禁止修改未展示引用、允许文件与深度限制、版本和补丁防护；本次相关文件 Ruff 通过。全量回归 525 passed、1 skipped。

证据：`.tmp/real-defects/symbol-discovery-v1/comparison.json`，同目录 `displayed.jsonl` / `full-seed.jsonl`。实现摘要 `c3208eb647cd9c4f23fc59b7a7d9bac43a483278d504add5c201eb19f3a180cc`。原预算对照 v1 保留，两组构建均校验上游源码未改变。

```powershell
python -m pytest tests/test_symbol_packing.py tests/test_symbol_context.py tests/test_symbol_index.py -q
python -m evals.compare_symbol_packing --comparison discovery --admission .tmp/real-defects/crossfile-admission-v2/admission.json --output .tmp/real-defects/symbol-discovery-reproduction
python -m pytest tests -q
```

需要已有准入报告和对应源码，输出使用新目录。原预算对照命令不带 `--comparison discovery`，行为仍为两组装填策略对照。

## 下一步

接入有限结构化补丁工作流：携带局部范围、完整性和版本，使用现有 apply_symbol_patch 校验，在独立副本验证目标行为和回归。先做协议与工具验收，再运行真实模型 pilot，报告最终是否成功；不得把此次上下文改善当成修复收益，也不向模型反馈隐藏验收内容。
