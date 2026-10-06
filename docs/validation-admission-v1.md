# 新真实任务批次：准入与冻结 v1

## 本轮交付

为未参与前七项任务策略设计的三个 Click 历史缺陷建立候选清单、独立 Target/Controls、准入器和冻结清单。本轮只验证任务真实性与评分条件，**修复调用 0、Embedding 调用 0**，没有新模型成功率结果。

候选在调用模型前固定，不随机采样：按格式化、二进制输出、颜色校验三个行为维度选取可用标准库独立复现的已合并缺陷。要求公开报告、完整 before/after 提交摘要、修复版本为 before 的直接后继、源码修改范围可核验、许可符合 BSD-3-Clause、与七项开发任务的 ID 和修复提交无重合。全部候选及排除原因保留，不以模型成败替换任务。

| 新任务 | 公开来源 | 行为要求 | 修改范围 |
| --- | --- | --- | --- |
| click-usage-empty | [PR 3434](https://github.com/pallets/click/pull/3434)、[issue 3360](https://github.com/pallets/click/issues/3360) | 没有参数时仍显示 usage 前缀与程序名，不产生多余空格或空行 | formatting.py |
| click-echo-empty-bytes | [PR 3493](https://github.com/pallets/click/pull/3493)、[issue 3487](https://github.com/pallets/click/issues/3487) | 空 bytes/bytearray 写入二进制流时能正确追加换行 | utils.py |
| click-style-color-validation | [PR 3677](https://github.com/pallets/click/pull/3677) | 保留 fg/bg 索引 0，非法颜色统一报 ValueError | termui.py |

构建者查看了公开报告和上游修复来构建评分检查，没有据此调整现有检索、Prompt 或补丁策略。源码与参考修复遵循上游 BSD-3-Clause 许可；这里的 unittest 检查为独立编写的行为复现，来源在各文件注释记录。

## 准入结果

使用既有隔离标准库解释器 `.tmp/real-defects/click-stdlib-env/Scripts/python.exe`，没有安装依赖或修改 conda 环境。每次以 `-I -B` 启动，确认导入来自对应源码快照，清理继承的模型凭据与 Python 导入配置。

| 任务 | before Target | before Controls | after Target | after Controls | 结果 |
| --- | --- | --- | --- | --- | --- |
| usage-empty | 断言失败，2 项 | 通过，2 项 | 通过，2 项 | 通过，2 项 | admitted |
| echo-empty-bytes | 断言失败，1 项 | 通过，2 项 | 通过，1 项 | 通过，2 项 | admitted |
| style-color-validation | 断言失败，3 项 | 通过，2 项 | 通过，3 项 | 通过，2 项 | admitted |

三项均通过。合计每个版本运行 6 项 Target、6 项 Controls，包含额外子场景；没有超时、空测试或环境执行错误。六份源码快照及三份检查在执行后摘要不变。

Target 覆盖公开缺陷，Controls 保护正常参数、文本/二进制输出、None 与对象转换、普通颜色/RGB、reset 和禁用颜色等行为。空 bytes 引发的已知 TypeError，以及非法颜色引发的已知错误类型，被显式转为“违反公开行为要求”的断言失败；未捕获的导入和环境错误仍标记 execution_error，不因异常本身而准入。

## 文件与隔离边界

- `docs/experiments/validation-candidates-v1.json`：完整候选、来源、提交、选择规则及公开需求，父进程使用。
- `docs/experiments/validation_checks_v1/`：三套独立 Target/Controls。
- `docs/experiments/validation_admission_v1.py`：复用既有下载、解压、隔离执行及快照校验；保留每个候选的准入结果与排除原因。
- `docs/experiments/validation-public-tasks-v1.json`：未来检索与模型任务的公开输入，仅含任务 ID、仓库、before 提交、需求和允许文件。允许整个 src/click Python 包，不泄漏参考修改范围。
- `docs/experiments/validation-suite-v1.json`：固定三项、候选/检查/公开投影摘要、源码树摘要及原策略身份；尚未运行模型修复。

冻结 corecoder/evals 引擎不变。评分输入与公开模型输入分开，未来运行器必须校验 manifest 并使用公开投影，不能将完整候选清单或上游 patch 直接送入模型。

## 身份、验证与复跑

```text
engine:   c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
catalog:  9b0a8f75f7b59c144d051d66356447dd9769a15bb072c7cb624be7712a1cb1b2
checks:   378ec821925c9d52b9d26b85c9901987ac37cf233f5b6b8563360938c5d14557
public:   abf6f27db13704d28fb62e053ffe0638a1e2a53c4af837fdec145c25819f49d8
manifest: 3dbed44448ed8af27f27f1a8f9569efba1af0343c2b237d3d7901cfadbf0dc8a
adapter:  24e95d3ebe5eb1669a94cf38a8ca10dd3bf3cc08e513ddd535d792ef73dafb6b
```

最终证据 `.tmp/real-defects/validation-admission-v1-final` 保存 GitHub 提交元数据、源代码归档、before/after 快照、许可摘要、测试环境和日志。初次验证目录 `.tmp/real-defects/validation-admission-v1` 保留；最终 manifest 绑定 final 报告。原始产物受 .gitignore 忽略，需另行归档。复跑报告的环境路径、时延和报告 SHA 可能不同，不覆盖原记录；提交、源码树、检查和候选身份应一致。

全量回归 **756 passed、1 skipped**；随后补充清单与公开投影校验，最终相关测试 **12 passed**；新增文件 Ruff 和 Git diff 空白检查通过。

```powershell
python -m pytest tests/test_validation_admission.py -q
python -m docs.experiments.validation_admission_v1 --output .tmp/real-defects/validation-admission-rerun --python .tmp/real-defects/click-stdlib-env/Scripts/python.exe
```

输出目录须不存在，需要网络访问 GitHub API 与源码归档服务；准入失败会保留原因并返回非零退出码，不表示模型修复失败。

## 下一步与限制

后续记录：六次真实模型修复与评分契约版本修正已完成，详见 [validation-repair-v1.md](validation-repair-v1.md)。本文件及冻结 v1 manifest 的“尚未运行”描述记录准入时状态；冻结文件未覆盖。颜色检查 v1 含超出公开需求的错误文案约束，后续报告保留 v1 结果并单列 v2 校正。

下一步校验冻结清单、从公开投影生成 Python 行块与直接函数证据，在相同模型、6,000 字符预算和单次片段补丁协议下完成六次新修复对照。三项全部保留，不能根据覆盖或模型成败筛掉不利任务，不能用参考修改位置选择证据。策略冻结后仍须分别记录检索、补丁合法性和 Target/Controls 结果。

这是**同一仓库内、策略设计后新增的验证批次**，构建者知道参考修复，模型预训练是否见过这些缺陷未知。三项为定向选择的单文件修复，不是随机样本、跨仓库泛化、跨文件修复基准或绝对盲测。若未来用这三项调参，应将其转为开发任务，另补未参与设计的验证任务；本轮不宣称修复效果提高。
