# 依赖预留预算：离线对照 v1

## 实现与边界

新增可选 `dependency-reserve` 装填策略。存在依赖扩展时，检索种子的正文最多使用总预算的一半；静态依赖可使用剩余全部预算。种子装不下时沿用已有命中窗口回退，标记为局部符号；依赖只从实际选中的代码范围追踪。深度为 0 时不预留。

未使用的依赖预算不回填种子，因而可能浪费预算。本次固定 50% 分配，不按目标路径或已知修复调整比例。原 `seed-first` 为默认；两组使用同一源码、符号索引、公开标识符查询、排名、6,000 字符预算、5 个种子及深度 1。窗口大小、依赖发现方式与补丁防护保持一致。

Trace 新增种子预算、种子/依赖实际字符数和丢弃项可用预算。已有源码版本、路径范围、重叠去重和只修改已展示文本的校验继续适用。只读 AST 分析不执行模块；本次模型调用为 0。

## 真实开发案例结果

| 策略 | 总正文 | 种子正文 | 依赖正文 | 观察 |
| --- | ---: | ---: | ---: | --- |
| seed-first | 5,984 | 5,833 | 151 | 完整初始化函数占用大量预算；BoolParamType 已发现但装不下 |
| dependency-reserve | 2,790 | 2,214 | 576 | 初始化函数只展示 2533–2561 行；BoolParamType 引用不在窗口中，未被发现 |

预留组完整保留 Option.resolve_envvar_value、Option.value_from_envvar，另外选中 Parameter.value_from_envvar、batch 和 Parameter.resolve_envvar_value。Option.__init__ 为局部片段，不得当作完整函数；Option.get_help_extra、Context、ParamType 被预算拒绝。

**结论：固定预留可以避免种子耗尽预算，但该真实案例仍缺少布尔转换实现。** 其原因从“依赖已发现但被预算丢弃”变成“种子被截短，依赖引用没有进入发现范围”。2790 字符不是 Token 实测，正文更短不代表上下文更好；未运行模型，不报告修复收益。

新增人工测试验证了预留策略可以在竞争预算下保留完整依赖，也明确覆盖引用位于局部窗口之外时不被发现的限制。真实结果是已知开发案例上的事后诊断，不是留出评测或正式 Recall；仅预留预算不足以解决整个问题。

## 证据与复现

报告 `.tmp/real-defects/symbol-packing-v1/comparison.json`，以及同目录两份策略 Trace。实现摘要 `4e5492ee7037dd07779b78fe11e907e0461e24adf0770ddcca905880d6f79315`，源码摘要与索引对照一致；两组均校验上游源码未改变。

```powershell
python -m pytest tests/test_symbol_packing.py -q
python -m evals.compare_symbol_packing --admission .tmp/real-defects/crossfile-admission-v2/admission.json --output .tmp/real-defects/symbol-packing-reproduction
python -m pytest tests -q
```

需已有准入报告和源码，输出目录须为新目录。4 项新增测试通过；全量回归 523 passed、1 skipped；本次相关文件 Ruff 通过。原索引对照报告不覆盖。

## 下一步

将依赖分析范围与最终展示范围分离：在允许的、带版本校验的完整种子符号上发现引用，再独立分配展示预算，并在 Trace 中明确引用来自已展示还是未展示范围。引用发现不赋予未展示文本的修改权限。作为独立策略对照，不修改本次失败结果；上下文充分性仍需检查，之后才进入结构化补丁工作流。
