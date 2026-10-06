# 三项新增真实任务：行块与完整函数修复对照

## 结果与解释

完成 Click 三项策略设计后新增任务的六次真实模型修复。按公开行为契约校正评分后，Python 行块通过 **1/3**，完整函数通过 **2/3**。这是单仓库定向小样本，每项每策略仅运行一次；不能声称稳定提升、统计显著或跨文件/跨仓库泛化。

| 任务 | Python 40 行块 | 完整函数 | 主要证据 |
| --- | --- | --- | --- |
| usage-empty | invalid_patch | failed_verification | 行块未找到 write_usage；函数证据完整，但补丁未处理空参数进入 wrap_text 后丢失前缀的问题 |
| echo-empty-bytes | passed | passed | 两组保留空 bytes 类型，Target 与 Controls 都通过 |
| style-color-validation | invalid_patch | passed（评分 v2） | 行块只含局部片段，替换不合法；函数证据包含 style、secho 和颜色解释函数，修复零色值与异常类型 |

预算超限、模型超时及基础设施错误均 **0/6**。invalid_patch 表示片段替换不满足已有合法性协议，不能记为验证成功。passed 仅代表本批独立 Target/Controls 通过，没有运行完整 Click 上游测试集。

| 策略（各三次原始调用合计） | Prompt Token | Completion Token | 总 Token | Worker 秒 |
| --- | ---: | ---: | ---: | ---: |
| 行块 | 7258 | 512 | 7770 | 26.8941 |
| 完整函数 | 7105 | 1587 | 8692 | 46.7752 |

所有调用均有 usage；Worker 时间包含子进程开销，不等于纯模型推理延迟。v2 重新评分复用原始调用成本，**没有新增模型或 Embedding 调用**。

## 协议与实现

三项源自 `validation-admission-v1.md` 的冻结准入清单。`validation_repair_v1.py` 校验 manifest、公开需求、源码、检查及旧策略摘要，先为全部任务生成证据，再打开 after 快照与私有评分材料。公开任务允许修改整个 src/click Python 包，未把参考修改范围、after 代码或隐藏检查送入模型。

两组沿用既有关键词检索与单次片段补丁协议，仅比较 Python 40 行块与完整函数种子；不追加依赖、工具调用、反馈或重试。固定 Qwen3.5:27b（digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`）、temperature=0、reasoning=none、证据最多 6000 字符、输出最多 2048 Token、总预算 15000 Token、窗口 16000、Worker 600 秒、验证 15 秒。策略运行顺序交错，全部六次保留。

补丁必须匹配展示过的 old 片段、完整文件版本、唯一替换位置和允许范围。父进程在干净副本上执行 Target/Controls；before 目标断言失败、after 与两边 Controls 通过的准入条件重新核验。冻结 corecoder/evals 引擎不变，新增代码位于实验适配层。

## 评分契约修正：保留 v1，单列 v2

原 v1 六次结果为行块 **1/3**、函数 **1/3**。分析颜色任务失败日志后发现：公开需求要求非法颜色抛出 ValueError，隐藏检查额外要求每个异常消息都包含 `Unknown color`。完整函数补丁已抛出正确异常类型，却因 `Palette index...`、`RGB component...` 等文案被判失败。

这是检查超出公开契约。**未修改冻结的 v1 检查、manifest、需求、证据、模型回答或补丁**。新增 `validation_checks_v2` 只移除错误文案子串断言，保留原非法输入、异常类型、零色值及所有 Controls。`validation-scoring-v2.json` 记录修正原因，并绑定旧 manifest、原始结果、证据、六个候选快照及新检查摘要。

`validation_rescore_v2.py` 对全部六个原始候选重新评分，重新核验 before/after 准入；校验候选快照及 patch.diff 未变，并单列 original_status。仅颜色任务的函数分支由 failed_verification 变为 passed。

**v2 是查看模型输出后的评分修正，不是完全预先冻结的验证结果。**两版必须一起报告；后续需要在修正评分已冻结的条件下执行新调用，不能用当前 2/3 替代前瞻验证或推广默认策略。

## 验证与复现

新增测试覆盖公开/私有材料隔离、输入篡改拒绝、全任务先检索后评分、六次交错运行、Controls 失败不能通过，以及异常文案任意、错误异常类型/非法值被接受必须失败。相关测试 **17 passed**；全量 **775 passed、1 skipped（79.88 秒）**。新增 Python 文件 Ruff 与 Git diff 空白检查通过。

```powershell
python -m pytest tests/test_validation_repair.py tests/test_validation_scoring.py -q
python -m pytest tests -q
# 首次新模型调用；输出必须不存在，需已有冻结准入产物和指定 Ollama 模型。
python -m docs.experiments.validation_repair_v1 --output .tmp/real-defects/validation-repair-rerun
# 对绑定的原始六个候选评分，不调用模型；输出必须不存在。
python -m docs.experiments.validation_rescore_v2 --output .tmp/real-defects/validation-rescore-rerun
```

原始调用目录 `.tmp/real-defects/validation-repair-v1` 保存 protocol、observations、experiment、请求、回答、Trace、patch.diff 与评分日志。正式校正结果在 `.tmp/real-defects/validation-rescore-v2-final`；初次评分检查目录 `validation-rescore-v2` 也保留。原始产物受 .gitignore 忽略，需独立归档；重新调用模型后的报告不能冒充绑定原结果的 v2 重新评分。

## 下一步

后续：已实现调用前冻结的 v2 三轮重复协议，新的模型调用与统计独立记录在 [validation-repeat-v2.md](validation-repeat-v2.md)，不与本轮事后校正结果混合。

冻结公开需求一致的 v2 评分协议，以相同三项任务开展新的交错重复运行，分别报告旧调用的事后校正和新调用的前瞻结果。复用任务只能检查本批稳定性；后续外推仍需更多未参与设计的任务。当前不调检索、不增加修复轮数，也不将函数策略推广默认。
