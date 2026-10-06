# 紧凑装填真实补丁对照 v1

## 设计与实现

固定七个开发任务及原检查点，read-first / compact-read-first-v1 各发起一次补丁请求，按任务交替执行顺序，共 14 个分支。模型仍为 Ollama qwen3.5:27b，temperature=0、reasoning_effort=none；原 30k 总预算、15k 补丁阶段上限、16k 上下文、2,048 输出上限及 6,000 字符证据正文上限均未改变。

独立入口为 `docs/experiments/staged_compact_live_v1.py`，冻结协议为同目录 `.json`，当前 revision=2。适配层、紧凑算法及覆盖模块分别绑定 SHA；原 `corecoder/`、`evals/` 的修复源码哈希仍为 `c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd`。旧检查点未修改，现有校验器仍检查描述、配置、候选文本、源码及实现版本；独立适配代码的版本由新协议补充绑定。

两组共用候选池、系统提示、非证据指令、预算和空工具集合。Worker 只收到原源码、公开 Controls 和检查点，不收到 Target、参考补丁或另一组反馈；父进程分别从原源码新建评分副本，运行独立 Target 和 Controls。历史补丁运行不并入本轮。

测试确认适配层的 baseline 请求与原 `patch_staged` 重放逐项一致。实际运行再次确认 **7/7 baseline 完整提示哈希与历史 baseline 相同，7/7 配对候选池及非证据指令相同**，源码和检查点未变，模型调用前后摘要一致。适配层显式使用紧凑选择器，没有替换全局函数或绕过旧哈希校验。

## 结果

| 指标 | read-first | compact-read-first-v1 |
| --- | ---: | ---: |
| 独立验收通过 | 2/7 | 1/7 |
| 公开 Controls 通过 | 5/7 | 4/7 |
| failed_verification | 5 | 5 |
| invalid_patch | 0 | 1 |
| 实际模型调用 | 7 | 7 |
| 输入 Token | 16,661 | 20,232 |
| 输出 Token | 2,999 | 2,556 |
| 实际补丁 Token | 19,660 | 22,788 |
| 流水线等效 Token | 82,973 | 86,101 |

| 任务 | read-first | compact |
| --- | --- | --- |
| help-eagerness | 验收失败 | 验收失败 |
| flag-default-map | 通过 | 通过 |
| resource-exception | 验收失败 | 非法补丁 |
| flag-envvar（跨文件） | 验收失败 | 验收失败 |
| prompt-suffix | 验收失败 | 验收失败 |
| invoke-missing | 通过 | 验收失败 |
| shared-default | 验收失败 | 验收失败 |

有效批次实际消费 **14 次调用、42,448 Token**，没有新增定位调用，提供方用量均已返回。历史共享定位 63,313 Token 已在此前发生，不再次计入实际费用；两组等效记账合计 169,074 Token，包含重复纳入的历史定位成本。

## 如何理解

紧凑策略没有改善本批修复结果，并使实际补丁 Token 增加 3,128。完整消息 JSON 在四个任务中变长；“正文去掉文档字符串”不能保证完整请求更小或 Token 更少。

prompt-suffix 虽然同时装入 prompt 和 confirm 的非文档范围，仍未通过；生成补丁无条件改变了输入提示空格处理，而公开需求要求保留正常 suffix 行为。覆盖改善不等于正确理解契约。prompt 尾部原有的 9 行缺口仍未补齐。

resource-exception 的补丁包含上下文未展示的旧文本，现有校验器拒绝应用，原子校验保持源码不变；失败计入 7 个任务分母。不能为提高通过率而放宽可见文本约束。invoke-missing 从原策略通过退化为失败；目前只观察到输出改变，尚未隔离文档删除、新增代码和分段元数据各自的作用。

这是每策略一次请求、七个 Click 开发任务的组合干预。相同旧 baseline 提示的重现不能增加独立样本量，也不证明跨仓库效果。保留 read-first 默认，不推广 compact；不增加同输入重复轮数或任务预算。下一步先离线审查退化请求及非法补丁，区分契约信息丢失、证据缺口和补丁表达问题，再决定是否修改策略。

## 启动失败批次

首批 `.tmp/real-defects/staged-compact-live-v1/` 的 14 个 Worker 均因启动时使用评分环境解释器而缺少 `openai` 包，未发起模型调用。失败批次及其嵌入协议保留，不并入 revision=2 的策略对照。

修订版明确用运行实验的 `corecoder` 解释器启动 Worker，继续用准入记录的评分解释器执行检查。修订协议在有效模型请求前冻结，并记录前一协议 SHA；未安装额外依赖，未覆盖旧产物。新增隔离进程测试验证 Worker 可启动并在模型调用前拒绝变更协议。

## 复现与验证

```powershell
python docs/experiments/staged_compact_live_v1.py --validate-only --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-compact-live-v1-rerun
```

移除 `--validate-only` 执行真实补丁实验；必须使用已安装模型依赖的 `corecoder` 环境，输出必须为新目录。

```powershell
python docs/experiments/staged_compact_analysis_v1.py .tmp/real-defects/staged-compact-live-v1-rerun/experiment.json
python -m pytest tests/test_staged_compact_live.py tests/test_staged_compact_packing.py tests/test_staged_evidence_coverage.py tests/test_staged_replay.py tests/test_staged_repair.py -q
```

分析入口还需历史三轮报告核对 baseline 提示。原检查点、准入源码和历史产物被 Git 忽略，应另行保存。

本次原始结果在 `.tmp/real-defects/staged-compact-live-v1-r2/experiment.json`、`analysis.json`；各分支包含完整补丁请求、响应、Trace、补丁及独立评分。相关测试 **35 passed**，Ruff 通过；修复实现未改变，未重跑全量测试。
