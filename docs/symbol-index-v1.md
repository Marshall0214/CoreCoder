# Python 索引与公开查询策略：离线对照 v1

## 做了什么

新增 Python 专用 BM25 索引和离线对照入口。比较固定 40 行分块与 AST 符号分块，再分别采用原始描述、通用别名扩展、公开标识符查询。目的是判断修复所需源码能否进入有限上下文，本次没有调用模型、生成补丁或计算修复成功率。

两种索引使用相同 Python 文件语料与 BM25 评分方法，Markdown 不参与评分。符号索引按函数、方法以及类头部建立代码块，模块常量等剩余行仍可检索；无法解析的源码退回行窗口。原有默认选择方式不变，新策略仅用于可选评测。

查询策略：

- `plain`：公开问题描述原文。
- `aliases`：原文追加通用映射，例如 environment variable → envvar、boolean → bool。
- `identifiers`：使用这些映射及公开描述已有的 snake_case 标识符；没有可提取词时退回原文。本案例为 `envvar bool flag_value`。

选择器不接收官方修复文件列表、修复后源码或隐藏验收内容。索引只读取源码并解析 AST，不导入或执行仓库模块。报告保存输入源码摘要、实现摘要、完整片段及各组 Trace，并检查源码未被改动。

## 实际结果

案例为已准入的 `click-flag-envvar` 开发案例。六组均固定正文预算 6,000 字符、最多 5 个种子、静态依赖深度 1，允许范围为整个 `src/click`。

| 索引 / 查询 | 正文字符 | 结果观察 |
| --- | ---: | --- |
| 行 / 原文 | 5,259 | 返回 Option 文档片段、wrap_text 等，缺少环境变量取值实现 |
| 行 / 别名追加 | 5,063 | 仍有 wrap_text；未解决关键实现缺失 |
| 符号 / 原文 | 5,702 | 返回初始化片段等，仍未解决取值实现缺失 |
| 符号 / 别名追加 | 4,857 | 返回 split_envvar_value，但未覆盖关键取值方法 |
| 行 / 标识符 | 5,409 | 完整返回 Option.resolve_envvar_value 和 Option.__init__ |
| 符号 / 标识符 | 5,984 | 另完整返回 Option.value_from_envvar，以及静态依赖 batch |

标识符查询改善了本案例的取值代码检索；仅追加别名不足。符号加标识符仍有缺口：静态追踪发现 BoolParamType，但完整初始化函数占用了大量预算，布尔转换代码因预算不足被丢弃。行加标识符组也丢弃了该依赖。

上述方法与依赖的相关性是开发者事后结合已知缺陷作出的解释，不是预先冻结的相关性标签。本案例已用于多轮开发，不能作为留出集，也不能据此报告正式 Recall 或一般化收益。符号策略在超大符号的窗口回退上也使用了围绕命中行的窗口，而行策略保留原始分块窗口，因此对照反映两种上下文策略，不能将差异全部归因于 BM25 分块。

## 验证与复现

新增测试覆盖公开查询提取、相同语料、Markdown 隔离、类头部去重、模块常量、解析失败，以及方法和跨文件依赖提取不执行源码。相关测试 13 passed；完整回归 519 passed、1 skipped；本次相关文件 Ruff 通过。

最终报告：`.tmp/real-defects/symbol-index-v3/comparison.json`，对应六份同目录 Trace；初次四组 v1 与六组 v2 保留，不覆盖。实现摘要为 `6784a86335d39afc4c4749285841949be4670e21c36b6e5a9e40c2f31298c621`；输入源码摘要为 `9fcc22855ce366a1b1164229ea761a75cde4e9465e21d293a284bfb07003226e`。

```powershell
python -m pytest tests/test_symbol_index.py tests/test_symbol_context.py -q
python -m evals.compare_symbol_index --admission .tmp/real-defects/crossfile-admission-v2/admission.json --output .tmp/real-defects/symbol-index-reproduction
python -m pytest tests -q
```

准入报告和对应源码须已存在；输出须使用新目录。退出 0 表示离线对照完成，不表示上下文充分或缺陷已修复。

## 下一步

固定查询和索引，独立比较现有种子优先装填与依赖预留预算策略。限制大种子占用、明确标记局部片段，检查是否能在同一预算下容纳依赖及关键实现；不按已知目标路径强制选取，也不为该案例微调预算使其刚好通过。确认上下文后再接入有限结构化补丁工作流，并单独报告协议变化。
