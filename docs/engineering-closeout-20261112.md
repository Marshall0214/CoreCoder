# Issue 服务工程收尾验收

2026-11-12：限定范围内验收完成，随本次提交冻结本地演示版本。此前工作检查点为 `a3da476`；本记录、实现、测试和机器收据属于同一收尾提交，不包含远程推送。

## 交付内容

- `feedback-actions-v2` 接入 CLI/API 共享执行入口，旧任务继续使用原执行策略。管理员固定执行配置和输入哈希，HTTP 调用者不能临时扩权。
- 首轮探索与反馈读写共用响应提供者；反馈阶段可重新读代码、提交唯一原文锚点补丁并运行公开检查。默认分别允许 20 次探索请求和 20 次反馈请求，各阶段最多 1200 秒；服务总超时仍可进一步限制，不设置累计 Token 截止。
- 公开通过且有有效修改才进入 `ready_for_review`。产品报告保持 `accepted=false`、独立验收不可用，公开检查和基准独立评分分离。
- 统一服务任务与验证容器的归属；取消、超时、中断保留已有报告与候选制品，不沿用先前成功状态。审批恢复、幂等、重复批准和拒绝沿用原服务机制。
- 固定准入镜像的不可变 ID，传入验证子进程；环境变量不能替换镜像，回执缺少或改变镜像身份时拒绝接受结果。
- 新增自包含 `demo-feedback` 命令，使用明确标注的合成任务与录制响应，真实执行工具、补丁与 Docker。无需下载仓库、启动模型或调用付费 API。
- Langfuse 录制响应使用 Span；回读检查兼容 `timed_out` 布尔摘要，继续拒绝代码、原始日志及其他类型混入摘要。

## 最终验收

| 项目 | 最终结果 | 证据 |
| --- | --- | --- |
| 相关离线回归 | 218 passed，0 skipped；85.71 秒 | `unit-final.xml` |
| 真实 Docker | 4 passed；85.96 秒 | `docker-final.xml` |
| 改动 Python 静态检查 | Ruff 通过 | 本地 `ruff-final-output.txt` |
| 全新公开命令 | 退出码 0，CLI/API 同 Diff、同公开结果 | `product-demo-final/demo/acceptance.json` |
| 审批与交付 | 审批前零执行；待审重启恢复；幂等、重复批准不重跑、拒绝不执行；SSE/制品可读 | 同一演示收据 |
| 生命周期 | 未解决、运行取消、超时保留部分证据；只清理本任务容器，其他哨兵容器保持运行 | Docker 与生命周期测试 |
| Langfuse | 两条 Trace 各 15 个完整操作；每条 6 个录制 Span、0 个 Generation；节点、结束状态、计数和评分回读通过 | `langfuse-product-demo-final-receipt.json` |
| 清理 | 已记录任务归属的容器残留 0 | 机器收据 `cleanup` |

这是 **218 项相关回归加 4 项容器验收**，没有运行全仓库测试集或模型修复率实验。最终四项 Docker 是同一批次全部通过；早期失败与重试另存，未删改为首次成功。

原始本地证据根目录：`D:\project_other\CoreCoder\.tmp\engineering-closeout-20261112`。冻结的测试 XML 位于 [验收附件](engineering-closeout-20261112/unit-final.xml)及 [Docker 附件](engineering-closeout-20261112/docker-final.xml)。[机器收据](engineering-closeout-20261112.json)保存最终演示、Langfuse 回执、输入/实现哈希、实际依赖版本及镜像身份。

### 完整修正链路

CLI 和 API 各消费 6 条录制响应：首轮探索结束，反馈阶段 5 次请求、3 次读取、2 次有效修改，实际公开验证 3 次：

| 候选 | Reproduce | Preserve |
| --- | --- | --- |
| 初始未修改候选 | 失败 | 通过 |
| 第一次错误修改 | 失败 | 通过 |
| 读取依赖后再次修改 | 通过 | 通过 |

两次执行均为真实模型调用 **0**、独立验收 **false**。该结果证明执行和交付链路可用，不证明模型能够自主修复此任务。

最终本地 Langfuse Trace：[CLI](http://127.0.0.1:3300/project/corecoder-issues/traces/2abe5fca7bc1eadd140c8f1bb3f8ec0f)、[API](http://127.0.0.1:3300/project/corecoder-issues/traces/4ec5f595b6eadf5395739dab4ace368b)。服务器存储与原始本地提交状态分开记录；没有把 `submitted_unconfirmed` 文件改写成首次提交即确认。

## 复现入口

依赖与全部 D 盘环境设置见[操作指南](issue-feedback-service.md)。镜像须事先存在，命令不隐式拉取；输出必须使用新目录。

```powershell
python -B -m repairflow demo-feedback --output .tmp/feedback-demo-002
```

启用本地 Langfuse 后，可对自己的新演示回读，不能拿历史 Trace 代替本次运行：

```powershell
python -B -m deploy.langfuse.verify --demo .tmp/feedback-demo-002/demo --env-file .tmp/langfuse-local/.env --output .tmp/feedback-demo-002-receipt.json --timeout 45
```

本次相关回归命令如下；环境沿用操作指南，`CORECODER_RUN_DOCKER_TESTS=0`。`--basetemp` 必须使用专门的新测试目录，pytest 会管理该目录。

```powershell
python -B -m pytest tests/test_issue_feedback_adapter.py tests/test_issue_feedback_demo.py tests/test_issue_feedback_lifecycle.py tests/test_issue_demo_fixture.py tests/test_issue_repair.py tests/test_issue_agent.py tests/test_issue_product.py tests/test_workflow.py tests/test_workflow_approval.py tests/test_feedback_repair_v2.py tests/test_feedback_validator_worker.py tests/test_service.py tests/test_service_persistence.py tests/test_langfuse_receipt.py tests/test_core.py::test_readme_line_counts_are_current -q --basetemp .tmp/closeout-unit-002 -o cache_dir=.tmp/closeout-pytest-cache
```

```powershell
$env:CORECODER_RUN_DOCKER_TESTS='1'
$env:CORECODER_TEST_BACKEND='docker'
python -B -m pytest tests/test_issue_feedback_docker.py -q --basetemp .tmp/closeout-docker-002 -o cache_dir=.tmp/closeout-pytest-cache
```

## 已保留的问题与边界

最初容器批次为 3 通过、1 个测试断言失败：容器状态实际返回 bytes，断言使用了字符串。修正断言后单项通过，最终四项再次全部通过。首次 Langfuse 回读被旧检查器拒绝，原因是新增的 `timed_out` 布尔字段不在摘要白名单；补定向测试后完成真实服务器回读。原输出仍保存在本地证据目录。

仅支持管理员登记的 Python 任务；不提供任意仓库任意命令执行、自动 Git 提交或 PR 合并。服务重启恢复待审批任务，运行中断任务标记 `interrupted`，不自动续跑推理。容器使用既定资源、网络与权限约束，本地服务不代表多租户生产隔离已验收。

四个已知本地模型失败未在本轮修复。之前本地五项独立验收 **1/5** 与历史 DeepSeek **47/50** 仍属于不同协议，不能与本轮录制演示合并成准确率结论。本阶段到此结束；后续算法或生产化工作另立目标。
