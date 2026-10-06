# 定义边界读取：补丁与独立验收 v1

## 本轮做了什么

将 [定位 pilot](definition-localization-v1.md) 的两个新 checkpoint 分别用于相同 `read-first` 补丁阶段：每组一次模型调用，不重新定位、不扩大预算、不反馈隐藏测试。沿用冻结补丁实现、15,000 Token 补丁额度、3,000 验证保留及 6,000 字符证据预算。任务仍是开发集 `click-prompt-suffix`，模型仍为 Ollama `qwen3.5:27b`。

新适配器 `docs/experiments/definition_patch_v1.py` 使用已验证的 read-first 补丁入口；每组独立 Worker、副本和模型计数器。协议 `definition_patch_v1.json` 在真实调用前冻结新 checkpoint 的字节 SHA、候选池及成本、定位运行报告、admission、catalog、模型 digest、引擎与适配器版本。校验两组问题、源码范围、源码版本和配置相同。

父进程首先核对 before 的公开 Controls 通过、Target 断言失败。Worker 只得到公开描述、证据和 Controls，Target 留在父进程；生成补丁后，父进程将允许源码复制到新的 grading 目录，独立运行 Target/Controls，检查范围并保存 diff。Controls 仅为公开小型回归，不代表完整 Click 上游测试。

## 真实结果

| 指标 | baseline 定位 checkpoint | definition 定位 checkpoint |
| --- | --- | --- |
| 本轮补丁调用 | 1 | 1 |
| 补丁生成 / 应用 | 成功 | 成功 |
| Target | 失败（断言） | 失败（断言） |
| 公开 Controls | 通过 | 通过 |
| 源码范围违规 | 无 | 无 |
| 新补丁 Token | 3,039 | 2,830 |
| 上轮定位实际 Token | 11,654 | 7,537 |
| 定位 + 补丁累计 Token | 14,693 | 10,367 |
| 最终状态 | failed_verification | failed_verification |

本轮新消耗 **5,869 Token、2 次模型调用**；加上上轮已发生定位费用，两个完整分支累计 **25,060 Token**。定位不再次计费。两组非证据提示哈希相同；补丁额度均为 15,000，没有把 definition 剩余定位额度追加到补丁阶段。

两组应用后的 diff **完全相同**，都只修改 `_build_prompt`：

```python
# 原来
return f"{prompt}{suffix}"
# 两组生成
return f"{prompt}{suffix}" if suffix else prompt
```

在 `prompt` 和 `suffix` 均为字符串的预期输入下，此改动不改变行为：非空后缀执行原表达式，空后缀拼接结果原本就是 `prompt`。因此出现“补丁有效应用、公开检查通过、实际缺陷未修复”。该解释来自生成 diff 和源码，不通过参考补丁推导。

公开描述要求空 `prompt_suffix` 同时影响 **prompt 和 confirm**。离线核对提交给补丁模型的证据：baseline 包含 prompt 83–182，definition 包含完整 prompt 83–191；两组均未包含 confirm 的实现（194–252）。这是对公开需求的覆盖诊断，未把行号或诊断结果反馈给本轮模型。读全一个函数不等于读全需求涉及的代码。

## 结论与下一步

**本次完整定义阅读改善了 prompt 的证据完整性，但没有改善独立缺陷验收结果。** 两组均失败，不能写成修复成功率提升；更低 Token 也不能直接推广为一般效率优势。单个已研究过的开发任务、每组一次，以及新增 schema/通用提示的工作流干预，均限制结论范围。

这次补丁调用没有被预算预检查阻止。当前失败不能继续统一归因于 Token 不够：既有公开需求涉及的 confirm 未覆盖，也有模型提出了行为等价的修改。前者涉及定位覆盖，后者涉及补丁推理；现有证据不能确定两者各自的因果贡献。

下一步先离线核对公开需求涉及的符号覆盖和生成补丁行为，复用已有诊断方法；随后将定义工具带到跨文件开发任务验证。暂不继续围绕此单例改提示或堆工具，不改变默认 Agent，不修改隐藏验证器。若新增工作流，需要另冻协议；留出任务仍用于最终验证。

## 产物与复现

运行产物 `.tmp/real-defects/definition-patch-v1/`：experiment.json、analysis.json、两组 job、Worker 结果、模型响应、请求、Trace、diff 和父进程 grading 日志。运行产物被 Git 忽略；需单独保留旧 admission 和两个定位 checkpoint。

```powershell
python docs/experiments/definition_patch_v1.py --output .tmp/real-defects/definition-patch-v1-rerun --validate-only
python docs/experiments/definition_patch_v1.py --output .tmp/real-defects/definition-patch-v1-rerun
python -m docs.experiments.definition_patch_analysis_v1 --run .tmp/real-defects/definition-patch-v1-rerun
python -m pytest tests/test_definition_patch.py tests/test_staged_compact_live.py tests/test_staged_replay.py tests/test_definition_localization.py tests/test_definition_read.py -q
```

输出须为新目录。新增四项输入校验测试及相关回归共 **35 passed**，Ruff 通过；真实运行前后均核对冻结输入和模型。未重跑全量测试，未提交 Git commit。
