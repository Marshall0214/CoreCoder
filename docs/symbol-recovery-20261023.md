# 符号恢复：真实 Docker 验收与本地模型复测

## 结论

2026-10-23：三项真实 Docker 验收全部通过。随后对 Click #3887 完成一次本地 Qwen3.5 27B 无思考运行，**6 次调用、0 次编辑申请，连续三次工具错误后停止，未修复目标**。没有选择性重跑。
脚本恢复链路已在真实容器测试中验收；真实模型尚未提交补丁，因此本轮不能证明锚点失败恢复的模型效果。不更新历史 47/50。

## 证据

- [结构化汇总及 33 项产物哈希](symbol-recovery-20261023.json)
- [Docker JUnit](symbol_recovery_20261023/docker/junit.xml)
- [模型报告](symbol_recovery_20261023/live/report.json)、[动作记录](symbol_recovery_20261023/live/actions.json)、[Trace](symbol_recovery_20261023/live/trace.jsonl)
- [运行前计划](symbol_recovery_20261023/run-plan.json)、[运行后完整性检查](symbol_recovery_20261023/postflight.json)
- [公开检查](symbol_recovery_20261023/public-checks.py)、[模块声明摘录](symbol_recovery_20261023/module-declarations.txt)

上下文及源码摘录来自 pallets/click，保留 [BSD-3-Clause 许可证](symbol_recovery_20261023/LICENSE-click.txt)。原始请求/响应保存在证据目录 live/step-NNN-*；没有模型内部思考内容。哈希仅证明记录一致性，不是第三方认证。

## 真实 Docker 验收

最初受限环境拒绝访问 Docker 管道；取得本地执行权限后确认 Linux 引擎可用，使用已存在的固定镜像，没有构建或拉取。

| 用例 | 脚本响应数 | 结果 |
| --- | ---: | --- |
| 有效补丁 | 1 | 公开检查通过，保留待审查 diff |
| 错误修复与回滚，旧协议 | 2 | 不交付，恢复原始源码 |
| 两次无效编辑、重读后第三次编辑 | 5 | 新协议通过真实 Docker 公开检查 |

**3 passed，33.55 秒**。每项真实模型调用为 0、accepted=false、准备源码不变。模型响应是脚本，不能计为模型修复成功。

## 本地模型配置

| 项目 | 固定值 |
| --- | --- |
| Issue / 源码 | Click #3887，8.1.8，934813e4d421071a1b3db3973c02fe2721359a6e |
| 执行代码 | 2cbabbda5c53d6bca75e34716da625b588511ad1，另保存实现哈希 |
| 模型 | qwen3.5:27b，Q4_K_M，think=false |
| 模型摘要 | 7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e |
| 协议 | symbol-recovery-v1，初始 context-policy=baseline |
| 次数 | 最多 20 步、6 次编辑；连续错误 3 次停止；同状态相同动作最多执行 3 次 |
| Token | 总量 60,000，单次输出 4,096，上下文 65,536 |
| 时间 | 总期限 1,200 秒，单次请求不超过剩余时间及 480 秒 |
| 允许文件 | src/click/termui.py |

镜像 ID 与准备任务一致，见计划文件。开始时原始目标检查 1 项断言失败、正常行为 3 项通过。
规格来自报告者公开预期，不代表上游已经接受；无独立隐藏评分或参考修复输入。

## 六步实际动作

| 步骤 | read_symbol 请求 | 结果 | 输入/输出 Token |
| --- | --- | --- | ---: |
| 1 | style | 成功，完整原文 4,529 字符 | 3,421 / 27 |
| 2 | _ansi_reset_all | symbol_not_found | 5,871 / 30 |
| 3 | unstyle | 成功，完整原文 340 字符 | 6,304 / 28 |
| 4 | strip_ansi | symbol_not_found | 6,892 / 29 |
| 5 | _ansi_reset_all | symbol_not_found | 7,332 / 30 |
| 6 | _ansi_reset_all | symbol_not_found，达到连续错误上限 | 7,764 / 30 |

初始 style 只有 1,164 字符的不完整片段，新工具确实提供了完整函数。但模型没有申请 apply_patch，没有候选进入 Docker 检查，也未触发锚点恢复。
最终 status=consecutive_error_limit、delivery_status=not_delivered、accepted=false，diff 为空。

## 失败原因与下一项工作

源码中 `_ansi_reset_all` 是实际存在的模块常量，`strip_ansi` 则由 `from ._compat import strip_ansi` 导入。
当前读取器只索引函数/异步函数/类，不包括赋值或导入绑定，因此 symbol_not_found 不等于这些名称在模块中不存在。
模型收到候选列表后仍重复查询常量。直接观察到的是工具知识类型覆盖不足，以及模型未能从查询失败中调整策略，不能说成“六次编辑失败”。

下一步应在同一允许文件内提供受限的常量/导入绑定读取，区分本地定义、导入与未找到；不自动跟随到禁止读取的 _compat.py。
该改动尚未实现或验证，不能保证随后修复成功。保留次数和预算，不单纯增加重试上限。

## 用量与比较边界

本轮输入 **37,584**、输出 **174**，共 **37,758 Token**，约 **41.51 秒**。6 次响应均为 stop，无输出截断、预算耗尽或执行故障。
请求同时携带当前片段和近期读取结果，源码会重复出现；输入随步骤增长，压缩的收益需另立对照。

| 开发轮次 | 调用 | 总 Token | 结果 |
| --- | ---: | ---: | --- |
| 10-19 第一轮 | 2 | 8,274 | NameError 后修正退回原样 |
| 10-19 第二轮 | 2 | 8,877 | 两次不真实锚点被拒绝 |
| 本轮 | 6 | 37,758 | 四次符号查询失败，未编辑 |

三轮步数、上下文与输出上限不同，是开发记录，不是公平消融或显著性比较。耗时也不是受控性能实验。

## 完整性和复现

运行后输入/实现哈希、准备任务及模型摘要不变，没有本任务遗留容器。未访问或重启 8001 服务；无云 API、模型下载或镜像拉取，新增产物位于 D 盘。
实际使用 Python execute 入口及上表参数；等效 CLI 如下。复跑必须换新输出目录，本次只运行一次：

```powershell
python -B -m repairflow repair-issue --prepared .tmp/github-issue-acceptance-20261019/click-3887-v2 --config configs/issue-tasks/click-3887.json --output .tmp/issue-recovery-live-20261023/click-3887-qwen35-symbol-001 --mode ollama --model qwen3.5:27b --workflow symbol-recovery-v1 --context-policy baseline --max-steps 20 --max-edit-attempts 6 --max-consecutive-errors 3 --max-repeated-actions 3
```

容器验收使用 tests/test_issue_repair_docker.py，环境变量 CORECODER_RUN_DOCKER_TESTS=1；完整命令和状态目录配置参见 [工具说明](symbol-read-recovery.md)。
