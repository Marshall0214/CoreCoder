# 补丁前后差异反馈 v1：未采用

本轮完成一个核心机制实验：第二轮修复同时看到当前函数、公开失败信息和第一轮实际补丁差异，尝试让模型撤销错误修改。真实对照没有提高修复通过数，并造成 Click 分支失败，因此冻结为可选原型，不接入默认 Agent 或服务，也不扩大到六项任务。

## 实现与约束

[差异装填](experiments/patch_delta_context_v1.py) 从任务起始文件字节和第一轮实际候选计算零上下文 unified diff，记录修改前后文件 SHA-256。差异仅供理解历史，结构事务仍只接受当前片段中的唯一匹配编辑；旧历史不能作为编辑锚点。没有读取参考修复或私有评分测试。

[Worker](experiments/patch_delta_worker_v1.py) 保留原首轮提示、公开检查、最多一次反馈和共享 15,000 Token。只在有实际修改的反馈阶段加入历史，历史 JSON 上限 2,000 字符；历史与源码契约、当前函数共同计入原 6,000 字符证据预算，最多五函数。当前已编辑函数必须完整保留，低优先级片段可能被挤出；预算不够或文件范围异常时停止，不截断必需证据。

[离线审计](experiments/patch_delta_audit_v1.py) 使用两项历史首轮候选，零模型调用确认删除的回退逻辑可见、源码没有被审计改动、预算内装填。Click 历史占 1,228 字符、组合证据 5,075；none-salt 历史占 543、组合证据 5,972。离线检查只证明实现可用，不证明修复能力。

## 两项真实任务的新配对

固定本地 Ollama `qwen3.5:27b`、关闭思考、temperature=0、top_p=1、模型摘要、工具集合和原预算；两策略各两项任务、每项一次，从干净版本运行。两项首轮提示哈希逐对一致，私有 Target/Controls 由父进程独立评分，不反馈给模型。任务已查看，是开发验证而非盲测或泛化基准。

| 任务 | 基线 | 差异反馈 |
| --- | --- | --- |
| click-usage-empty | 修复成功 | 第二轮片段不匹配，拒绝补丁，最终失败 |
| itsdangerous-none-salt | 目标及控制测试失败 | 恢复两处回退，控制测试通过，但目标仍失败 |

独立修复通过数 **1/2 → 0/2**。none-salt 恢复 `make_signer` 和 `iter_unsigners` 的原有回退，是局部纠正；构造函数仍把显式 None 变成错误的固定默认值，没有解决缺陷。两项控制测试通过分支 **1/2 → 2/2**，不能据此替代主要修复指标或宣称总体改善。

Click 的当前完整 `HelpFormatter.write_usage` 和 `Command.format_usage` 都在提示中。模型复述第一段 old 文本时漏掉当前代码中间的 `text_width = self.width - self.current_indent`，事务报 `Edit text was not supplied in local context`，整个第二轮补丁未提交。这不是缺少该函数或预算预检查停止；差异展示可能影响原文复述，但单次运行不能证明其因果机制。

| 指标 | 基线 | 差异反馈 |
| --- | ---: | ---: |
| 模型调用 | 4 | 4 |
| 返回 usage Token | 16,931 | 16,867 |
| 独立修复通过 | 1/2 | 0/2 |
| 控制测试通过分支 | 1/2 | 2/2 |
| Worker 总耗时（秒） | 64.60 | 69.12 |

总计 **8 次本地 Qwen 请求、33,798 Token**，没有 DeepSeek 调用。64 Token 差异不构成效率收益；运行与软件测试并行，耗时不是稳定性能结论。

本轮比较的是独立实验工作区中的反馈策略，没有运行最终暂存发布门控。Click 被拒绝的第二轮不写回，但第一轮候选仍保留；不能把这里的 failed workspace 当作已发布的服务代码。已有暂存服务及所有冻结实验实现均未修改。

正式记录 `.tmp/real-defects/patch-delta-compare-v1/experiment.json` 与 [机器摘要](patch-delta-v1.json) 保留全部分支、usage、提示、回答、预算、片段和独立检查。入口为 [对照脚本](experiments/patch_delta_compare_v1.py)。

## 软件验收与结论

新增 **10 项测试通过（1.13 秒）**，覆盖差异/版本哈希、预算装填、创建删除和越界拒绝、旧版本不能成为编辑锚点，以及两轮实际补丁与公开检查。最终 Windows 全量 **1,144 passed、2 skipped（193.67 秒）**，Ruff 通过。开发时修正了测试复用暂存专用断言、CRLF 比较及事务前置参数的问题；真实配对仅运行这一轮，没有选择性重跑。

按预定停止条件，不采用该策略。下一项核心工作优先解决已定位的“当前代码已展示但 old 片段复述错误”，保持版本验证与唯一匹配保护，避免继续扩大上下文、轮次或外围功能。任何新的编辑协议必须单独标明干预变量，再用独立修复结果验收。

## 复跑

依赖原有任务准入快照、公开认证、历史审计和隔离 Python；不能仅 clone 重建全部数据。保持产物在 D 盘，输出目录必须全新：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m pytest tests/test_patch_delta.py -q -p no:cacheprovider --basetemp .tmp/patch-delta-rerun-tests
python -B -m docs.experiments.patch_delta_compare_v1 --output .tmp/real-defects/patch-delta-rerun
```
