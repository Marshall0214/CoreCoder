# 从重复读取推进到候选补丁：三项开发验证

本轮没有重跑 50 项，也没有更换模型、开启 thinking 或增加预算。保留原始 0/50 报告，审计失败后新增一个显式可选的候选生成流程，在三个已检查过的开发任务上各尝试一次。

## 1. 失败审计

上一轮 50 项全部完成独立评分、没有环境异常，真实模型请求 371 次、1,193,835 Token，非空补丁 0、通过 0。

- 371 个动作全部属于读取和定位：search 61、read_file 222、read_symbol 61、list_files 27，没有 apply_patch 或 finish。
- 26 个任务曾读到至少一个完整符号；完整不保证该符号就是正确修复目标，因此不能把 50 项全部归为上下文已经充分。
- 读取记录原先只用 path、version、offset 区分。符号内 offset=0 与文件 offset=0 是不同坐标，但会互相覆盖。9 个任务出现“完整符号读取后紧接同文件同 offset 文件读取”的序列。
- 工具错误包含 invalid_arguments 15、symbol_ambiguous 1、invalid_offset 2；这与定位/阅读阶段无法推进共同存在。

这些观察支持修复读取状态和执行流程，但不证明每个失败都由同一个问题造成。审计计数与逐任务名单见冻结包 `audit.json`。

## 2. 本轮改动

新增 `evals/repository_checkpoint.py`，保留旧实现文件不动：

1. **区分读取记录：**键包含路径、源码哈希、读取类型、符号名和偏移；同版本的文件片段和符号定义可以共存，发布修改后旧证据全部失效。
2. **显式生成阶段：**探索阶段仍由模型选择搜索/读取；出现完整符号后，控制器切换到候选生成协议，模型返回结构化 edits，而不是继续在六类动作中自由选择。
3. **收敛生成上下文：**候选阶段仅携带完整符号定义，移除重叠文件前缀；缺少依赖时可请求最多两个具体符号。不是把参考修复或隐藏测试送给模型。
4. **执行器验证：**仍执行当前版本、已读证据、唯一锚点、实际修改和语法校验。第一个有效候选生成后停止，再独立评分，不根据评分反馈请求修正。

仍有 20 次请求、6 次编辑尝试、30,000 Token、2,048 单次输出、16,000 估算上下文、1,200 秒 deadline。使用同一 Qwen3.5:27b digest、think=false、temperature=0 和同一小型 Docker 镜像；模型和沙箱身份均在协议记录。

## 3. 实际结果

| 开发任务 | 保存的 v1 结果 | 新流程结果 | 新模型调用 | 新 Token |
| --- | --- | --- | ---: | ---: |
| click-usage-empty | 未修复、无补丁 | 生成补丁；Target 2/2、Controls 2/2 通过 | 5 | 9,744 |
| toolz-join-unmatched | 未修复、无补丁 | 未生成补丁；重复读取停止 | 7 | 25,600 |
| boltons-repeat-equality | 未修复、无补丁 | 生成补丁；Target 1/1、Controls 1/1 通过 | 6 | 19,996 |
| 合计 | 0/3、非空补丁 0 | **2/3、非空补丁 2** | **18** | **55,340** |

这三项原先消耗 71,649 Token，本轮减少 16,309，即 **22.76%**。两项成功补丁分别处理 Click 空参数 usage 输出，以及 Boltons 对 `'repeat'` 使用对象身份比较导致的错误。仅通过项目既有手写 Target/Controls，不等于上游全套测试通过。

这是**三项已知开发失败的单次顺序对照**，没有独立留出或重复采样。读取记录修正、阶段切换和上下文收敛一起生效，没有消融，不给单一组件分配收益。不能把原始完整 0/50 报告改成 2/50，也不能把 2/3 外推为完整任务池修复率。旧 DeepSeek 94% 仍属于另一个历史协议。

## 4. 剩余失败与下一步

Toolz 搜索已命中 `join`：定义在第 813 行，对应字符起点 19,788。但后续反复执行 read_file(offset=800)，实际读取字符 `[800, 6800)`，没有覆盖函数，也没有读到完整符号，因此候选阶段没有触发。

这与把行位置近似当成字符偏移的行为相符，但不能直接得知模型内部原因。下一步应为搜索命中提供明确的符号读取入口或带单位的坐标，减少模型自行换算；先验证这一项，不直接增加循环/预算或重跑 50 项。

## 5. 观测、检查与复现

三个真实推理 Trace 的节点结束状态、实际请求数、原生输入/输出 Token 均经 Langfuse 回读确认；后置评分写回对应 Trace，发布阶段模型调用 0：

- [Click：通过](http://127.0.0.1:3300/project/corecoder-issues/traces/a8773867bef0c181ef518e7f0a1258aa)
- [Toolz：失败](http://127.0.0.1:3300/project/corecoder-issues/traces/7105a9775fdf898de0fac0460a713090)
- [Boltons：通过](http://127.0.0.1:3300/project/corecoder-issues/traces/7fd28cefd5f82a30009bf7de6f1f373a)

相关代码测试 **70 项通过**，Ruff 通过，新增测试覆盖读取坐标区分、版本失效、生成阶段切换、依赖读取、未读锚点拒绝及重复动作停止。

原始结果在 `.tmp/checkpoint-pilot-20261103`。可审查的 29 文件冻结包见[清单](repository-checkpoint-20261103.json)，包括完整报告、两项补丁、评分结果、服务器回执、实现快照、原始请求/响应哈希。未复制原始仓库正文和完整 Prompt。原始 0/50 报告及其实现哈希均检查未变。

```powershell
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE='D:\project_other\CoreCoder\.tmp\langfuse-local\.env'
python -B -m evals.checkpoint_pilot --output .tmp/checkpoint-pilot-new
```

该命令会再次进行三次任务推理，必须使用新目录。本轮只运行了一次；默认 local50/SWE-bench v1 入口没有被静默替换。
