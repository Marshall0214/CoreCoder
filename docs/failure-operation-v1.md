# 按公开失败操作补齐上下文：共享首轮三项对照

## 结论（2026-10-09）

**当前流程 0/3，操作检索 1/3。新增修复 click-flag-default-map，其他两项仍失败。**
这是三个已知开发失败的局部对照，不是完整任务池的新成功率；完整冻结成绩仍为 32/50。
默认 Agent/API 未变，不把局部新增修复直接换算成 33/50。

| 任务 | 当前流程 | 操作检索 | 实际变化 |
| --- | --- | --- | --- |
| click-flag-default-map | 失败 | 通过 | 补齐帮助渲染调用者，模型用有效默认值选择展示 flag，独立 Target/Controls 均通过 |
| more-range-membership | 失败 | 失败 | 补齐 __contains__ 并保留已修改 index；模型改到目标路径，但浮点余数语义仍错 |
| click-prompt-suffix | 失败 | 失败 | 无新增检索候选，第二轮实际请求和回答均完全相同 |

## 实现内容

新增 [操作检索器](experiments/failure_operation_context_v1.py) 与
[共享首轮对照入口](experiments/failure_operation_compare_v1.py)。没有修改冻结检索模块。

- 从公开失败日志的 test_admission.py 帧定位失败测试函数和操作表达式，不扫描成功测试来增加上下文。
- 用 AST 中局部变量的构造调用与公开 import 别名解析所属类；同名类、重复绑定或外部导入无法可靠解析时不猜测。
- 将 assertIn/assertNotIn/in 映射到 __contains__，reversed/len/bool 映射到对应魔术方法。
  复用已有函数索引与证据校验；成员判断映射此前已有原型，本轮新增限定失败表达式和严格配对验证。
- 从失败测试实际使用的长选项提取词，例如 --help → help；寻找名称包含该词且静态引用已检索函数的调用者。
  本例通过 get_help_record 引用 get_default 自动发现帮助渲染路径，不硬编码任务 ID 或目标函数名。
- 新操作函数优先，然后保留首轮已修改的种子函数，再补原有片段；整体仍最多五个完整函数、6000 字符。
  超大函数沿用现有打包器的拒绝/预算记录，不截断源码或额外增加预算。
- 没有可靠新增候选时返回原刷新片段，避免仅因新策略名称改变模型上下文。

反向调用者规则是有界静态启发式，并不等于完整调用图或动态根因定位。
它无法保证处理工厂返回值、动态派发、复杂对象流或任意 CLI 框架。
优先保留已修改种子受原有预算约束，不承诺超大函数必定可容纳。

## 离线验收与输入一致性

离线在冻结的首轮候选上运行，检索目标不读取参考补丁、修复后源码或独立评分代码。
新片段自动找到 Option.get_help_record 与 numeric_range.__contains__。
两项分别装填 5227、2580 字符；prompt 的 5746 字符片段保持相同。

三对初始消息与初始回答完全相同，初始候选快照哈希相同；不是分别采样首轮后再比较。
初始请求通过已验证的历史响应重放，历史真实 Token 用量计入两组共享预算。
两组只发出第二轮真实请求；三对系统提示、任务描述、允许文件和公开反馈相同，只有片段及其引用元数据可变。
公共验证重新执行后，与历史首轮的通过状态、运行测试数、失败/错误数一致，随后复用相同的历史公开反馈文本。

prompt 对照无新增片段，两个第二轮 provider-call-02/request.json 和 response.txt 均字节相同。
因此没有把“换策略名称”或重写反馈提示当作额外干预。
所有真实请求均返回 stop，无思考输出、截断、预算停止或缺失 worker。
输入对照记录：D 盘 `.tmp/real-defects/failure-operation-v1-pilot/paired-input-audit.json`。

## 为什么新增一项、另一项仍失败

default-map 原先两轮仅修改 get_default，但 get_help_record 仍通过 self.default 选择 fast/slow。
补齐调用者后，模型提交唯一原文替换，将该判断改为 default_value。
候选的当前/冻结公开 Reproduce 与 Preserve，以及独立 Target 与 Controls 全部通过。
这支持“该任务的上下文覆盖缺口会影响修复”的局部解释，不证明所有检索缺口都能靠本规则解决。

range-membership 确实修改了 __contains__，但用 divmod 的余数接近 0 判断成员。
例如 `divmod(0.5, 0.1)` 为 `(4.0, 0.09999999999999998)`，余数接近步长而非 0；
公开测试因此仍报告 0.5 不在范围中。Preserve 通过、整项失败，候选回滚。
这次没有继续追加第三次修正，也没有把断言推进当作修复成功。

prompt 已展示内部 `f(" ")`，片段不变、回答也不变，仍未修好。
它说明上下文补齐能解决部分覆盖问题，不能替代正确的执行顺序与语义推理。

## 成本与验收

固定 Qwen qwen3.5:27b、冻结 Ollama 身份、非思考、temperature=0、top_p=1，
每任务两次调用（含重放）、15,000 Token、单次输出 2048、600 秒 worker。
候选原文唯一匹配、编译、双重公开检查、失败回滚、worker 外独立评分均保持原协议。
两组交替顺序，不重置首轮预算，不增加诊断执行或模型重试。

| 指标 | 当前流程 | 操作检索 |
| --- | ---: | ---: |
| 独立修复通过 | 0/3 | 1/3 |
| 新模型请求 | 3 | 3 |
| 新请求 Token | 9431 | 8954 |
| 计入重放后的任务预算 Token 合计 | 17283 | 16806 |
| 回滚后独立 Controls | 3/3 | 3/3 |

共 6 次新请求、18,385 Token；操作组新请求 Token 少约 5.1%，这是局部观察，不作为稳定节省比例。
各组表中的 Token 是三任务合计，15,000 上限按每个任务执行，不是整组上限。
最终 Controls 含失败任务回滚后的检查；新增成功任务的候选自身也通过了正常行为验证。

相关测试 **36 passed**；Windows 全量 **1411 passed、4 skipped（162.96 秒）**，新增文件 Ruff 通过。
未调用 DeepSeek、未重跑 Docker/HTTP，模型记录与临时文件均保存在 D 盘。

## 下一步与限制

这次新增修复足以保留原型，但还不能替换默认流程。下一轮先增加历史成功任务的回归对照，
并扩展开发失败覆盖，确定调用者补齐是否会挤掉关键片段。随后再考虑完整开发集复核。
不围绕 range 单例追加提示，也不把锚点协议、输出上限改动与检索收益混在一起。
历史留出失败已在审计中被查看，未来泛化评测需要新的未查看任务。

机器摘要：[failure-operation-v1.json](failure-operation-v1.json)。原始记录位于 D 盘
`.tmp/real-defects/failure-operation-v1-pilot`。复跑必须使用全新输出目录。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m pytest tests/test_failure_operation_context.py tests/test_frozen_feedback.py tests/test_predicate_runtime.py -q --basetemp .tmp/failure-operation-tests-rerun
python -B -m docs.experiments.failure_operation_compare_v1 --offline-only --output .tmp/real-defects/failure-operation-offline-rerun
python -B -m docs.experiments.failure_operation_compare_v1 --output .tmp/real-defects/failure-operation-paired-rerun
```
