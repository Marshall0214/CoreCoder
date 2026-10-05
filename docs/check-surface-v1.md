# 公开检查的观察边界与生成一致性

## 问题与改动

完整工作流对照暴露两项问题：路由检查使用禁止导入的 dataclasses；事件审查接受 seen 集合必须含裸字符串 ID 的断言，正确补丁使用租户和 ID 的组合后反而失败。引用有效、JSON 合规和算术一致不能证明期望具有契约支持。

新增可选 `--public-check-policy contract-surface`，协议为 `public-contract-feedback-v5-surface`。保留 v4 的契约目录、接口视图、JSON Schema 和算术校验，在模型审查后加入确定性的 AST 观察边界过滤：追踪传给导入 API 的参数名称及直接/派生赋值别名，发现断言读取这些名称时排除整个测试方法。保留模型原判、观察名称和排除理由，不改写断言。若无检查保留，关闭反馈，仍执行初次补丁和父进程独立验收。

这是主动收窄检查范围，而不是自动证明契约支持。即使契约规定了参数修改，这个策略也会保守排除；API 返回值可检查，API 结果随后成为另一调用的参数时也可能被排除。它只覆盖简单生成代码，不是完整 Python 数据流分析：辅助函数、动态别名、跨方法状态和返回对象的内部表示仍可能绕过限制。应通过返回结果及多次调用的公开行为验证去重，不能据此宣称所有语义误判已解决。

新版本生成提示要求使用公开 API 返回值，避免窥探去重集合等状态；需要辅助对象时使用普通 Python 类，不导入 dataclasses/types。导入验证规则没有放宽，生成违规仍保留失败记录。旧策略的提示、默认配置和上一轮冻结结果保留。

## 验证

最终离线回归：431 passed、1 skipped。新增 15 项测试覆盖参数/别名/关键字参数过滤、返回值保留、整方法排除、违规导入、Schema 调用及 coverage/feedback 协议兼容。其中一项可选审计读取本地原始事件检查；缺少实验目录时跳过，独立的构造案例仍验证相同错误。Ruff 与 diff 检查通过。

首轮 CLI 启动因新增策略遗漏报告协议映射而在模型调用前报错，没有得到试点结果；已补齐 runner 和结构化补丁的协议映射，另用新目录执行最终试点。

```powershell
python -m pytest tests/test_check_surface.py tests/test_review_schema.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode contract-feedback --task artifact-routing --task event-replay --task pagination-cursor --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --public-check-policy contract-surface --output .tmp/evals/check-surface-v1-replay
```

最终原始结果在 `.tmp/evals/check-surface-v1-pilot-final/summary-d92f37725b.json`，三个 report 的共同源码哈希为 `c8c58cd1207aea2440933b04c7b27c35ed8ed7a50abe8e2aecea80c58c28542a`。模型和预算沿用上次配置，每任务仅一次，不是完整批次对照。目录被 Git 忽略，需要单独备份。

| 任务 | 生成/审查 | 保留检查 | 过滤 | 反馈次数 | 最终公开检查 | 独立验收 | Token |
| --- | --- | ---: | --- | ---: | --- | --- | ---: |
| artifact-routing | 有效/有效 | 6 | 无 | 1 | 失败 | 通过 | 7,463 |
| event-replay | 有效/有效 | 5 | 1 项直接读取 state 的重放测试 | 0 | 通过 | 通过 | 5,388 |
| pagination-cursor | 有效/有效 | 5 | 1 项观察再次传入 API 的 cursor/page2 的测试 | 1 | 通过 | 通过 | 9,080 |

总 Token 为 21,931，独立验收 3/3，最终公开检查 2/3。生成未再使用 dataclasses；事件检查未再要求 seen 的裸字符串表示。分页仍能通过保留检查触发一次反馈并修复。新提示改变了生成的检查集合，因此不能把所有变化归因于 AST 过滤，也不能用此试点宣称成本降低或成功率提升。

## 保留的问题与下一步

路由最终失败的是 `a/../a/b.txt` 应匹配 `a/./b.txt` 的断言。公开契约仅说 dot segments 被规范化，没有明确区分 `.` 与 `..`；现有实现处理 `.`，独立验收也没有裁决 `..`。这既可能是生成检查扩大契约，也可能是任务规格/验收覆盖不足，不能仅因独立验收通过就判定检查错误。本次不改任务契约、不删除失败断言，不将额外反馈记成验证收益。

事件保留检查在原始缺陷代码上全部通过，说明虽然避免了已知状态表示误断言，其缺陷识别能力仍不足。分页过滤也体现了保守策略的覆盖代价。当前仍不推广为默认策略。

下一步先建立检查质量诊断：原始缺陷检测、独立通过补丁上的冲突和契约歧义分别报告；使用这些父进程诊断评价检查，不能据隐藏测试筛选检查或反馈给模型。对 `.`/`..` 另建明确规格的新版本任务，保留 localization-v1；随后再做按需验证成本实验和真实缺陷留出集验证。
