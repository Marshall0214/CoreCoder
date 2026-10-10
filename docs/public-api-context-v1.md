# 两项 Click flag 失败的公开 API 上下文改进

## 范围与条件

仅运行 click-flag-default-map、click-flag-envvar；原完整 DeepSeek 高思考实验两项均失败。不重跑完整任务池，不修改公开/冻结/独立评分，原 43/50 保留。采用已知失败定向调试，不能用于盲测结论。

保持同一 DeepSeek Flash 高思考配置、最多两次模型调用、60,000 累计 Token、32,768 单次输出、65,536 上下文预算、480 秒请求超时及 1,200 秒 Worker 超时。首次截断仍停止，公开反馈最多一次，失败回滚。未叠加之前无收益的首次公开复现提示策略。

## 改动

只解析公开测试的 AST，从其调用的 API 工厂函数静态寻找相关实现类。结合描述、公开调用关键字和方法名选择类方法，扩展直接调用、直接父类 super 方法，以及有明确参数类型标注的接收对象调用。剩余空间才使用关键词检索补充。

不执行测试代码来构建检索索引，不调用额外模型，不读取参考补丁或独立评分内容。自然语言中的 command-line、argument 不再被直接当作同名工厂函数强行优先。静态解析仅支持明确可解析的绑定、直接基类和简单类型标注；动态工厂、复杂继承和未标注接收对象可能仍无法覆盖。

长文档仍采用连续正文片段及签名元数据，不拼接不相邻的可编辑源码。上下文维持五个片段、六千字符，反馈时重新读取候选版本与文件 hash。

离线覆盖检查：

- default-map：Option.get_default、Option.get_help_record、Parameter.get_default、Context.lookup_default、Command.format_help，共 5,503 源码字符。
- envvar：Option.resolve_envvar_value、Option.value_from_envvar、Parameter.resolve_envvar_value、Parameter.consume_value 及 batch，共 2,209 源码字符。

相关测试 32 passed，包括公开工厂跨文件导入、父类调用、带类型标注的接收对象、未解析调用不猜测类型、源码刷新和失败回滚、原预算及运行范围限制。

## 运行

入口：`python -B -m docs.experiments.public_api_repair_v1 --scope pilot --output .tmp/real-defects/public-api-context-v1-20261009`

## 最终结果（2026-10-09）

2/2 运行完成，独立验收 1/2，通过正常行为 Controls 2/2。每项一次模型调用，共 34,022 Token，Worker 累计约 124 秒；没有输出截断。

| 任务 | 独立结果 | Token | Worker 秒数 |
| --- | --- | ---: | ---: |
| click-flag-default-map | Target/Controls 均通过 | 5,021 | 12.422 |
| click-flag-envvar | 公开/冻结检查通过，独立 Target 未通过，Controls 通过；计失败 | 29,001 | 109.860 |

默认值展示补丁使用实际解析出的 default_value 选择帮助文本中的选项，而非读取声明中的 self.default。对应补丁、公开检查和独立验收可复核。

环境变量补丁只排除了已枚举的假值，仍会把其他非空输入当成激活，未完整落实描述要求的“真值或精确 flag_value 才激活”。独立评分诊断仅用于事后审计，没有反馈给本轮模型。本轮保留其失败补丁作为隔离工作区中的审计证据，不作为已验收补丁交付；公开验收通过时旧工作流会保留候选，不能把 Worker completed 当成独立 accepted。

已核对进程正常退出、用量不超原预算、调用次数、最终源码 hash 与记录一致。汇总见 `public-api-context-v1-results.json`。完整证据位于输出目录的 experiment.json、context-selection.json、实际请求/补丁与验证日志。本轮不复跑旧策略，历史结果比较存在模型随机性与服务变化，不能独立证明算法因果收益。

原完整 43/50 不改写。本轮新增一项可复核修复；此前 remap-set、prompt-suffix 两项定向成功仍分别保留，不拼接宣称新的全量通过率。剩余历史失败为 help-eagerness、shared-default、range-membership、flag-envvar，仍需分别处理。
