# bounded-pipeline-v1：有界证据与结构化修复管线

更新：2026-10-04。新增可执行协议：**固定查询检索 → 限额完整文件与静态依赖 → 单次结构化补丁 → 父进程独立验收**。先建立管线，不将旧 Agent 或全部源码诊断结果视为单项检索因果对照。

## 固定执行规则

`--mode pipeline --search-backend keyword` 启用。查询为原缺陷描述加固定后缀 `contract contracts`，不使用模型改写、参考补丁或相关文件标签。沿用当前 Python/Markdown BM25 索引和排除规则；按排名挑选前 K 个不同文件作为种子，默认 K=5。

按种子顺序接纳完整文件，再以广度优先顺序沿静态 import/from 补充已索引的允许源码。默认最多两层、最多二十文件，全文字符上限沿用 search_max_chars，默认 6,000；文件放不下时记录丢弃，不截断，也不沿该文件继续扩展。字符预算只计正文，JSON 元数据和 Prompt 仍由请求 Token 预检限制。

只解析 AST，不导入或执行仓库模块。支持直接绝对/相对模块映射，限定在允许源码；不处理动态导入、别名包搜索路径或运行期依赖。语法错误文件可作为证据，但不展开导入。循环依赖去重，空文件/排除文件不扩展。种子及依赖哈希须与索引版本一致；每次运行重建任务索引，无跨任务答案记忆。

生成阶段复用固定证据诊断的 JSON 编辑协议，一次逻辑模型调用，无自由工具循环、额外计划、压缩或测试反馈修复。只能修改已提供证据中的允许源码，所有编辑先验证、再按 UTF-8 字节写入；保留 CRLF，忽略无变化编辑。父进程仍检查范围并从原版本重建目标与回归验收目录。

该模式是一个有界工作流，不是拥有反思、恢复或服务持久化的完整产品 Agent。benchmark_eligible=true 仅表示真实模型、可在**同一 bounded-pipeline-v1 协议**内开展对照；报告写明协议，混合 pipeline 与旧 Agent 的汇总不标为共同基准。

## 小样本协议

pagination-cursor 与 lease-lifecycle 各三次，共六次。Qwen3.5:27b、temperature=0、reasoning_effort=none；Token 30,000、输出 2,048、估算上下文 16,000、Worker 180 秒、测试 15 秒。top_k=5、导入深度=2、正文 6,000 字符，不混用 read-cover 或 contract-check。原轮数参数对单请求阶段不生效。

模型运行前按同一规则检查证据构建：分页 5 文件、1,563 字符，租约 8 文件、2,054 字符。没有为这两个任务添加特定查询、文件清单或补丁规则；开发集仍可能影响设计选择，应在扩展任务和留出集复验。

六次用于管线验收，不是策略效果实验；后续只改变一个证据策略，并在共同版本冻结预算、生成提示和评分。只有两个独立人工任务，重复结果不支持真实仓库泛化或统计显著性。

## 实际验收结果

| 任务 | 独立验收 | 每次输入 / 输出 / 总 Token | 模型调用 | 证据 |
| --- | --- | --- | --- | --- |
| pagination-cursor | 0/3，failed_verification | 949 / 174 / 1,123 | 每次 1 次 | 5 文件，1,563 字符 |
| lease-lifecycle | 3/3，passed | 1,338 / 574 / 1,912 | 每次 1 次 | 8 文件，2,054 字符 |

六次均正常完成生成，没有预算终止、基础设施错误或缺失 usage；没有因失败重跑。总计 3/6，但仅两个独立任务，不能解释为真实仓库成功率 50%。源码哈希共同为 `8866d90cd80891b711daf8fc7c69510e61a1dac6813bc6e98839ebe5222007c3`。

分页实际证据顺序为 `docs/paging.md → api.py → paging.py → cursor_codec.py → query.py`，公开契约和两处缺陷文件都已提供，没有预算丢弃。三次仅修复 query.py 的同时间戳比较，未修复 paging.py 用 lookahead 元素生成下一页游标的问题；回归通过，隐藏目标测试 2/4 通过。因此不能将失败归为已知缺陷文件漏召回。

租约证据顺序为 `docs/leases.md → docs/acquisition.md → acquire.py → renew.py → cleanup.py → models.py → lookup.py → expiry.py`，没有预算丢弃。三次均修复 TTL 单位、租户匹配及过期边界，另在 renew.py 添加防御性租户检查；隐藏目标 4/4、回归 2/2 通过。这只是当前测试范围内的正确性证据。

原始报告：`.tmp/evals/bounded-pipeline-v1/pagination-cursor/summary-68257f23ed.json`、`.tmp/evals/bounded-pipeline-v1/lease-lifecycle/summary-e87ce9bbce.json`，同目录有 Markdown 汇总及各次 Trace、补丁、验收输出。测试：针对管线及共享补丁模块 23 passed；完整回归 **299 passed、1 skipped**（Windows 符号链接环境）；修改的 Python 文件 Ruff 检查通过。

此前全部公开证据诊断为 6/6，本次为 3/6，但证据集合、组织顺序及代码版本不同，不能据此估计单项检索收益。下一项先在共同管线版本、相同选中文件及正文下，对照排名/依赖顺序与稳定路径顺序，固定生成提示、预算和评分，验证上下文组织是否影响完整修复；暂不加入更多模型调用或修复机会。

## 复跑

```powershell
python -m pytest tests/test_pipeline.py tests/test_fixed_evidence.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --task pagination-cursor --mode pipeline --search-backend keyword --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/bounded-pipeline-v1/pagination-cursor
python -m evals --suite evals/fixtures/retrieval-overlap-v1 --task lease-lifecycle --mode pipeline --search-backend keyword --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/bounded-pipeline-v1/lease-lifecycle
```

证据选择事件 pipeline_evidence_built 保存查询、索引版本、种子评分、接纳/丢弃理由、深度和字符数。pipeline_patch_request 保存实际证据 manifest，pipeline-response.txt 保存原模型输出，父进程保存补丁、报告和独立测试。新实验使用新目录；产物被 Git 忽略，需要独立备份。
