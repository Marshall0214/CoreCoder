# evidence-order-v1：固定证据的组织顺序对照

日期：2026-10-04。目的：在 bounded-pipeline-v1 中，验证证据组织顺序是否影响完整修复；不改变检索、证据集合或生成机会。

## 实现与冻结条件

新增 `--evidence-order selection|path`，默认 selection 保留排名种子和广度优先依赖顺序；path 在选择、依赖扩展、完整文件预算裁剪完成后按相对路径排序。未提供证据的源码仍不能修改。其他模式拒绝 path，避免未生效配置。

`pipeline_evidence_ordered` 保存选择顺序、请求顺序、正文与元数据的顺序无关哈希 evidence_set_hash，以及包含顺序的 ordered_evidence_hash。生成阶段只接收重新排列的文件数组，不额外注入策略名称、提示或工具。默认 selection 的原请求正文保持一致。

固定 Qwen3.5:27b Q4_K_M、temperature=0、reasoning_effort=none、Token 30,000、输出 2,048、估算上下文 16,000、Worker 180 秒、测试 15 秒。BM25 查询、K=5、依赖深度=2、正文 6,000 字符和独立验证器不变，每次干净工作区、一次模型调用。两个开发任务每组各三次，共十二次；不合并旧版本结果。

运行顺序按重复轮交错：第 1/3 轮 selection→path，第 2 轮 path→selection；每轮先分页再租约。未要求清空 Ollama 缓存，局部耗时受加载、缓存和机器状态影响，不作为顺序收益证据。temperature=0 的重复不代表独立任务。

## 十二次结果

| 任务 | 顺序 | 独立通过 | 每次输入 / 输出 / 总 Token | 端到端秒数（按重复轮） |
| --- | --- | --- | --- | --- |
| pagination-cursor | selection | 0/3 | 949 / 174 / 1,123 | 25.26、19.99、20.12 |
| pagination-cursor | path | 0/3 | 949 / 174 / 1,123 | 20.59、19.98、20.10 |
| lease-lifecycle | selection | 3/3 | 1,338 / 574 / 1,912 | 30.11、28.94、29.41 |
| lease-lifecycle | path | 3/3 | 1,338 / 554 / 1,892 | 29.04、28.87、28.48 |

每组均为一次模型调用；usage 完整，无基础设施错误、预算终止或选择性重跑。首次分页 selection 运行前模型未加载，其余已加载，故不能把首轮耗时差解释为组织顺序影响。模型调用后均核对同一 Ollama 0.34.3、模型 digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e` 与实际上下文 32,768。

同任务两组的配置仅 evidence_order 不同；源码、任务 manifest、初始工作区、评分测试哈希一致，证据集合/正文哈希一致、实际组织顺序不同。源码哈希：`42348612fea8ee90917f931467e5f287ec6c82f7453532740a36961e1452c1ba`。分页仍为 5 文件 / 1,563 字符，租约仍为 8 文件 / 2,054 字符；每组内三份实际 Prompt 哈希一致。selection 的两个 Prompt 哈希与前次管线 pilot 一致，但前次不计入本实验分母。

分页六次均仅修改 query.py，遗漏 paging.py 的续页游标；契约及两处缺陷文件均已提供。租约两组都修复三处缺陷，selection 另修改 renew.py 添加防御性检查，path 仅改 acquire.py、expiry.py、lookup.py。因此 path 每次少 20 个输出 Token，输入 Token 相同；这是当前任务的补丁长度差，不是通用成本收益。

**结论：这两个开发任务上没有观察到组织顺序带来的修复成功率提升。**不能据此证明顺序在其他任务或模型上无影响。保留默认 selection，不在此阶段增加额外生成机会。

原始完整汇总：`.tmp/evals/evidence-order-v1/summary-ba4286b106.json`（同名 .md），完整报告数组为 `all-reports.json`，配置/哈希核对为 `comparison-audit.json`。每次补丁、原模型输出、目标与回归测试保存在对应 run_id 目录；核对脚本 `.tmp/audit_evidence_order.py` 也需独立备份。代码验证：**303 passed、1 skipped**（Windows 符号链接环境），Ruff 与 git diff --check 通过。

下一步先在共同管线、固定路径排序和 6,000 字符预算下对照种子 K=5 / K=10，检查证据范围能否解释全部公开证据诊断与有界管线的差异；既有缺陷文件已经召回，不能预设范围扩大必然有效，也不使用隐藏测试指导证据选择。

## 复跑

在已激活的 corecoder 环境执行；新实验使用新输出目录：

```powershell
python -m pytest tests -q
foreach ($rep in 1..3) {
    $orders = @('selection', 'path')
    if ($rep -eq 2) { $orders = @('path', 'selection') }
    foreach ($task in @('pagination-cursor', 'lease-lifecycle')) {
        $suite = 'evals/fixtures/localization-v1'
        if ($task -eq 'lease-lifecycle') { $suite = 'evals/fixtures/retrieval-overlap-v1' }
        foreach ($order in $orders) {
            python -m evals --suite $suite --task $task --mode pipeline --search-backend keyword --evidence-order $order --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output ".tmp/evals/evidence-order-replay/$rep/$task/$order"
        }
    }
}
```

失败验收返回 1，保留并继续后续运行；基础设施错误单列，取消后停止。当前开发者批次使用相同次序的 Python 调度脚本，每份报告记录重复号，脚本保存于 `.tmp/run_evidence_order.py`；脚本与原始产物被忽略，应独立备份。复跑 CLI 各次为独立批次，重复轮以目录命名识别。
