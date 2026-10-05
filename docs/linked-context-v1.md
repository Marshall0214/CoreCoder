# 同预算实例别名上下文与模型 pilot v1

## 实现

新增可选 linked 上下文装填策略，使用原检索结果及 AST 分析候选，不硬编码 Click 的路径、类名或属性名。

1. 优先保留完整关键词种子。对于局部种子，从完整 AST 中找与公开查询词相关的属性赋值，以真实调用表达式优先，再按行号排序；选择一处赋值及上下各四行，标记为局部片段。
2. 将引用方完整符号、模块实例绑定、目标类/方法组成原子候选组。按公开查询词重合度和引用方中别名出现次数排序；预算放不下整组时拒绝，不只提供孤立绑定。
3. 重复覆盖范围跳过，部分重叠拒绝，最后按原顺序尝试保留其他原证据。总正文不超过 6,000 字符、最多 20 片段；不截断半行。Trace 保留每次候选成本和丢弃原因。

属性与别名来自语法分析，不是运行时类型推断；固定四行窗口也可能省略外围条件。节点和片段带完整文件版本，保留 CRLF。模型仍只能修改单个已展示片段中的精确文本，并通过版本、允许路径及唯一匹配校验。

初次 v1 错将带括号表达式当成调用，选偏了赋值窗口；改为 AST Call 判断后形成 v2，最终集成版本记录为 v3。三个离线目录均保留，模型试跑只使用最终实现。默认 base 不变，linked 只接入单请求诊断，暂不接入反馈流程。

## 离线对照

固定原始源码、公开查询、符号索引、五个种子和已有选择器深度 1。linked 额外分析实例别名候选并改变预算分配，因此比较的是整体上下文策略，不能将差异全部归因于某一个特性。

| 信息 | base：5,764 字符 | linked：5,998 字符 |
| --- | --- | --- |
| 两个关键 Option 环境变量取值方法 | 完整 | 完整 |
| Option.__init__ 类型选择赋值 | 未展示 | 2616–2624 局部窗口，包含 2620 行赋值 |
| convert_type | 完整 | 完整 |
| BOOL / STRING 实例绑定 | 未展示 | 展示 |
| BoolParamType | 完整 | 完整 |
| StringParamType | 未展示 | 完整 |

linked 同时提供了绑定、类型选择和字符串转换实现，但并不提供完整调用图。为容纳候选，IntRange、batch 和 Parameter.resolve_envvar_value 等原证据未被保留；它还加入 FLOAT/INT 分支及构造器原窗口。任何一项是否必要，不能由本例事后结果推广为一般结论。

## 一次真实模型试跑

与前次单请求使用相同 qwen3.5:27b、temperature 0、reasoning_effort none、输出上限 2048 Token、总预算 30000、上下文 16000、墙钟 180 秒。未增加调用或提供隐藏反馈。

| 项目 | 实测 |
| --- | --- |
| 模型请求 | 1 |
| Prompt / Completion Token | 4,039 / 455，总计 4,494 |
| 总耗时 | 21.13 秒 |
| 修改 | core.py 合法补丁，范围校验通过 |
| 公开 Controls | 3 项通过，仅该回归组 |
| 独立 Target | 失败，未超时、无执行错误 |
| 最终 | failed_verification，accepted false |

模型改用 isinstance(self.type, types.BoolParamType) 区分类型，但在非布尔分支继续用 rv.strip() 判断激活，仍把非空假值和不匹配值视为激活；没有修改 types.py。它没有完整实现公开需求。该分析不提供给模型，也不追加重试。

结论：此次预算内补齐了已诊断的引用链信息，但一次 pilot 没有修复成功，不能宣称检索收益。此前 base 的实验版本和次数不同，不将两者成绩合并或给出因果提升比例。正文预算相同也不代表 Token 相同：额外片段元数据有成本。

## 证据、测试与复现

最终离线报告 `.tmp/real-defects/linked-context-v3/comparison.json` 及两份 Trace；pilot 目录 `.tmp/real-defects/linked-context-pilot-v1/click-flag-envvar-51f73d026c/` 保存响应、补丁与独立验收。实现摘要 `f6110786cab573dbe72105792de2211950d6a0ce8ede9713035c2ac9aeb9611b`。

相关测试 31 passed；Ruff 通过。覆盖调用与括号表达式区分、候选整组预算、去重/重叠、CRLF、确定性、过期版本、未展示文本拒绝及可选协议。全量回归 558 passed、1 skipped。

```powershell
python -m pytest tests/test_linked_context.py tests/test_symbol_patch.py tests/test_symbol_links.py tests/test_real_tasks.py -q
python -m evals.compare_linked_context --admission .tmp/real-defects/crossfile-admission-v2/admission.json --output .tmp/real-defects/linked-context-reproduction
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode live --workflow symbol-patch --symbol-context-policy linked --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --evidence-dependency-depth 1 --output .tmp/real-defects/linked-context-pilot-reproduction
python -m pytest tests -q
```

需要已有准入源码与 Ollama 模型；离线输出目录须为新目录。未通过验收时模型诊断 CLI 返回 1 是正确行为。

## 下一步

冻结当前开发案例的失败与策略实现，暂不再围绕同一案例增加 Prompt 或修复轮数。优先准入更多不同类型的真实缺陷，再冻结开发/留出划分，确认 base/linked 的适用范围；如需判断模型能力，另做固定证据的第二模型诊断，不混作检索收益。linked 继续为可选实验策略，不推广默认。
