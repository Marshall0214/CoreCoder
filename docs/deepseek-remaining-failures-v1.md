# DeepSeek 43/50 基线：剩余七项失败审计

后续进展：已完成 [三项定向改进](targeted-context-v1.md)，remap-set 和 prompt-suffix 通过独立验收，range-membership 仍截断。进一步核实 remap 的 7,867 字符完整实现被旧 6,000 字符打包器整体跳过，不能只归因于检索排序。本轮未重跑五十项，原 43/50 保留。

审计日期：2026-10-09。基于已完成的 `reasoning-budget-v1-full-rerun-20261009/experiment.json`、逐项 job evidence、最终模型输出、公开检查日志和独立评分日志。本轮未发起新 API 请求，不修改评分、不使用参考补丁指导修复。

## 核心发现

最终任务状态只有两项标记 output_truncated，但逐调用审计发现五项任务发生过截断，共五次。另三项首轮返回空补丁或不完整语义补丁，第二轮截断，最终归类为 failed_public_validation。不能仅看最终状态就认为只有两项需要处理输出问题。

| 任务 | 实际输出与检查 | 提供的代码及缺口 |
| --- | --- | --- |
| click-help-eagerness | 首轮 32,768 生成 Token 全为思考，无最终补丁 | 包含 iter_params_for_processing、HelpOption.__init__ 等；仅凭截断无法判断修复逻辑是否正确 |
| click-shared-default | 首轮 32,768 生成 Token 全为思考，无最终补丁 | 包含 Parameter.__init__、Argument.__init__、Context.lookup_default；缺少 Option.get_default 等候选相关实现，因果作用尚未验证 |
| click-flag-default-map | 首轮 edits=[]；反馈轮在 28,219 生成 Token 截断 | 有 Option.__init__、Option.get_default、Context.lookup_default；缺少实际帮助文本构建实现，需定向补充后验证 |
| click-flag-envvar | 首轮 edits=[]；反馈轮在 30,907 生成 Token 截断 | 有 Option.consume_value 等，缺少 resolve_envvar_value、value_from_envvar 等环境变量处理候选实现，需验证 |
| boltons-remap-set | 两轮均 edits=[]，公开测试仍返回 (索引, 值) 组成的集合 | 五个片段全来自 dictutils.py 的 OrderedMultiDict 方法，没有 remap；目标代码未提供是直接可见的检索问题 |
| more-range-membership | 首轮修改 numeric_range.index，但公开测试的 `value in r` 仍失败；反馈轮在 30,098 生成 Token 截断 | 有 index、_get_by_index、__getitem__ 等，没有 __contains__ 和长度计算实现；仅修改 index 未修复成员判断 |
| click-prompt-suffix | 首轮补丁通过公开检查；独立 Target 在 confirm 分支失败，Controls 通过 | 提供 prompt、_build_prompt，但没有 confirm；补丁只改 prompt 内部逻辑，遗漏描述中明确要求的 confirm 行为 |

这些缺口由实际输入和测试日志确认；除明确错文件和漏改路径外，不宣称补齐上下文必然修复成功。截断也不能全部归因于缺少代码。

## 下一轮优先改动

优先处理上下文选择的覆盖缺口，而非默认扩大思考预算或重跑相同提示：

1. 对缺陷描述中明确提到的函数、类和公开测试中的直接调用，先做精确符号解析，在预算内优先纳入完整实现，再以词法相关性填充其余空间。例如 remap 不应被常见词匹配的 OrderedMultiDict 方法挤掉。
2. 遇到公开测试失败时，结合失败调用补充当前未覆盖的实现。Python 运算需考虑协议方法，例如成员判断对应 __contains__；相关辅助方法可以按静态引用展开，并设置数量和字符上限。
3. 描述要求多个入口时，建立覆盖记录，例如 prompt 与 confirm 都需要上下文；不能将其中一个分支的公开通过视为整个需求已解决。独立评分仍不反馈给模型，不能用已见私有断言编写特定提示或公开测试。

先用原始开发集验证上下文覆盖与修复净收益，再完整跑五十项。保留原 DeepSeek 模型、思考配置、两次修复机会和预算，以减少混杂；最终比较新增成功、原成功丢失、Token 和耗时。未验证前不修改 43/50 成绩。

此前模型主动选择源码的 Qwen 开发集实验没有净收益；本次候选方向针对确定可见的符号遗漏，以精确解析和受限展开为主，不能把已有负结果忽略后重跑同一种模型选码方法。
