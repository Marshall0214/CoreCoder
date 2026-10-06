# 第二仓库 ItsDangerous：三项真实任务准入

## 已完成的工作

从 Click 扩展到 ItsDangerous，构建并冻结三个历史行为缺陷。三项均满足：before 的 Target 为断言失败且无执行 ERROR；after 的 Target 全部通过；Controls 在 before 和 after 都通过。每项两个 Target、两个 Controls。本轮 **0 次模型修复、0 次 Embedding、0 次依赖安装**，不报告修复成功率。

| 任务 | 公开需求与来源 | 上游修改的源文件 |
| --- | --- | --- |
| itsdangerous-none-salt | Serializer/Signer 接受 salt=None，兼容 Signer 默认盐值及签名；[issue 237](https://github.com/pallets/itsdangerous/issues/237) | serializer.py、signer.py |
| itsdangerous-future-age | 指定 max_age 时拒绝未来时间戳，保留时间边界与无 max_age 行为；[issue 126](https://github.com/pallets/itsdangerous/issues/126) | timed.py |
| itsdangerous-malformed-time | 非法签名且时间戳超出日期范围时，归一化为 BadTimeSignature，保留 payload，避免 ValueError/OSError 泄漏；[PR 296](https://github.com/pallets/itsdangerous/pull/296) | timed.py |

选择依据是独立于检索效果和模型成败的公开行为、可固定父/修复提交、纯 Python、stdlib 可验证。构建者查看过上游修复；不是盲测，预训练污染未知。ItsDangerous 与 Click 都属于 Pallets 生态，因此第二仓库也不能代表任意 Python 项目。候选及未选分支理由记录在 `second-repo-candidates-v1.json`；PR299 与 PR296 重叠且涉及平台模拟，MarkupSafe 的 C/native 后端会引入额外环境干预，本批未选。

## 跨文件边界：明确诊断结果

none-salt 的公开入口经过 serializer.py → signer.py → encoding.py。未来时间戳与异常时间戳经过 timed.py → serializer.py/signer.py，并涉及 encoding.py、exc.py。上述说明的是跨模块行为链，不等于修复必须改多个文件。

none-salt 的上游补丁改了两个源文件，独立诊断结果如下：

| 应用到 before 的上游文件改动 | Target | Controls |
| --- | --- | --- |
| 仅 serializer.py | 失败 | 通过 |
| 仅 signer.py | 通过 | 通过 |
| 完整补丁 | 通过 | 通过 |

因此本检查下 signer.py 的改动已经足够；不能宣称这是必须同时修改两个文件的缺陷，也不能用该诊断证明所有可能修复的最小范围。其余两项上游仅改 timed.py。本批补足了第二仓库和跨模块入口检查，**仍未补足必要多文件修复基准**。

## 评分契约与实现

`docs/experiments/second_repo_admission_v1.py` 在实验适配层新增 ItsDangerous 准入，复用既有安全解压、进程执行、源码摘要和准入判定。既有 evals/CoreCoder 引擎及 Click 适配器不变。

核验 GitHub 固定修复提交、直接父提交和源文件范围；记录源码归档、BSD-3-Clause 许可证及摘要。独立 stdlib 测试环境使用 `-I -B`，显式加载对应源码 src，并验证包及已加载子模块均来自该目录，防止安装版包掩盖缺陷。执行前后检查源码和测试摘要；保留每个候选的准入失败原因，不替换失败候选。

公开需求明确要求异常类型、返回值、payload/date_signed、盐值兼容性及边界。检查不约束未公开的错误文案。时间用固定时钟子类，未安装 freezegun；异常时间戳使用可触发当前 Windows 日期越界的值，不声称覆盖 32 位 OverflowError。目标中仅将公开需求明确要求归一化的 TypeError/ValueError/OSError 转为断言失败，其他执行异常不冒充行为缺陷。

公开模型输入在 `second-repo-public-tasks-v1.json`：仅任务 ID、仓库、before 提交、需求、允许文件；允许整个 src/itsdangerous Python 包。父进程用的 `second-repo-suite-v1.json` 才包含 after、参考范围、评分摘要和单文件诊断。后续检索不得将完整候选或清单直接送入模型。

## 冻结身份与证据

```text
engine:   c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
catalog:  9490adfb4fafbd54936940d58a7db0f2851eed1bbaf9070dfd157b2bd69001e8
checks:   42b76a7dccd241cb549cd69a91e3351aabe3e7111eff13912299744592d5e56d
adapter:  87a17a95c77243e4aa4a9a5b7a2a1c1b6421830b788522a107502ef8f8161a46
public:   23f775bf5a65d971c7cbe85273e4a0abd61e698e356f963a0852804879c5e644
manifest: 190edb5b580b12380041c2e2916aef5b0ed198fbe80d9341ebda5b011da89ce4
report:   532adccb5b9c6bc7a83229da2af8704de146378c8a4f054f4528a468eead9dec
```

完整提交和各源码树摘要在 manifest。正式记录目录 `.tmp/real-defects/second-repo-admission-v1-final`；初次验证目录 `second-repo-admission-v1` 保留。发现阶段元数据在 `itsdangerous-discovery-v1`，PR238 查询 404 也记录为未验证来源，未加入准入池。正式目录保存 before/after 归档、快照、许可、环境、独立测试日志、单文件诊断与公开投影。`.tmp` 受 .gitignore 忽略，需要独立归档。

```powershell
python -m pytest tests/test_second_repo_admission.py -q
python -m pytest tests -q
python -m docs.experiments.second_repo_admission_v1 --output .tmp/real-defects/second-repo-admission-rerun --python .tmp/real-defects/click-stdlib-env/Scripts/python.exe
```

输出必须不存在，需网络读取 GitHub 固定提交与归档。复跑报告会因环境路径/时延改变 SHA，不覆盖原记录。测试解释器复用之前的隔离 stdlib 环境，未安装 ItsDangerous 或其它依赖。

## 下一步

后续：六次新修复对照已完成，两组均通过 2/3，独立报告与当前实验阶段收束见 [second-repo-repair-v1.md](second-repo-repair-v1.md)。冻结准入清单保留准入时状态，未覆盖。

验证结果：相关测试 **11 passed**；最终全量回归 **789 passed、1 skipped（72.13 秒）**。新增适配器、检查与测试 Ruff 通过；Git diff 空白检查通过。首次全量 787 passed 后新增了两个冻结清单/公开投影校验，最终全量包含全部新增测试。

校验冻结清单，从公开投影构造相同 Python 行块与完整函数证据，先记录检索结果，再按同模型、证据预算和单次补丁协议执行六次新对照。现有 Click 准入/评分代码有包名约束，须在实验适配层提供 ItsDangerous 的公开投影与验证桥接，不能绕过包来源或检查一致性校验。全部三项保留；不得用 after 修改位置选择证据。与 Click 结果按仓库分列，不立即合并宣称泛化收益。
