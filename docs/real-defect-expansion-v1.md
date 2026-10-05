# 真实缺陷开发集扩充 v1

## 目的与边界

此前反复围绕 `click-flag-envvar` 调整证据组织。本次扩充不同缺陷，先验证任务有效性，不调用模型、不报告检索收益。

现有真实开发任务共 7 个：原单文件目录 3 个、跨文件目录 1 个、本次新增 3 个。均来自 Click，存在同仓库和相近版本关联。本次已经审阅上游修复，全部属于开发集，不是留出集或跨仓库泛化证据。新增参考修复均只涉及单个源码文件，不能计为跨文件修复。

## 固定任务

目录：`evals/real_defects/expansion-candidates-v1.json`，包含完整 before/after 提交、公开问题、许可证、修复范围及检查路径。

| 任务 | 需求与来源 | 参考修改文件 |
| --- | --- | --- |
| `click-prompt-suffix` | 空后缀的 prompt/confirm 不应多出空格；[Issue 3019](https://github.com/pallets/click/issues/3019)、[PR 3021](https://github.com/pallets/click/pull/3021) | `src/click/termui.py` |
| `click-invoke-missing` | Context.invoke 缺省可选参数应传 None；[Issue 3066](https://github.com/pallets/click/issues/3066)、[PR 3068](https://github.com/pallets/click/pull/3068) | `src/click/core.py` |
| `click-shared-default` | 共享参数的多个 flag 应使用配置默认值，不受声明顺序影响；[Issue 3071](https://github.com/pallets/click/issues/3071)、[PR 3079](https://github.com/pallets/click/pull/3079) | `src/click/core.py` |

父评测器检查位于 `evals/real_defects/checks/<任务名>/test_admission.py`，不作为模型输入。人工根据公开需求构造断言，并审阅上游补丁；不是未见修复的独立出题流程。

- prompt-suffix：精确检查两种交互输出及返回值；控制检查正常 `: ` 后缀。不覆盖 stderr 分流、隐藏输入或全部终端兼容性。
- invoke-missing：检查字符串/普通可选参数缺省均为 None；控制检查默认值转整数、多值空元组、显式传值及显式 None。
- shared-default：两种声明顺序下默认均为 safe；控制检查显式 quick/safe 覆盖默认。

## 实测准入

证据：`.tmp/real-defects/expansion-admission-v1/admission.json`，保留源码快照、上游元数据、许可证、哈希和日志。旧目录及历史结果未修改。

| 任务 | 原始 Target | 原始 Controls | 修复 Target | 修复 Controls | 准入 |
| --- | --- | --- | --- | --- | --- |
| prompt-suffix | 断言失败 | 通过 | 通过 | 通过 | admitted |
| invoke-missing | 断言失败 | 通过 | 通过 | 通过 | admitted |
| shared-default | 断言失败 | 通过 | 通过 | 通过 | admitted |

每组 1 个 unittest 方法，内部包含多个 subTest 场景，不把子场景计为独立缺陷。原始 Target 均无执行错误或超时。参考通过只表示这些检查通过，不代表上游完整测试套件通过。

解释器：既有 `click-stdlib-env`，Python 3.11.16；colorama、typing_extensions 均未安装。本次未安装依赖。执行时隔离导入固定源码，并验证源码与检查文件未改变。

目录 SHA-256：`afd53fe118f4b544329c6dfc20daad47ad648b07f8a2e582bd990e66b7b7b3c6`。

复现（output 必须为新目录）：

```powershell
python -m evals.real_admission --catalog evals/real_defects/expansion-candidates-v1.json --output .tmp/real-defects/expansion-admission-replay --python .tmp/real-defects/click-stdlib-env/Scripts/python.exe
python -m pytest tests/test_real_admission.py -q
python -m pytest tests -q
```

代码验证：准入回归测试 13 passed；全量 559 passed、1 skipped；新增检查及准入测试通过 Ruff。

## 下一步

统一三个目录的开发任务入口，冻结列表与统一配置，先跑默认策略的混合开发集基线并分类失败，再决定 base/linked 成对比较。特殊 symbol-feedback 流程目前只适用于 envvar，不能直接推广。

另行采集更多跨文件及其他仓库案例后建立留出评测；当前 7 个开发任务不足以证明跨文件策略有效。
