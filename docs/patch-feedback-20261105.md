# 公开反馈修正：20 轮入口（2026-11-05）

后续更新：[已接通 Harness² 并完成一项真实验收](harness2-feedback-20261105.md)。下面“尚未执行”的状态描述保留为独立入口首次交付记录，以该后续文档的实际结果为准。

在 [独立补丁验证器](patch-validator-20261105.md)之后，增加 `repairflow.feedback_repair`。默认**最多 20 轮反馈修正**，仅针对已生成的候选补丁继续修复，不重新执行此前的代码探索或 Harness² 策略搜索。

## 轮次与停止

初始验证记作第 0 轮，不调用模型。候选未通过时，发送当前源码、公开静态/测试错误，模型返回唯一锚点替换请求；执行器校验并应用到新的工作副本，再运行公开验证。每次修正请求算一轮，格式错误、无变化和失败请求也保留记录，不偷偷重试。

- 默认 20 轮，参数 `--max-feedback-rounds 20`；与旧探索器的 20 次工具动作、6 次编辑限制分开，本入口不套用后两项限制。
- 不因重复同一失败、重复补丁或连续格式错误提前终止；达到 20 轮才按轮次停止。
- 公开检查通过即进入 `ready_for_review`，不自动提交，也不表示独立验收成功。
- 保留原来的总时限默认 1,200 秒、单次本地请求最多 480 秒、取消和沙箱边界；基础设施错误不能当作补丁错误无限重试。20 轮是最多可尝试次数，不保证在时限内跑满。
- 本地 Qwen3.5:27b、`think=false`；没有 Token 预算预检查或应用层输出 Token 截断，仍受模型实际上下文容量与现有响应字节保护约束。

因此可以看见第 1、2、…、20 轮各自发生了什么，无需为了多试一轮不断修改程序。

## 记录与隔离

`protocol.json` 固定公开任务、源码/检查哈希、指导、代码版本与轮次规则。`rounds/NNN/` 保存请求、响应、单轮 Token、补丁、公开验证和耗时；总 `report.json` 区分修正请求数、成功应用补丁数和真实模型调用数。未知用量记为 null，不伪造为零。

只反馈 `Reproduce/Preserve` 的白名单字段、测试错误尾部及静态诊断；日志尾部最多 12,000 字符，并记录省略字符数。接口不接收独立测试位置、Target/Controls 或参考补丁。独立评分须在本入口结束后另行执行，不能用其结果挑选中间补丁。

每轮失败候选留在隔离的工作副本供继续修正，所有历史补丁保留；不会覆盖用户仓库或原始 agg1。取消文件为输出目录中的 `CANCEL`，在请求前及请求返回后检查；不声称能立即中断正在等待的 HTTP 请求。可选 Langfuse 沿用本地模型调用及 Token 观测；未配置时仍保存完整本地记录。

## 使用

准备两份源码导出、可信公开检查目录和仅含 `instance_id/repo/base_commit/problem_statement` 的公开任务 JSON。所有路径在项目工作区，输出目录必须全新：

```powershell
$env:PYTHONPATH = 'D:\project_other\CoreCoder'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHON_DOTENV_DISABLED = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m repairflow.feedback_repair `
  --baseline .tmp/harness2-autonomous-20261104/input `
  --candidate .tmp/harness2-autonomous-20261104/executions/issue-cc-agg1/toolz-join-unmatched/agg1/agent/workspace `
  --task .tmp/harness2-autonomous-20261104/executions/issue-cc-agg1/toolz-join-unmatched/agg1/public.json `
  --allowed toolz/itertoolz.py `
  --public-checks repairflow/validation_checks/toolz_join --package toolz `
  --max-feedback-rounds 20 --output .tmp/patch-feedback-toolz-20261105
```

这条命令会实际调用本地模型。本轮交付先完成入口和自动化测试，**尚未执行以上真实模型实验或新的独立评分**。若比较已有合成指导，需通过 `--guidance` 显式传入冻结的指导文本，并记录其来源；上述不带此参数的例子不等于沿用原 Harness² 合成指导。当前入口提供完整可写文件作为新鲜读证据，因此与旧探索/上下文链路也不完全相同；后续单项结果应表述为保存候选的反馈修正机制实验，不能包装成严格单变量的整体准确率提升。

## 已验证的边界

相关自动化测试 **23 passed**（反馈循环 11 项、验证器 12 项），两份新文件 Ruff 通过。测试包括连续 20 次无效补丁仍记录满 20 轮、第 20 轮成功可被接纳、提前成功停止、新鲜源码锚点、取消后不落盘、基础设施阻断不花模型轮次、失败调用用量、镜像变化禁止准入及独立结果不进入提示。该测试使用注入响应，不计真实模型效果；前一阶段 Docker 验收仍见独立验证器文档，本轮未重复 Docker 验收。

下一项实际工作：用这个入口继续修正保存的 agg1，逐轮查看公开失败是否消除，结束后单独评分并关联 Langfuse。保留正负结果和全部成本，不改写原 21/50 基线。
