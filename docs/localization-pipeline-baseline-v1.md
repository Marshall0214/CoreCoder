# localization-pipeline-baseline-v1：有界管线完整开发集基线

日期：2026-10-04。固定 bounded-pipeline-v1 协议，在 localization-v1 全部五个任务上各运行三次，建立当前管线的完整开发集结果。独立验收仍使用原目标与回归测试；不能将它与旧 Agent 不同工作流的结果作为单项检索因果对照。

## 冻结协议

Qwen3.5:27b Q4_K_M、temperature=0、reasoning_effort=none、keyword、K=5、依赖深度2、selection 顺序、完整文件正文预算6,000字符、Token30,000、单次输出2,048、评测估算上下文16,000、Worker180秒、测试15秒。baseline 生成提示、不启用 read-cover、契约提示或跨轮去重。每次从干净工作区开始，单请求生成结构化补丁，父进程独立验收。

执行顺序为每轮依次 artifact-routing、checkout-rounding、event-replay、job-deadline、pagination-cursor，重复三轮。没有根据中途结果改变 Prompt、预算、模型或任务；失败保留，不选择性重跑。Ollama 缓存未清空，耗时受机器状态影响；三次重复不代表三个独立缺陷。

此前离线评测显示 K5 的五项任务参考修复源码全部在证据中；本批再按每次实际证据 manifest 核对。参考修改文件仅用于运行后的覆盖分析，不进入查询、索引、模型或生成逻辑。

## 完整基线结果

| 任务 | 独立通过 | 每次输入 / 输出 / 总 Token | 端到端中位秒数 | 已修复与遗漏 |
| --- | --- | --- | --- | --- |
| artifact-routing | 0/3 | 711 / 86 / 797 | 18.11 | 修复路径规范化；遗漏规则优先级 |
| checkout-rounding | 3/3 | 956 / 227 / 1,183 | 21.56 | 行金额和折扣均按半入舍入 |
| event-replay | 0/3 | 706 / 197 / 903 | 20.76 | 修复重复事件导致提前结束；遗漏租户身份隔离 |
| job-deadline | 0/3 | 1,054 / 71 / 1,125 | 17.66 | 修复单次 timeout 上限；遗漏等待不能超过 deadline |
| pagination-cursor | 0/3 | 949 / 174 / 1,123 | 20.15 | 修复同时间戳比较；遗漏 lookahead 续页游标 |

总计 **3/15（20%）**，五个独立人工开发任务，仅金额任务通过；三轮任务结果与各任务 Token 一致。15 次总计 **15,393 Token**，每次一次模型调用、正常生成结束、usage 完整；无预算终止、格式拒绝、越界或基础设施错误。全部可见回归测试通过；隐藏目标分别为归档2/4、金额5/5、事件2/4、截止时间1/4、分页2/4通过。失败保持 failed_verification，命令最终退出码1。

所有参考修复目标文件均包含在每次实际证据里；五项正文分别为1,122、1,295、961、2,078、1,563字符，无预算丢弃。每个失败任务都修改一处而遗漏另一处契约行为；公开契约已描述这些规则。该观察不能证明全部必要上下文充分，也不能把文件级召回100%解释为生成正确性；但继续增加 K 或预算并不是已有证据支持的优先改造。

同任务三次的实际 Prompt、证据集合、初始工作区、任务及目标测试哈希一致；全部运行使用共同配置与源码哈希 `0e8cc8c575b6aa6a66e0bce05e0256c09ea5931bdea214e35c6e91a9ceeb6816`。核对 Ollama0.34.3、Q4_K_M 模型 digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`、实际上下文32,768。首次归档运行前模型未加载，其余已加载，不将耗时差解释为机制收益。

旧受限 Agent 在同任务集为0/15，本管线为3/15，但工具循环、生成方式、证据组织与代码版本都不同，只能作为不同系统的开发集结果，不能写成检索带来20个百分点提升。历史分页/租约 pilot 不并入此次分母；本集曾用于机制开发，不是留出集或真实仓库泛化评测。

## 证据与下一步

完整汇总 `.tmp/evals/localization-pipeline-baseline-v1/summary-bfb0172183.json`（同名 .md），逐项配置/哈希/覆盖核对为 `baseline-audit.json`，核对脚本 `.tmp/audit_pipeline_baseline.py`。各次目录保留 pipeline-response.txt、patch.diff、trace.jsonl、原始验收输出和版本元数据。核对脚本仅事后读取评分标签，没有回传模型或选择性重跑。

本次冻结已有运行代码，新增实验文档，未重复运行单测；上一阶段完整测试314 passed、1 skipped。本批验证为15次真实模型运行、各次父进程目标与回归验收、配置/哈希审计及 git diff --check。

下一步在同版本管线中对照 baseline 与通用契约覆盖的结构化生成策略：从公开描述和证据列出行为约束、依据及代码对应关系，再输出补丁，不注入任务专用答案或隐藏测试。保持相同检索结果、预算和一次模型调用；新增输出与提示属于明确的生成策略干预，不作为检索收益。模型自报覆盖只用于诊断，成功仍由独立验收判定；先小批检查格式与预算，再决定完整对照。

## 复跑

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode pipeline --search-backend keyword --evidence-order selection --evidence-top-k 5 --evidence-dependency-depth 2 --search-max-chars 6000 --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/localization-pipeline-baseline-replay
```

使用新目录。存在失败时退出码为1，这是验收结果，不应因此删掉产物或重跑。工作区、原始模型输出、Trace、补丁、独立目标与回归输出都保留在各 run_id 目录；原始产物被 Git 忽略，需独立备份。
