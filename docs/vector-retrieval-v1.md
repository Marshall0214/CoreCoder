# BM25 / Dense / Hybrid 离线检索 v1

## 目的与交付

在相同代码分块、查询和候选语料下，检查向量检索是否更容易找到参考修复涉及的文件。本轮只测检索，不调用修复 LLM，不改变默认 read-first 或冻结的修复引擎。

- `docs/experiments/vector_retrieval_v1.py`：本地 Ollama Embedding Client、精确余弦向量索引、等权 RRF Hybrid，以及复用原 `search_code` 参数、引用、字符预算和历史去重的可选工具适配器。
- `docs/experiments/vector_retrieval_eval_v1.py`：11 个合成开发任务的固定查询离线评测，保存全部候选排名后才读取参考补丁评分。
- `tests/test_vector_retrieval.py`：向量有效性、维度、模型版本、缓存失效、私有文件排除、工具接口及评分标注隔离测试。

适配器位于实验目录，尚未注册到默认 Agent，也没有新增生产数据库依赖。当前索引是内存中的精确向量扫描，适合小语料验证；不代表已实现向量数据库、ANN 或服务部署。

## 固定协议

| 项目 | 配置 |
| --- | --- |
| 语料 | 原始 fixtures 5 项、localization-v1 5 项、retrieval-overlap-v1 1 项 |
| 分块 | 原 KeywordIndex 的非重叠 40 行；Python 允许文件及公开 Markdown |
| 查询 | `task.description + " contract contracts"`，与现有 pipeline 相同 |
| Embedding 输入 | 文档为 `path + "\n" + content`；查询为上述原文，不额外改写或加 instruction |
| 向量 | qwen3-embedding:0.6b，1024 维；归一化后精确余弦 |
| Hybrid | 两个完整 chunk 排名等权 RRF，常数 60；不以评分标签选择参数 |
| Top-K | 第一处 chunk 出现确定唯一文件排名；K=1/3/5/10，包含 Markdown 文件 |
| 标签 | 参考补丁修改的源文件集合；在所有任务检索观察落盘之后加载 |
| 评分 | 每任务命中文件数 / 标签文件数，再对任务取平均 |

不做后端专属 Query 优化，不添加依赖展开、Reranking、证据装填或补丁生成。保留 chunk 全排名以供后续核对。标签是不完整相关性代理，未修改的依赖文件可能同样必要；本报告 Recall 不是修复成功率。

索引继续沿用原有允许列表、目录排除、符号链接排除及语料大小限制。请求仅允许本地 Ollama，`truncate=false` 防止静默截断；检查返回数量、有限值、非零范数和维度。模型 digest 在使用缓存和新请求时核对；内容缓存仅存在于本次进程内，索引变化时重新取当前 chunk 的向量。

## 实测结果

2026-10-06，本机 Ollama 0.34.3；最终报告 `.tmp/retrieval/vector-v1-final/report.json`。

| 策略 | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 18.18% | 57.58% | 57.58% | 62.12% |
| Dense | 27.27% | 54.55% | 80.30% | 96.97% |
| Hybrid | 27.27% | 59.09% | 80.30% | 96.97% |

@5 的变化集中于 artifact-routing（0→0.5）、job-deadline（0→1）、pagination-cursor（0→1）；其他任务相同。Dense 在 @3 略低于 BM25，不能概括为所有预算均有收益。Hybrid 相对 Dense 的优势只出现在 @3。

最终批次 Embedding：22 个 HTTP 请求、80 条输入、11 次输入缓存命中、4,104 prompt tokens；用量缺失请求为 0。请求耗时合计约 1.45 秒，是模型已热启动后的本机观察，不能外推生产延迟。Hybrid 复用 Dense 的文档和查询向量，报告明确将其计时标为 cached；不能将此时间与冷启动 Dense 直接比较。Embedding Token 单独记账，修复 LLM 调用为 0。早期批次 `.tmp/retrieval/vector-v1` 用于接线验证，未纳入最终性能统计。

冻结标识：

```text
embedding digest: ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d
engine hash:      c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
adapter hash:     340199a5404cc99c4890bf56025c00f2e42e747005d95c67cae1a39874a104e0
evaluator hash:   715fc03cf55a2f8a3a7bcb6d5abda04ca145d2b542382ce6181ff1266f5664dc
```

## 复跑

在 corecoder conda 环境、项目根目录执行，输出目录必须不存在：

```powershell
ollama pull qwen3-embedding:0.6b
python -m pytest tests/test_vector_retrieval.py tests/test_search_code.py tests/test_retrieval_eval.py -q
python -m docs.experiments.vector_retrieval_eval_v1 --output .tmp/retrieval/vector-v1-rerun
```

`observations.json` 是评分前观察；`report.json` 含其 SHA256、模型/代码身份、用量、逐任务评分与全排名。更换 tag 的实际 digest 视为新实验，需重新记录，不能合并。测试与分析保留合成任务的开发集属性。

## 决策与下一步

验证：相关测试 37 passed、1 skipped；全量测试 697 passed、1 skipped；新增文件 Ruff 检查通过。冻结引擎 source hash 与之前一致。

向量检索在小语料中呈现召回收益，保留 Dense/Hybrid 为候选策略；默认修复策略不变。下一步采用固定 read-first 装填和同模型/预算，对这 11 项做 BM25/Dense/Hybrid 修复对照，独立核验补丁并单列检索、Embedding 与修复成本。先验证召回收益能否传递到修复成功，再扩展真实仓库与留出集，不按当前评分继续调参数。

接口与模型资料：[Ollama Embed API](https://docs.ollama.com/api/embed)、[Ollama Qwen3 Embedding 模型](https://ollama.com/library/qwen3-embedding)、[Qwen 官方实现](https://github.com/QwenLM/Qwen3-Embedding)。
