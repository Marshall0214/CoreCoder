# 公开开发检查与一次反馈修复 v1

## 实现与来源

新增 `symbol-feedback` 工作流，用固定公开开发检查验证局部补丁，至多追加一次补丁请求。检查为 `evals/public_click_contract.py` 中人工编写的五个方法，适用范围仅 click-flag-envvar；不是通用模型测试生成能力。

检查对应公开描述中的假值/不匹配值不激活、真值/精确匹配激活、布尔空白值为假，以及保留命令行激活和普通参数转换。变量名 PUBLIC_SHADE_SWITCH / PUBLIC_BOOL_SWITCH、flag_value enabled-shade、测试输入和显式 default=False 均为开发者配置。未激活时保留该默认值是检查中的开发解释，不能当作经过独立验证的完整契约。

`public_contract` 要求公开描述包含适用需求，并记录原文范围。未读取 Target 或修复后源码构造检查；检查仍是已知开发案例上的人工开发资产，不是独立评分器或盲测样本。Trace 明确 semantic_correctness_verified false。实际命令生成、执行和比较过程中，Target 仍仅由父进程持有。

## 执行协议

1. 修复前冻结公开检查代码及摘要，在原始源码副本执行。
2. 采用与 baseline 相同的首轮符号证据与补丁 Prompt，模型不预先收到新检查。
3. 在候选源码的独立副本执行同一检查；仅原始和候选均存在断言失败，且无执行错误/超时，才触发反馈。
4. 反馈只包含冻结公开检查代码及其输出。重新索引当前候选，提供更新后的局部片段与版本；模型最多再返回一次补丁。
5. 有效补丁继续拒绝修改未展示文本、越界路径和过期版本，检查代码不在允许写入范围。公开检查每次执行前后校验冻结摘要；源码在副本中运行。
6. 最终仍由父进程在干净原始副本叠加允许源码修改，运行独立 Target / Controls，决定 accepted。

补丁、检查、错误输出均为独立文件，首轮与反馈响应不互相覆盖。没有第三次修复、重新生成检查或隐藏结果反馈。公开检查通过不等于最终通过；执行错误也不被当作缺陷失败反馈。

工作流协议为 `symbol-feedback-development-v1`，baseline 为 `symbol-patch-development-v1`。两组首次请求证据和配置一致，反馈组获得额外请求和候选上下文，所以比较的是完整工作流收益，不是纯 Prompt 或检索消融。

## 三轮真实模型对照

冻结实现摘要 `9ceebff40043ff7f0c96332bf7a2109f2b0566e3d66288c440ad0081c9a3ae00`，本地模型 manifest 摘要与前次一致。固定 qwen3.5:27b、temperature 0、reasoning_effort none、输出上限 2048 Token、上下文 16000、总预算 30000、墙钟上限 180 秒。证据首轮均为 5764 字符，反馈后依据候选重新索引。

| 工作流 | 独立验收通过 | 模型请求总数 | 总 Token | 平均总耗时 |
| --- | ---: | ---: | ---: | ---: |
| 单请求 baseline | 0/3 | 3 | 11,001 | 14.7332 秒 |
| 公开检查 + 一次反馈 | 0/3 | 6 | 27,779 | 37.6102 秒 |

反馈组三次均满足原始/候选断言失败条件，触发且仅触发一次反馈，两个阶段均产生合法补丁。反馈补丁均修改 core.py 和 types.py，布尔空白值的公开检查通过，但非布尔假值和不匹配值仍激活开关，公开检查最终仍失败。三次独立 Target 均失败；公开 Controls 均通过。

仍失败的补丁继续用 `self.type.convert` 的返回值判定激活；非布尔字符串转换并不等于布尔激活判断。公开断言已暴露该问题，但模型第二次仅增加异常处理，并未更正这一语义。这个结论来自公开检查输出与候选补丁分析，不反馈隐藏验收内容。

总 Token 为 baseline 约 2.53 倍，没有最终成功收益，保持默认单请求流程。同一开发案例的重复运行不是独立任务样本，不能据此推广结论。公开检查促成跨文件改动和部分行为修复，可验证工程闭环，但不能代替最终验收。

报告目录 `.tmp/real-defects/symbol-feedback-v1`，包含 freeze.json、comparison.json、每次补丁响应、冻结公开检查、各阶段独立副本和日志；失败保留，不与原 Prompt 对照成绩合并。

测试：相关 29 passed，全量 546 passed、1 skipped；相关文件 Ruff 通过。覆盖首次成功不重试、无效补丁不重试、失败时仅一次反馈、代码冻结、独立副本执行、比较顺序及固定首轮证据。

## 复现步骤

```powershell
python -m pytest tests/test_symbol_feedback.py tests/test_symbol_prompt_comparison.py tests/test_symbol_patch.py tests/test_real_tasks.py -q
python -m evals.compare_symbol_prompts --axis public-feedback --admission .tmp/real-defects/crossfile-admission-v2/admission.json --repeat 3 --output .tmp/real-defects/symbol-feedback-reproduction
python -m pytest tests -q
```

需要原有准入源码及其隔离 Python、本地 Ollama qwen3.5:27b；输出目录必须是新目录。冻结与身份检查沿用 Prompt 对照入口，默认轴仍为原 symbol-prompt。对照完成与修复成功分别记录。

## 下一步

先根据公开失败检查定位激活判断与字符串转换的调用链信息缺口，离线检查现有证据能否展示类型选择及转换实现。确定补充哪些上下文后，再做独立策略试跑；暂不增加修复轮数，不继续仅靠提示词叠加。公开检查仍属于开发资产，后续必须扩充真实任务并划分开发与留出集。
