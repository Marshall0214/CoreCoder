# v6/v7 场景检查的重复对照

## 冻结协议

目的：确认上一轮 v7 单试点的场景保留与单独缺陷检出能否重复。v6 仅使用契约对比场景提示；v7 增加契约来源清单、生成 Schema 及形状诊断。比较这组改动的整体效果，不单独归因于 Schema 或某一句提示。

在原 localization-v1/event-replay 上各三轮，按 v6/v7、v7/v6、v6/v7 交错，共六次真实模型运行。共用 Qwen3.5:27b、temperature0、reasoning none、输出2048、累计30000 Token、上下文估计16000、worker180秒/测试15秒；keyword K5、依赖深度2、path排序、6000字符证据与 contract-coverage 初次补丁。每次从干净工作区开始，隐藏验收不反馈模型，失败不挑选重跑。

源码、依赖及任务哈希按已有比较入口冻结；本次运行时实现未修改。源码哈希 `308d26d1409c18783a49c4d0106d053ab6cc3145c6d8af12c8f9ae85dc932c35`，模型 digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。完整配置与顺序见 `.tmp/evals/scenario-manifest-v1-comparison/freeze.json`；批次 completed=true、stop_reason=null。

## 实测结果

| 指标 | v6-scenarios | v7-manifest |
| --- | ---: | ---: |
| 原始任务缺陷检出 | 3/3 | 3/3 |
| 生成/审查有效 | 3/3 | 3/3 |
| 每次保留检查 | 4 | 6 |
| 修复后公开检查通过 | 3/3 | 3/3 |
| 独立验收通过 | 3/3 | 3/3 |
| 模型调用/反馈 | 9 / 0 | 9 / 0 |
| 总 Token | 17,547 | 19,488 |
| 平均端到端耗时 | 44.90秒 | 47.09秒 |
| 中位端到端耗时 | 43.92秒 | 47.21秒 |

v7 的三类生成与保留代码形状均在三轮中观察到，没有用例被状态观察规则过滤；v6 每轮仍有两个读取 state 的跨批次用例被排除，且多租户用例未共享 ID。两组各自三轮的冻结检查哈希完全相同。

三对初次补丁提示、证据清单及模型输出完全相同，修复成功率没有提升。v7 总 Token 多1,941（约11.1%），没有增加调用次数；服务端用量完整，没有超时或预算终止。耗时为本机观察值，部分运行期间同时执行了离线回归测试，未独占计算资源，不解释为严格性能基准。

## 全部冻结检查的事后故障拆分

六份检查分别在四个独立副本上执行，共24次离线重放：原始代码、按公开契约构造的正确实现、只保留全局 ID 去重错误、只保留重复事件提前停止错误。正确行为来自已保存的公开契约回归示例，不使用隐藏测试或参考补丁生成期望。每次核对检查哈希和任务版本；诊断结果不进入模型请求，也不选择或修改冻结检查。

| 实现变体 | v6 冻结检查 | v7 冻结检查 |
| --- | --- | --- |
| 原始代码 | 3/3断言失败 | 3/3断言失败 |
| 公开契约正确实现 | 3/3通过 | 3/3通过 |
| 仅全局 ID 去重错误 | 3/3通过，漏检 | 3/3断言失败 |
| 仅重复事件提前停止错误 | 3/3断言失败 | 3/3断言失败 |

由此得到的有效结论：在这一已用于开发的合成事件任务上，v7 稳定保留了所需场景，并识别了 v6 漏掉的跨租户身份错误。原始任务整体检出不能单独说明所有缺陷均被检出，故障拆分补足了这一诊断。

仍只有一个开发缺陷及两个构造的单独故障；temperature0 下同组输出重复，三个运行不是三个独立缺陷。尚无真实仓库或留出集证据。静态形状及契约 ID 不是语义证明；v7继续作为可选候选，不改变默认策略。本阶段停止在同一事件任务上扩展提示，进入真实历史缺陷任务。

## 复现与验证

比较脚本新增 `--pair v6-v7`，保留原 `v5-v6` 默认值。新事后审计脚本核对完成状态、运行数量、源码版本、检查哈希和路径，并保存各次故障执行、正确行为/审计器哈希与初次补丁配对结果。它不调用模型。

```powershell
python -m pytest tests/test_event_comparison_audit.py -q
python -m pytest tests -q
python -m docs.scripts.compare_event_scenarios --pair v6-v7 --output .tmp/evals/scenario-manifest-v1-comparison-replay
python -m docs.scripts.audit_event_comparison --input .tmp/evals/scenario-manifest-v1-comparison-replay --output .tmp/evals/scenario-manifest-v1-comparison-replay-audit
python -m evals.check_quality --input .tmp/evals/scenario-manifest-v1-comparison-replay --output .tmp/evals/scenario-manifest-v1-comparison-replay-quality
```

新增审计回归7项通过，完整回归 **482 passed、1 skipped**，Ruff与diff检查通过。新增文件属于实验复现和审计，核心运行时与旧任务未修改。

本次证据分别在 `.tmp/evals/scenario-manifest-v1-comparison`、`.tmp/evals/scenario-manifest-v1-comparison-audit/fault-audit.json`、`.tmp/evals/scenario-manifest-v1-comparison-quality`。必须使用新目录复跑；这些原始证据被Git忽略，需要另行备份。

下一步筛选少量公开Python历史缺陷，记录许可证、缺陷前/修复后提交、公开问题描述、独立复现测试和依赖环境；先完成原始失败/已知修复通过的准入，再冻结开发/留出划分。现有合成任务保留为回归集，不再作为泛化成果。
