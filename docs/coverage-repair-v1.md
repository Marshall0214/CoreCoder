# 修复目标覆盖与补丁约束

日期：2026-10-10。基于完整 50 项重测中五项退步的审计，新增可选实验版本，未修改旧冻结实验模块及默认 Agent/API。

## 已实现的改动

1. public_api_context_v2 修复完整名称与末级名称混用，保留描述明确指定的类方法。
2. coverage_context 在最终打包前预留明确修复主体，以及相等/hash、资源退出、成员/index 等关联协议。 required 超过原五片段/六千字符预算时明确阻止，不静默丢掉目标；保留 required、missing_required、discarded 诊断。
3. constrained_patch_v1 拒绝空 edits、空锚点、相同 old/new、最终未改变源码的补丁。仍要求锚点来自已提供原文、唯一匹配、允许文件范围、当前 hash 和语法正确。全部检查先在 staging 完成，再复制到工作区。
4. 首轮结构化补丁无效时，允许执行原公开检查并在第二次请求提供补丁约束错误与公开失败，最多两次调用不变。截断/预算停止不追加机会；修正无效回滚，独立评分不进入提示。

约束保证的是候选格式、作用范围和实际变更，不保证语义正确，最终仍由公开、冻结和独立检查验收。没有要求必须修改所有描述中出现的函数，以免排除合理的替代修复位置。

## 离线验收

五项退步的关键方法已进入上下文：

| 任务 | 保留的关键实现 |
| --- | --- |
| usage-empty | HelpFormatter.write_usage |
| resource-exception | Context.with_resource、Context.__exit__ |
| invoke-missing | Context.invoke |
| reverse-empty-range | numeric_range.__reversed__ |
| range-equality | numeric_range.__eq__、numeric_range.__hash__ |

全部 50 项原始源码通过上下文预检，证据见 coverage-repair-v1-preflight.json；这是离线覆盖检查，不是 50 项模型修复成绩。

预检中发现普通词 option/output 可能被误当强制主体，因此保留已启动 v1 实验不变，另立 coverage_context_v2 收紧规则：限定完整符号、代码形式标识符或明确句首函数主体。v2 全部 50 项也通过预检；当前五项初始证据与 v1 完全相同，见 coverage-repair-v2-preflight.json。新入口 coverage_repair_v2 已提供，但没有再调用模型重跑 v2。

## 真实验证协议

仅运行预先选定的五项退步，每项从原始冻结源码开始，全部重新生成。原 DeepSeek Flash 高思考、最多两次调用、60,000 累计 Token、32,768 单次生成（含思考）、65,536 上下文、480 秒请求和 1,200 秒 Worker 超时保持不变。公开、冻结和独立评分不改动；文件、缓存及输出均位于 D 盘。

实际入口：`python -B -m docs.experiments.coverage_repair_v1 --scope pilot --output .tmp/real-defects/coverage-repair-v1-20261010`

v1 运行过程中只调整了独立的 v2 实现和测试，没有修改 v1 记录的源码 hash。不同版本须分别记录；本轮同时改变了检索覆盖及补丁约束，不能独立量化每项改动的因果贡献。

完整历史和最近完整结果仍分别为 43/50，不用五项定向结果拼接新的完整通过率。新版本用于后续完整测试前仍需检查成功任务的回归。

## 最终结果

相关测试 68 passed，全部 50 项离线覆盖预检通过。真实模型五项全部完成并通过审计：最近完整实验中这五项 0/5，本轮恢复为 5/5；更早完整历史中这五项曾为 5/5，因此这里是恢复退步，不是五项首次解决。

| 任务 | 独立验收 | 调用 | Token |
| --- | --- | ---: | ---: |
| click-usage-empty | Target/Controls 通过 | 1 | 12,426 |
| click-resource-exception | Target/Controls 通过 | 1 | 19,938 |
| click-invoke-missing | Target/Controls 通过 | 1 | 13,874 |
| more-reverse-empty-range | Target/Controls 通过 | 1 | 2,196 |
| more-range-equality | Target/Controls 通过 | 1 | 13,503 |

共五次首轮调用、61,937 Token，Worker 累计约 214 秒，未发生截断或反馈重试。相比最近完整实验中这五项的 172,904 Token 减少 64.18%；更早成功历史中它们消耗 55,923 Token，不能描述为相对所有历史都降低成本。

已核对进程、原预算、输入 hash、最终源码、允许修改范围、非空且确有变更的补丁、公开/冻结和独立评分。v2 在这五项原始源码上选出的证据与实际请求中逐字段相同，已记录；这不代替 v2 的完整 50 项模型回归测试。

本轮同时修复目标覆盖和增加补丁约束，不能证明单靠某一条提示或约束就提升成功率。模型未再返回空补丁；两项此前首轮截断也恢复为完整补丁，支持先修正上下文覆盖的决策，但不保证其他截断项都能同样解决。

结构化结果见 [结果数据](coverage-repair-v1-results.json)。完整基线和最近完整实验仍保持 43/50，不宣称 48/50。下一步应以 v2 在最近完整通过的任务上做回归确认，最终通过完整 50 项测试再报告全量收益。
