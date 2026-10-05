# 类型选择与实例别名链：离线诊断 v1

## 本次完成

新增 `symbol_links.py` 与 `symbol_link_audit.py`。以当前实际选中的符号为分析起点，记录完整种子中的属性赋值，并将模块顶层唯一的本地类构造赋值链接到类/方法定义，例如 `TOKEN = TextType()` → `TOKEN.convert` → `TextType.convert`。

只接受单目标、模块顶层、可识别的同文件类构造；重复赋值、条件赋值、未知工厂和链式赋值不建立该链接。解析 AST，不导入或执行源码，不推断 self.type 的运行时类型。构造器、装饰器、元类或运行时修改都可能改变真实对象，因此链接只是语法证据，不是可靠的运行时调用图。

分析范围为准入 before 的全部允许 Python 源文件，起点由原公开查询和既有选择器产生，没有加入官方修复路径、隐藏测试或人工指定目标符号。默认分析深度 1、最多 100 节点/300 边，达到上限明确记录 limited。节点带文件版本、范围、字符数和是否完整展示；实例绑定记录行号与展示状态。

**本次没有改变模型证据、检索默认值或调用模型。** 图中发现的节点并未自动装填，也不赋予修改未展示文本的权限。该分析为后续预算分配提供候选信息。

## 真实案例发现

当前选择器仍返回原 5,764 字符证据。离线图有 19 节点、24 边，未触及上限。

| 信息 | 准入源码范围 | 当前是否展示 |
| --- | --- | --- |
| Option.__init__ 的 self.type = types.convert_type(None, flag_value) | core.py 2620 | 否 |
| convert_type 类型工厂 | types.py 1068–1125 | 是 |
| STRING = StringParamType() | types.py 1143 | 否 |
| StringParamType 类及字符串转换实现 | types.py 207–230 | 否 |

这确认了上一轮失败分析提出的信息缺口：模型看到了类型工厂，却没有看到 flag_value 如何决定实例类型，也没有看到 STRING 对应的转换类。StringParamType.convert 返回字符串，而非判断是否激活开关的布尔结果。原失败补丁却依赖该返回值的真假判断激活。

这是事后源码解释，不证明缺失上下文是失败的唯一原因，也不证明补齐后模型一定修复成功。图还产生其他类型分支候选，不能全部算作相关代码或直接全部加入上下文。

预算限制仍存在：当前证据剩余 236 字符，StringParamType 完整类需要 788 字符，另需绑定与赋值上下文。直接追加会超出 6,000 字符，下一步必须比较预算内的替换/重新分配，而不是扩大预算后宣称收益。

## 证据与验证

报告 `.tmp/real-defects/symbol-links-v1/audit.json` 与同目录 trace.jsonl，保留完整原证据、图、赋值范围、版本和限额。实现摘要 `1017b155de1a4e37a1246d8814d98344d8f43bc55a54faca425c3c8f275450ee`；模型调用为 0，上游源码未改变。

新增 8 项测试通过，覆盖别名/方法、重复和条件绑定拒绝、不执行源码、缺失赋值、图上限、过期版本及越界路径。相关文件 Ruff 通过；全量回归 554 passed、1 skipped。

```powershell
python -m pytest tests/test_symbol_links.py -q
python -m evals.symbol_link_audit --admission .tmp/real-defects/crossfile-admission-v2/admission.json --output .tmp/real-defects/symbol-links-reproduction
python -m pytest tests -q
```

需要已有准入报告和对应源码；输出目录须为新目录。退出 0 表示审计完成，不代表相关实现已经提供给模型或缺陷已修复。

## 下一步

将实例别名候选和与类型选择相关的赋值窗口接入可选上下文策略，在同一 6,000 字符预算下重新分配。候选来源只允许当前检索与 AST 引用链，不按已知修复路径强制选取；保留来源和片段完整性。先做离线证据对照，确认绑定、赋值和转换实现同时进入上下文后，才运行模型 pilot；与当前策略独立报告。
