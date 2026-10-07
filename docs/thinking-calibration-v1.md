# Thinking 开关小型校准 v1

本轮完成四个人工任务的真实配对校准：thinking-off 和 thinking-on 均 **4/4**，没有准确率差异。显式开关在原生接口返回中表现符合预期：off 均无 thinking 内容，on 均有。on 组供应商报告的总 Token 为 off 的 **2.54 倍**，不据此修改默认配置。

| 指标 | thinking-off | thinking-on |
| --- | --- | --- |
| 请求数 / 补丁应用 | 4 / 4 | 4 / 4 |
| 源码加载通过 | 4/4 | 4/4 |
| 独立行为检查与结构约束通过 | 4/4 | 4/4 |
| 供应商报告总 Token | 1,401 | 3,552 |
| 有 thinking 内容的响应 | 0/4 | 4/4 |
| 输出截断 | 0 | 0 |

## 任务与边界

四项人工校准任务分别是：保留 falsey 值的唯一原文替换、修复现有方法且保留类定义、纠正不存在的 typing 属性注解以恢复加载、处理构造 None/省略参数/方法覆盖关系。每项只用一个小型 app.py，提供完整源码；没有 RAG、工具循环、公开反馈或多轮修复。

人工原始代码分别出现目标问题，人工参考修复均通过独立检查，之后才进行模型调用。参考编辑和测试仅留在父进程，Worker 输入白名单为 workspace、description、allowed_files、files、thinking、model、base_url。各候选在干净副本进行结构、加载及行为检查；不能把未应用补丁时仍可加载的原源码计作模型修复。此次八个补丁都已应用，因此表中的三阶段分母一致。

这个简化的 None 任务不等于真实 ItsDangerous 缺陷。结果说明当前模型在这组完整短源码上能输出有效补丁并处理这些基本关系，不能证明真实仓库失败已解决，也不能证明模型具备普遍修复能力。每任务每模式仅一次调用，没有稳定性或统计显著性结论。

## 固定条件与记录

- Ollama 原生 `/api/chat`，qwen3.5:27b；冻结模型 digest、版本、thinking 元数据和模板哈希。
- 两组消息、temperature=0、top_p=0.95、seed=17、num_ctx=16,000、num_predict=2,048 完全相同，仅 think 布尔值不同；四对实际请求已校验。
- 每任务一次调用，预算 15,000 Token；复用既有预算预检查和返回用量检查，不是供应商计费硬上限。
- 记录 done_reason、空最终答复、工具输出、thinking 是否出现及字符数。思考正文不保存、不送回历史。
- 用量为原生 prompt_eval_count + eval_count；没有独立思考/最终答复 Token 拆分。供应商用量未知时不记作零。

本轮只校准原生 think 开关，没有重放旧的流式 `/v1/chat/completions` 请求，不能据此证明旧接口 reasoning_effort 映射已经实际生效。也没有比较官方温度 0.6 等采样组合；若比较温度，必须单独固定 thinking 开关建立新协议。完整协议与结果见 [机器摘要](thinking-calibration-v1.json)。

## 复跑

按 [公开检查报告](repair-public-feedback-v1.md) 设置既有 Conda 环境和 D 盘 TEMP/PYTHONPATH；新输出目录须未存在。

```powershell
python -B -m pytest tests/test_thinking_calibration.py -q -p no:cacheprovider --basetemp .tmp/calibration/thinking-tests-user
python -B -m docs.experiments.thinking_calibration_v1 --output .tmp/calibration/thinking-offline-user
python -B -m docs.experiments.thinking_calibration_v1 --output .tmp/calibration/thinking-live-user --live --repeat 1
```

离线命令不接触模型，使用仓库内人工 fixture，能够仅从 Git 重建。真实命令需本机指定模型 digest 和 Ollama；默认为一次配对，可选 repeat 1–3，但重复不会增加不同任务数。原始报告在 `.tmp/calibration/thinking-v1-live/experiment.json`；参考源码、完整源码副本与日志保留在 D 盘 .tmp，Git 保存摘要。

## 下一步

不把“开启 thinking”当作已验证的修复优化。优先实现编辑事务保护，并离线重放真实失败补丁：检测新增重复定义、模块加载错误、作用域越界及误拒正确补丁，失败不提交候选变更。它能处理已观测的结构和加载问题；默认盐值语义仍需行为验证。历史评分和默认模型配置保持不变。

工程验收：新增校准测试 10 passed；Windows 全量 952 passed、2 skipped（157.53 秒）；Ruff 通过。Linux、容器、HTTP 故障验收本轮未重跑。没有安装依赖或操作已有用户服务；新产物均写 D 盘。
