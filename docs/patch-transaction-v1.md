# 编辑事务保护与离线重放 v1

## 做了什么

模型输出仍使用唯一原文片段搜索替换。新增一个可选事务适配器：先在临时副本应用补丁，编译修改后的 Python 文件，检查新增重复定义，再在另一个副本中执行模块加载检查。全部通过才写回目标工作区；写入发生 OSError 时恢复已经写入文件的原始字节。

例如，模型在替换 `Serializer.__init__` 时顺便加入新的 `dumps`，但文件后面原来的 `dumps` 仍存在。原编辑器能成功匹配，Python 也能解析，后面的定义却会覆盖前面的修复。现在这种新增重复定义在写回前被拒绝。`typing.str_bytes` 这类运行时不存在的注解，则由真实模块加载检查发现，而非仅依靠 AST 或编译检查。

这是防止无效编辑污染工作区的保护层，**事务通过不表示缺陷已修复**。公开行为检查与独立评分仍负责验证语义。

## 实现边界

- [事务适配器](experiments/patch_transaction_v1.py)：保留已有证据版本、允许路径和唯一匹配限制；检测修改文件中的新增重复声明。区分 typing overload、property setter/deleter 和条件分支，已有重复定义不会仅因存在而被拒绝。
- [离线重放](experiments/patch_transaction_audit_v1.py)：验证历史实现与源文件哈希，重建第一轮编辑后的状态，再将真实第二轮补丁交给事务适配器。未修改历史输出或评分。
- [回归测试](../tests/test_patch_transaction.py)：16 项，覆盖错误语法、非法顶层 return、导入故障、新增重复定义、合法声明、导入修改文件、非唯一匹配、过期证据、双文件写入失败回滚及提交前源文件变化。

导入配置由调用方提供并检查模块来源。检查进程使用隔离 Python 启动参数、清理后的环境和超时，模型不提供检查脚本。只检查所配置模块的实际加载，不保证覆盖所有模块或运行时路径。重复定义检测是保守的静态诊断，不是完整 Python 名称绑定分析；刻意新增的同名覆盖也可能被拒绝。

调用方必须独占一个可丢弃的工作区。提交前会复查原始文件，阻止已发生的源文件变化；没有文件锁，不能消除检查后的并发竞争。逐文件写回并在写入异常时尝试回滚，**不保证进程崩溃、多进程并发或磁盘故障下的跨文件原子性**。模块加载也不是 OS 沙箱。适配器尚未接入默认服务或修改冻结引擎。

## 本轮结果

| 重放集合 | 结果 | 含义 |
| --- | --- | --- |
| 同一真实缺陷的 6 个历史失败补丁 | 拦截 4/6，均为新增重复定义；拒绝后原工作区字节不变 | 验证已知结构故障的拦截能力，不是 6 个独立缺陷 |
| 剩余 2 个历史失败补丁 | 事务通过，但公开盐值检查均失败，各实际执行 11 个测试方法 | 导入与结构正确仍可能有默认值/覆盖语义错误 |
| 人工认证的真实正确补丁 | 1/1 事务与行为检查通过 | 真实任务正例 |
| 之前校准中的成功模型补丁 | 8/8 事务与行为检查通过，来自 4 个合成任务、两种 thinking 配置 | 在这一小组已知正例中未发现误拒 |

本轮新增模型调用 **0**。没有重新估计真实修复成功率，没有证明模型生成质量提高；历史模型调用和修复评分保持原样。历史带注解错误的补丁先因重复定义被拒绝，未进入导入阶段；独立导入错误用例由回归测试验证，不重复计作历史拦截。

原始记录：`.tmp/real-defects/patch-transaction-v1-certified/audit.json`。每个分支保留 `transaction.json`、staging 副本，以及实际执行阶段的导入或公开检查日志。前两次开发运行分别因重放字段适配错误中断、以及修改前版本被后续认证替代，不能与正式记录合并。

完整机器摘要见 [patch-transaction-v1.json](patch-transaction-v1.json)。临时目录不进入 Git；复跑历史重放需要已经冻结的真实任务快照及 `.tmp/real-defects/salt-relations-feedback-v1`、`.tmp/calibration/thinking-v1-live` 原始记录。新 clone 可以直接运行事务单元测试，不需模型或历史实验产物。

## 复跑

在项目根目录、已有 corecoder Conda 环境中执行；临时文件继续放 D 盘：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_patch_transaction.py -q -p no:cacheprovider --basetemp .tmp/pytest-patch-transaction-rerun
python -B -m docs.experiments.patch_transaction_audit_v1 --output .tmp/real-defects/patch-transaction-rerun
```

输出和 pytest 临时目录使用全新名称，避免覆盖冻结证据。下一步可将事务拒绝原因作为有界编辑反馈开展独立对照；继续保留两次调用上限、Token 预算和独立评分，不靠无限重试宣称收益。

## 工程验收

事务专项测试 16 passed，Ruff、文档链接及 33 项冻结输入哈希检查通过。第一轮全量为 967 passed、1 failed、2 skipped：旧取消测试在查询子进程状态时遇到进程已退出的竞态。统一修正四处测试断言，捕获 NoSuchProcess，并补充三项确定性测试；仍拒绝存活进程，服务运行时不变。最终 Windows 全量 **971 passed、2 skipped（152.58 秒）**。本轮未重跑 Linux、Docker 或真实 HTTP 验收。
