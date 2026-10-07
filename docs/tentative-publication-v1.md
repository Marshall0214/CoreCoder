# 任务级暂存发布：真实模型对照 v1

本轮验证：同样的修复流程和预算下，正确候选能否正常发布，错误候选能否避免破坏任务起始源码。采用本地 Ollama `qwen3.5:27b`，两项真实缺陷、两种流程各运行一次；这些任务已用于开发，结果不能代表未见任务的泛化能力。

| 任务 | 直接写工作区 | 暂存后验收发布 |
| --- | --- | --- |
| click-usage-empty | 修复成功 | 修复成功，发布净修改 |
| itsdangerous-none-salt | 修复失败，源码已被修改，控制测试失败 | 公开检查失败，拒绝发布，起始源码和控制测试保持 |

两边独立验证均为 **1/2**，修复率没有提升。实际收益是本轮错误候选的发布次数从 **1 次降至 0 次**，失败分支保持任务起始文件字节；这是单个失败任务的观察，不能写成普遍的 100% 保护率。公开验收通过也不等于完整生产正确性。

## 固定条件与开销

两边固定模型及摘要、关闭思考、temperature=0、top_p=1、每分支最多两次请求和共享 15,000 Token；检索、源码契约上下文、已编辑函数保留、工具集合和公开反馈规则相同。两项任务的首轮提示哈希逐对一致。只有写入及最终发布路径不同；模型生成结果不强制相同。

| 指标 | 直接写入 | 暂存发布 |
| --- | ---: | ---: |
| 实际模型调用 | 4 | 4 |
| 返回 usage 计量 Token | 16,911 | 16,931 |
| 控制测试通过的分支 | 1/2 | 2/2 |
| 失败后源码被修改的分支 | 1 | 0 |
| Worker 总耗时（秒） | 65.30 | 70.11 |

暂存分支额外最终验收与发布阶段合计约 **2.84 秒**：Click 2.12 秒，none-salt 0.72 秒。这个阶段不增加模型调用；耗时从 trace 的墙钟时间估算，包含源码检查与发布，不能当作稳定性能基准。并行软件测试和模型执行会影响总耗时，20 Token 差异也不能解读为策略节省或浪费。

私有 Target/Controls 评分由父进程在修复后独立执行，不反馈给模型。失败候选及每轮提示、回答、工具检查、发布日志均保留。正式记录是 `.tmp/real-defects/tentative-publication-compare-v1-certified/experiment.json`，协议包含冻结源码、模型、认证检查和实现哈希；可跟踪摘要见 [JSON](tentative-publication-v1.json)，对照入口见 [代码](experiments/tentative_publication_compare_v1.py)。

## 调试记录与复跑

首轮目录布局错误触发隔离保护：日志目录包含任务源码，暂存分支在模型请求前拒绝。该轮只运行了直接写入的四次模型请求，计量 16,931 Token；另一次修正尝试因日志目录未创建而停止，零请求。两轮未完成记录分别保留在 `.tmp/real-defects/tentative-publication-compare-v1` 和 `tentative-publication-compare-v1-final`，不合并到正式四分支对照。本次总新增模型请求为 **12 次、50,773 Token**，全部使用本地 Qwen，未调用 DeepSeek。

复跑需要已有任务快照、认证公开检查、历史离线审计和隔离评分 Python；输出目录必须全新，临时目录保留在 D 盘：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -m docs.experiments.tentative_publication_compare_v1 --output .tmp/real-defects/tentative-publication-rerun
```

## 软件验收

新增对照统计与阶段耗时测试 6 项通过；Windows 全量 **1,118 passed、2 skipped（171.52 秒）**，Ruff 通过。首次全量发现旧 glob 测试依赖仓库目录排序，文件数超过输出上限后断言失败；改为独立临时目录中的真实文件后全量通过。未修改 glob 行为或冻结引擎，未重跑 Linux、Docker、HTTP。

## 边界与下一步

本轮没有修改默认 Agent、服务或已有冻结实验。暂存保护仍是可选 Worker，要求源码与产物目录互不包含、任务工作区独占；没有跨进程锁、操作系统沙箱或崩溃安全多文件原子提交。

下一步优先把已验证的暂存发布机制接入服务的可选执行路径，保持审批、取消、失败诊断与发布结果一致；不要继续把这一轮的源码保护结果写成缺陷修复率提升。
