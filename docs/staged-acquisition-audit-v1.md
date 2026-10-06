# prompt 定义获取缺口审计 v1

## 结论

`prompt` 尾部 9 行的缺失由当前定位路径造成：种子装填未收录该函数，模型随后请求了不足以覆盖完整定义的 100 行，又重复读取已有片段，最后定位预算耗尽。**不是 read_file 的 120 行硬上限截掉了这 9 行。**

本轮重放原种子构建和两次读取，结果与冻结产物一致。按 AST 完整定义请求 109 行，现有工具可以返回全部内容，未提高任何上限。没有发起模型调用、真实定位任务或评分器调用。

## 来源链

公开任务描述明确提及 `prompt` 和 `confirm`；原始 `termui.py` 的 AST 将 `prompt` 定位为 83–191 行，共 109 行。审计只访问该任务 before 源码、原检查点和定位 Trace，不读取隐藏测试、参考补丁或 after 源码。

1. **种子预算排除。** 该函数出现在排名种子中，但 `dependency-reserve` 的种子字符额度为 3,000。它被处理时，剩余额度仅 453 字符，降级窗口仍需 1,212 字符，因此被丢弃。1,212 是降级窗口的大小，不是完整函数大小。离线重建得到完全相同的种子池、选择及丢弃记录。
2. **探索请求只覆盖 100 行。** Trace sequence 17 请求 `offset=83, limit=100`，sequence 18 返回 83–182 行，共 100 行、4,439 字符，并提示 next offset 183。工具按请求返回，没有触发 120 行限制。
3. **再次读取没有新增源码。** sequence 24 请求 `offset=136, limit=20`，sequence 25 返回 136–155 行，共 20 行、1,075 字符；20 行全部已在第一次读取中出现。
4. **定位停止。** 三次探索模型调用消耗 11,686 Token，12,000 阶段预算只剩 314。下一次请求预估 5,022 Token，预检以 `minimum_output_preflight` 停止；183–191 行没有进入 reads 或 seeds。阶段停止后仍有补丁预算，但定位阶段没有继续读取权限。

重复读取增加了当前对话内容，但不能仅凭其字符数计算“若删掉重复读取就一定能完成定位”的反事实 Token 用量。改变读取会改变后续模型请求和响应，须另做实验。

## 原工具下的定义读取复放

| 请求 | 返回范围 | 返回行数 | 含编号及 footer 的字符数 |
| --- | --- | ---: | ---: |
| 原请求：offset 83，limit 100 | 83–182 | 100 | 4,439 |
| AST 定义请求：offset 83，limit 109 | 83–191 | 109 | 4,806 |

109 行小于原工具 120 行上限，4,806 字符小于其返回上限；全部行逐行核对原源码。新读取仍有文件级分页 footer，但完整函数本身已经读完。这说明需要区分“文件还有后续行”和“当前符号是否完整”。

这只是离线工具可行性验证：没有将新片段插入旧检查点，没有发起新修复请求，不宣称 Token 或成功率改善。完整 prompt 与 confirm 仍竞争原 6,000 字符装填预算，读取补全不会自动解决装填和行为契约问题。

## 下一步

实现独立、可选的定义边界读取原型：通过允许源码的 AST 解析公开符号，返回定义范围、实际展示范围、是否完整及下一偏移。定义能在原 120 行和字符限制内容纳时一次读取完整范围；超限时明确标记不完整并提供继续位置。不得写死本任务 83 行或 109 行，不删文档，不增加工具权限及预算。

先用离线案例核对完整定义、超长定义、重载/嵌套符号、语法错误和返回范围，再冻结新的定位实验协议。旧检查点保持原样，后续新候选池的结果与旧装填对照分别报告。保留 read-first 默认；补齐代码不能替代对正常行为的理解和独立验收。

## 复现与测试

```powershell
python docs/experiments/staged_acquisition_audit_v1.py --source-root .tmp/real-defects/expansion-admission-v1/click-prompt-suffix/before --output .tmp/real-defects/staged-acquisition-audit-v1-rerun
python -m pytest tests/test_staged_acquisition_audit.py tests/test_staged_containment_packing.py tests/test_staged_failure_audit.py tests/test_staged_compact_live.py tests/test_staged_compact_packing.py tests/test_staged_evidence_coverage.py tests/test_staged_replay.py tests/test_staged_repair.py -q
```

输出须为新目录；需要保留原 before 源码、检查点及 Trace。产物 `.tmp/real-defects/staged-acquisition-audit-v1/` 包含 `audit.json`、`seed-replay.jsonl` 和 `definition-read.txt`，保存原输入和脚本 SHA、逐请求来源及离线重放结果，被 Git 忽略。

新增 6 项测试及相关回归共 **54 passed**，Ruff 通过。覆盖请求范围、重复读取、footer 排除、CRLF 原文、伪造/不连续行拒绝、AST 尾部范围和未配对事件拒绝。未修改原修复实现和冻结协议，未重跑全量测试。
