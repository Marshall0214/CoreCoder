# 独立公开场景：避免首个异常遮挡后续问题

上一轮运行证据让 locate 的部分公开断言通过，但随后 replace 仍异常。初始公开测试把多个
场景串在同一方法中，locate 一旦报错，后面的 replace 缺陷场景便不会执行。

## 本轮实现

从认证公开测试的 AST 派生诊断副本，不更改原测试、参考源码或独立评分：

- Reproduce 原五条断言变为四个场景：普通 locate、短输入 locate 和最后调用参数、
  replace 不匹配保留数据、replace 匹配替换。短输入调用与依赖它的 `seen[-1]` 断言保留在一起。
- Preserve 原两条断言各自独立。总计六个诊断方法，每个重新执行原公开初始化代码。
- 原断言表达式和期望值都直接从公开 AST 复制，记录原断言行号；没有新增答案或降低期望。
- 原认证检查和最终验收仍执行原来的串联测试；派生场景仅用于采集诊断数据。
- 普通执行与插桩执行逐场景核对测试名及成败，源文件和原/派生测试都有不可变性检查。
- 保留所有场景的成败，只展示失败场景的实际操作输入和 predicate 调用，省略通过场景的
  操作明细。运行证据上限仍 5000 字符；模型预算、原源码上下文和失败回滚保持不变。

拆分器只支持本任务当前公开检查结构；结构变化会拒绝，不声称支持任意 unittest 文件。
诊断场景重置状态，因此诊断结果不能代替原串联检查或独立验收。

代码：[场景派生和反馈](experiments/independent_predicate_feedback_v1.py)、
[对照执行器](experiments/independent_predicate_compare_v1.py)、
[测试](../tests/test_independent_predicate.py)。复用上一轮的有界 predicate 采集器。

## 对照设计

两组分别是上一轮单测试运行证据 `predicate-runtime` 与独立场景运行证据 `independent-runtime`，
用于判断补齐第二处错误是否比上一轮采集方式有效。不是无运行证据与有运行证据的重复比较。

两组复用同一历史首轮回答和原失败反馈，每组各产生一次新的修正，核对首轮请求、源码哈希、
第二轮 system prompt 相同；原 user payload 除运行证据字段外应完全相同。
模型仍 qwen3.5:27b、非思考、temperature=0、top_p=1，单次输出 2048 Token，累计预算
15000 Token、上下文 16000、每项 600 秒。历史首轮 3059 Token 仍计入每组预算。
本轮新增模型调用共两次；派生场景、普通执行及采集不调用模型。

只使用公开测试和当前首轮候选；独立 Target/Controls 在 worker 退出后评分，未提供给模型。
单个已知开发失败、固定顺序、各组单次；不能据此声称总体成功率或泛化提升。

## 离线检查与复现

相关测试 15 项通过，Ruff 通过。实际历史候选的离线采集得到六个场景：四个通过，
两个分别暴露 locate/replace 的 TypeError；整理后的运行证据 2629 字符。
首个离线调用传入相对工作路径，子进程无法导入包，返回无可用证据且模型调用为零；
使用绝对路径复查成功，并为新入口加入路径归一化，保留两次离线日志。

激活 corecoder 后执行，使用尚不存在的输出目录，产物留在 D 盘：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m pytest tests/test_independent_predicate.py tests/test_predicate_runtime.py -q
python -B -m docs.experiments.independent_predicate_compare_v1 --output .tmp/real-defects/independent-predicate-v1-new
```

原始记录：`.tmp/real-defects/independent-predicate-v1-pilot/experiment.json`，
只有 `complete=true` 才代表两组及验收全部完成。

## 完整结果

| 方案 | 整项通过 | 第二轮输出 Token | 新推理 Token | 含历史首轮的预算 Token |
| --- | --- | --- | --- | --- |
| 单测试运行证据 | 0/1 | 248 | 4286 | 7345 |
| 独立场景运行证据 | 0/1 | 254 | 4519 | 7578 |

两组首轮请求及候选哈希相同、第二轮 system prompt 相同；移除运行证据字段后 user payload
完全相同，冻结输入检查通过。本轮两次新模型请求合计 8805 Token；源码、验收及重试预算未变。

独立场景证据实际加入模型请求，同时显示 locate 短输入与 replace 尾部的 TypeError。模型
这次修改了两个函数，但采用了“过滤含填充值的整个窗口”，而不是保留窗口中的有效元素。
原串联复现在 locate 的 `seen[-1] == (4,)` 断言失败，实际仍为 `(3, 4)`；正常行为公开检查通过。
两组补丁均完整可应用，无输出截断；两组整项均拒绝并回滚，不算修复成功。

为避免验收中的早停再次遮挡后续问题，在推理结束后，对两个已保存的第二轮候选额外执行
同一套公开派生场景，未增加模型调用，也未改变验收。这六项诊断中：单测试证据候选剩一项
失败（replace）；独立场景候选剩两项失败（短 locate、replace 保留尾部）。后一候选丢弃
尾部窗口，因此诊断中的短输入不再调用 predicate，replace 不匹配时也丢失末尾元素。
这组逐场景结果不能替代原验收成绩，但说明新补丁没有解决两个场景的完整语义。

**决定：诊断原型保留，修复策略不采用、不扩跑。**错误证据覆盖从一处增加到两处，
仍没有整项成功率提升；不能把诊断覆盖提升写成修复效果提升，也不将模型失败继续归因为
完全缺少 replace 运行信息。后续重点应是解释“去掉填充值”和“丢弃整个窗口”的行为差异，
而非继续拆更多同类场景或增加重试。

全量 **1338 passed、4 skipped**，Ruff 与冻结输入检查通过。默认 Agent/API 和历史完整
五十项成绩 32/50 保持不变。[逐项结果](independent-predicate-v1.json)包含实际运行证据、
正式配对、第二轮候选的离线公开场景检查及消耗。
