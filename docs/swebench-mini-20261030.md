# SWE-bench Verified Mini：首项官方评测与 Langfuse 实验接入

本轮完成一项真实任务的**评测链路验收**，没有运行 Agent 或模型。使用未修改代码和数据集参考补丁，验证 Docker 环境、官方测试脚本、解析器、评分及 Langfuse 数据集实验关联。原有 `47/50` 历史实验保持不变。

## 1. 数据来源与固定任务

- 社区子集：[MariusHobbhahn/swe-bench-verified-mini](https://huggingface.co/datasets/MariusHobbhahn/swe-bench-verified-mini)，`test` 共 50 项，仅覆盖 Django、Sphinx；不是官方另发的 50 项 Verified。
- 子集 revision：`b316c349947c29963fce3f4a65967c9807a4b673`。
- 当前官方数据：[SWE-bench/SWE-bench_Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified)，revision `78f471bf655a3137b2e8a75af1501690ec009ec3`。下载的是约 6.3 MB 的任务元数据，没有下载其余 499 项运行环境。
- 首项按任务 ID 排序选择：`django__django-11790`，未根据模型结果选题。
- 仓库 `django/django`，基线 `b1d6b35e146aea83b171c1b921178bbaae2795ed`。
- 任务：认证表单的 username 字段未正确设置 HTML `maxlength`，参考补丁恢复该属性，并处理字段没有最大长度时的默认值。

Mini 使用旧数据结构；当前 Harness 需要官方新增的 image、eval_script、log_parser、eval_type。适配器在选中项上逐字段核对仓库、commit、Issue、参考补丁、测试补丁和版本，解析 JSON 后比较测试标签集合，再采用当前官方评测脚本；不静默替换题目或评分标签。任务包括 **2 项 FAIL_TO_PASS、77 项 PASS_TO_PASS**。

本轮冻结了 50 个 ID，只执行其中 **1 项、2 个控制组**。它与旧项目的 50 项真实来源缺陷是不同任务池。

## 2. 实际结果

| 控制组 | 目标测试 FAIL_TO_PASS | 正常行为 PASS_TO_PASS | 官方 resolved | 本次耗时 |
| --- | --- | --- | --- | --- |
| unchanged，源码不修改 | 0/2 通过，2 项失败 | 77/77 通过 | false | 4.890 秒 |
| reference，使用参考补丁 | 2/2 通过 | 77/77 通过 | true | 5.438 秒 |

两个控制组均使用相互独立的新容器。结果说明该任务环境和评分可用，**不代表 Agent 已修复一项，更不是 Mini 的 100% 通过率**。新模型调用 0、没有 thinking 或付费 API。

两个 eval.sh 进程的最终退出码都为 0，因为测试后还有还原测试文件等命令。适配器依赖官方解析器和逐测试结果判分，不能用脚本退出码当作修复成功。

## 3. 执行方式及隔离边界

使用官方 `swebench==5.0.2` 的 TestSpec、测试脚本、日志解析与 `get_eval_report`；外围 Docker 调度由本项目实现，**不是未经修改的官方 run_evaluation CLI，也不是榜单提交**。

每个控制容器禁网、无宿主目录或 Docker socket 挂载，不注入模型凭据；限制 2 CPU、4 GiB 内存、256 PID，移除 capabilities、禁止提权，默认 600 秒超时，结束后仅清理本次容器。官方脚本生成 locale 等操作需要容器内 root 和可写根文件系统，因此不能描述为沿用旧任务的“非 root、只读根文件系统”沙箱配置。适用范围是可信参考补丁和测试；尚未接入任意模型候选补丁。

镜像按本地不可变 ID 执行：

```text
swebench/sweb.eval.x86_64.django_1776_django-11790:latest
ID: sha256:e0e74c3332a0c6bd8b1c8409fd966da5dc7b8836d9c4e0fa139908068d8f1d21
Registry manifest: sha256:97132bd9fa42be42add93741520b3e58dbba8a693a209757a18381a31d386ec5
```

下载 10 层、压缩约 1.15 GB，逐层校验 SHA-256 后导入 D 盘 Docker 存储。作者所述约 5 GB 是其环境组合的估计，不作为本机官方镜像总占用保证。[子集构建说明](https://github.com/mariushobbhahn/SWEBench-verified-mini)。

镜像初始 HEAD 为 `84a9058f3ff86c9e7b27cc134460437fc9a4aac1`，与任务基线不同。首次执行被检查拦截，未产生评分；修正为仅在无宿主挂载的新容器内 checkout 指定 commit，并验证实际 HEAD 和 tracked diff 后执行。第一次失败记录保留在 `.tmp/swebench-mini-controls-20261030/`，成功记录在带 `-v2` 的新目录。

旧版 4.1.0 在 Windows 导入时触发 Linux-only `resource` 错误；没有伪造模块或修改上游代码，改为当前官方 5.0.2 并固定版本。准备数据、依赖、临时文件、缓存和镜像归档均在 D 盘；原 conda 环境的包未被覆盖。

## 4. Langfuse 中已有什么

同一个数据集包含一个已接通的任务，两个实验分别表示 unchanged 和 reference：

- [数据集](http://127.0.0.1:3300/project/corecoder-issues/datasets/cmvus85580003oa1wjbngpych)。
- [未修改代码实验](http://127.0.0.1:3300/project/corecoder-issues/experiments/results?baseline=6962e27d95fd1c4c)。
- [参考补丁实验](http://127.0.0.1:3300/project/corecoder-issues/experiments/results?baseline=10923803166b9fc4)。

每组回读确认 experiment、dataset、trace 的关联、输出与本地一致以及四项评分：`official_resolved`、`fail_to_pass`、`pass_to_pass`、`fresh_model_calls`。前两组的目标通过比例为 0 和 1，回归比例均为 1，模型调用均为 0。

**这些实验是实际官方评分完成后的结果导入**，标记 `source=official_grading_replay`、`is_agent_result=false`。Langfuse 自动记录的实验任务时长是导入耗时；实际容器检查耗时保存在输出的 `seconds`，不能把导入耗时当作修复速度。

上传的输入仅有任务 ID、仓库、基线 commit、Issue 描述哈希；不上传参考补丁、测试补丁、测试标签或原始日志。`expected_output` 只声明目标为 resolved=true，不包含实现答案。

本地 `agent/input.json` 保存模型将来需要的公开描述，`grader/instance.json` 保存评分材料。当前只是字段和目录分离；后续接入 Agent 时还需使用单独工作区和工具范围，不能把父目录直接交给 Agent。

## 5. 复现命令

已有依赖可直接使用。新机器可按 `evals/swebench-requirements.txt` 安装到新的 D 盘 target；Langfuse SDK 按现有[部署文档](langfuse-local.md)安装。不要覆盖现有 conda 包。

本机 Harness 运行配置：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHON_DOTENV_DISABLED='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:HF_HOME='D:\project_other\CoreCoder\.tmp\swebench-cache\hf'
$env:XDG_CACHE_HOME='D:\project_other\CoreCoder\.tmp\swebench-cache'
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\swebench-v5-deps;D:\project_other\CoreCoder\.tmp\swebench-deps;D:\project_other\CoreCoder'
```

已下载文件分别位于 `.tmp/swebench-mini-setup-20261030/mini.parquet` 和 `official-0.parquet`。准备输出必须是新目录：

```powershell
python -B -m evals.swebench_mini prepare --mini-parquet .tmp/swebench-mini-setup-20261030/mini.parquet --official-parquet .tmp/swebench-mini-setup-20261030/official-0.parquet --mini-revision b316c349947c29963fce3f4a65967c9807a4b673 --official-revision 78f471bf655a3137b2e8a75af1501690ec009ec3 --output .tmp/swebench-mini-entry-002

python -B -m evals.swebench_mini run --entry .tmp/swebench-mini-entry-002 --image-id sha256:e0e74c3332a0c6bd8b1c8409fd966da5dc7b8836d9c4e0fa139908068d8f1d21 --output .tmp/swebench-mini-controls-002
```

发布使用另一个终端或切换 PYTHONPATH，使 SDK 与 Harness 的依赖分开；这里只上传现有评分，不重复运行测试或模型：

```powershell
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder'
$env:NO_PROXY='127.0.0.1,localhost,::1'
python -B -m deploy.langfuse.swebench_mini --entry .tmp/swebench-mini-entry-002 --controls .tmp/swebench-mini-controls-002 --env-file .tmp/langfuse-local/.env --output .tmp/swebench-mini-langfuse-002.json
```

数据文件应从上述 Hugging Face 仓库的固定 revision 下载，保持原 parquet；入口 manifest 保存 SHA-256、完整 50 项 ID 和首项选择规则。镜像、公开测试脚本、标签与评分版本都需要一起固定；官方流程参考[评测指南](https://www.swebench.com/SWE-bench/guides/evaluation/)。

## 6. 交付边界与下一步

新增 20 项测试覆盖固定选择、数据和标签漂移、输入完整性、缺失/矛盾评分、服务器关联验证、容器约束及异常/超时后清理；与现有 Langfuse 相关测试合计 69 项通过，Ruff 通过。真实 Docker 控制组和 Langfuse 回读另有证据，见[冻结清单](swebench-mini-20261030.json)。

下一步是**只对这同一项运行一次本地 Agent**：让它读取实际基线仓库、独立定位和生成补丁，再交给同一评分器。不能把参考补丁、目标文件列表或评测专用测试反馈给 Agent；这需要单独的仓库范围与工具适配，不直接复用只接受手工 allowed_files 的旧任务入口。本轮不自动扩大到 50 项，不调用 DeepSeek，不把参考补丁通过当作 Agent 成绩。

后续[第一次真实 Agent 尝试](swebench-agent-20261030.md)已执行：本地 Qwen 关闭 thinking，6 次调用、19,364 Token；定位后重复读取，未生成补丁，目标 0/2、回归 77/77。原始推理与后置评分均已关联 Langfuse；保留失败，没有自动重跑。
