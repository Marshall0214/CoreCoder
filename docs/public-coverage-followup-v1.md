# 公开需求覆盖诊断：定位获取与证据装填

## 本轮目的与实现

复用已有公开名字/AST 诊断方法，对 prompt 两组新 checkpoint 和历史跨文件 `click-flag-envvar` checkpoint 离线分析。新增 `docs/experiments/public_coverage_followup_v1.py`，区分阅读 receipts、候选池（reads + seeds）和最终 read-first 证据，返回各层缺失区间，并分类为 acquisition、packing、mixed 或 none。

公开名字来源仍是公开描述中的下划线/限定名字；prompt/confirm 是此前已声明且在公开描述中原样出现的 bare names。它们不是隐藏修复位置。对 prompt 两组，重新装填的 fragments 与真实补丁请求逐项比对，避免只诊断一个并未发给模型的模拟输入。

输入及诊断脚本 SHA 记录在 `public_coverage_followup_v1.json`；校验冻结 checkpoint、配置、源码版本和候选原文。只读 before 源码与公开描述，不读 Target、after 或参考补丁，不调用模型，不改旧协议或引擎。

## 关键发现

| 对象 | baseline 候选池 / 模型可见 | definition 候选池 / 模型可见 | 缺口所在 |
| --- | --- | --- | --- |
| prompt（109 行） | 100 / 100 行 | 109 / 109 行 | baseline 为获取缺口；definition 已完整 |
| confirm（59 行） | 59 / 0 行 | 59 / 0 行 | 两组均为装填缺口 |

**confirm 已被种子检索完整获取，却没有进入补丁提示。** 上轮报告所说“证据缺少 confirm”是指最终可见证据，不能进一步解释为未找到实现。read-first 排序下先选 prompt，再选其他片段；confirm 的 2,071 字符因为剩余容量不足被丢弃。

定义组完整 prompt 为 4,287 字符，完整 confirm 为 2,071 字符，合计 **6,358**，已经超过 6,000 字符证据预算，尚未计入其他依赖。即使仅去掉重复片段或调整顺序，也不能同时装下这两个完整函数。需要明确管理原文片段的取舍，而非继续把问题归为读取工具或模型额度不够。

两组最终选中 5,473 / 5,172 字符；不满 6,000 并不表示能放入剩余完整候选，原装填按完整片段接受或丢弃。多展示 confirm 是否会改善修复尚未验证；此前等价补丁也表明上下文覆盖不是唯一问题。

## 跨文件任务诊断与限制

历史 `click-flag-envvar` checkpoint 的公开描述明确包含 `flag_value`，可解析出 14 处 AST 标识符锚点，全部在 core.py；候选池和可见证据覆盖 9 处，5 处未获取，没有额外装填丢失。

这不是“任务覆盖率 9/14”。公开自然语言里的布尔转换需求没有写出 types.py 中具体 API 名字，因此字面锚点方法无法衡量该依赖。没有 types.py 锚点不代表没有跨文件关系；14 处出现也不都是必要修复位置。该历史 checkpoint 与新 prompt 两组不是同一对照，不能比较收益。

跨文件试验应保留 `click-flag-envvar` 的公开自然语言任务，让 Agent 自行搜索、识别符号并使用可选定义工具；不把审查时看到的未覆盖行、上游改动文件或隐藏验证位置预置为模型目标。完整工具干预仍使用新的成对协议，而非改写历史 checkpoint。

## 下一步调整

新增完整定义阅读已经解决了 prompt 的获取缺口，继续围绕同例重复读取无法解决 confirm 被装填排除的问题。下一步先实现独立的预算分配原型：从冻结候选池选择带真实行号的原文区间，报告公开锚点可见性、遗漏范围与取舍；固定 6,000 字符，不伪造连续源码、不自动删除文档或扩大额度。先离线核对覆盖和编辑来源，再决定是否值得调用模型。词面锚点仅作诊断指标，不充当“充分上下文”证明。

随后在跨文件开发任务跑 baseline/可选定义工具的完整定位与修复闭环，观察是否识别类型转换依赖；仍通过独立 Target/Controls 验证。当前未增加模型运行，也未取得新的修复成功率结论。

## 验证与产物

五项新增测试及原覆盖诊断回归共 **10 passed**，Ruff 通过。覆盖不连续缺失区间、完整候选被装填丢弃、获取与装填缺口共存、词面覆盖限制及禁止添加公开描述外 bare names。未运行全量测试。

最终产物 `.tmp/real-defects/public-coverage-followup-v1-final/coverage.json`，被 Git 忽略。初稿输出仍保留，最终版新增 mixed 分类，不修改既有模型输入或评分。

```powershell
python docs/experiments/public_coverage_followup_v1.py --output .tmp/real-defects/public-coverage-followup-v1-rerun
python -m pytest tests/test_public_coverage_followup.py tests/test_staged_evidence_coverage.py -q
```
