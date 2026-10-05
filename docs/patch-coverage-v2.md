# patch-coverage-v2：证据不足表达与编辑一致性诊断

日期：2026-10-04。修正v1清单协议的冲突，并让声明和补丁的文件级差异可见；保留原baseline请求与严格补丁校验，默认仍为baseline。

## 修改

1. 新增action=unverified：公开描述或契约可引用，code_files可以为空，也可以关联allowed_files中的已知文件名；这些关联明确未经验证，即使正文未提供也不宣称已检查。不得猜白名单外文件；edit/preserve仍只能关联已提供的允许源码，并要求非空文件列表。unverified关联不会加入可编辑证据或授予文件访问权限。
2. 引用优先复制单行精确子串。校验允许折叠空白排版，包括换行、缩进和CRLF；不改变词、大小写、标点或接受释义。记录coverage_citation_policy=whitespace-layout-v1，空白引用不合法。
3. 提示要求生成前核对edit声明与补丁。应用补丁后，coverage_edit_consistency记录声明文件、实际字节变化文件、声明未落实、修改未声明及两集合是否一致；无变化编辑不算落实。Trace同步保存。

一致性只是文件集合的诊断，不证明同文件内所有行为都修好了；一个文件可以既修改某行为又保留另一个行为，不将preserve与修改同文件一概视为矛盾。unverified不等于通过；有效引用不等于语义正确。引用错误和声明不一致不覆盖父进程评分，也不自动追加模型调用、写入参考答案或用隐藏失败反馈修复。

初版清单运行元数据记录coverage_protocol=contract-coverage-v2；最终关联规则修正后为contract-coverage-v2.1。CLI仍使用`--patch-policy contract-coverage`，实际版本由源码/Prompt哈希和coverage_protocol辨别；各批结果保留，不合并。

## 验证协议

localization-v1五项各baseline/coverage一次，共十次；任务顺序与交错策略同v1。Qwen3.5:27b Q4_K_M、temperature=0、reasoning_effort=none、keyword、K5、依赖深度2、selection顺序、正文6,000字符、Token30,000、输出2,048、估算上下文16,000、Worker180秒、测试15秒，每次一次调用与干净工作区。两组除patch_policy外配置一致，独立目标/回归验收不变。

测试完整回归334 passed、1 skipped（Windows符号链接环境）；最终空引用保护与诊断专项20 passed，Ruff通过。覆盖unverified边界、换行引用与释义拒绝、声明未落实、未声明修改、noop、同文件preserve以及独立评分。单次/任务只是验收pilot，不预设修复收益；不依据中途结果调整参数。

## 完整v2批次与剩余问题

v2初版在共同源码下完成十次交错pilot：baseline1/5、coverage4/5，两组总Token5,131/9,092，每次一次调用。两组相同任务的有序证据、初始工作区和评分哈希相同；baseline实际Prompt仍与此前基线一致。四项修复通过，分页仍失败；清单从v1的1/5有效改善至3/5有效，一致性诊断在三份有效清单上均显示文件集合一致。原始结果`.tmp/evals/patch-coverage-v2/summary-c01780000f.json`和comparison-audit.json；源码哈希`b254c978460b15c7fc504a8a05795add552d2b9c6c9d55d6d6996ae44bff06e8`。

两份无效清单已使用unverified，却关联了allowed_files中的export_keys.py、backoff_preview.py。要求所有unverified关联必须为空仍过于狭窄：已知文件名与其实现被验证是不同事实。因此最终规则允许白名单内的未验证关联，引用和补丁权限不放宽，并升级为v2.1；这属于开发期间的协议修正，不修改v2原结果。

按原证据manifest从初始任务重建内容并核对字节哈希，使用最终schema离线复核五份原清单，全部结构/引用合法。结果final-schema-recheck.json、脚本`.tmp/recheck_coverage_schema.py`，均标为schema诊断、0模型调用、不参与模型基准；不能用它替换原始3/5清单有效率。最终完整回归 **335 passed、1 skipped**，Ruff通过，新增未验证关联不能变成preserve/edit权限的测试。

**分页尚未解决。**v2模型不再声明编辑paging.py，却把续页游标行为归为preserve；实际只修改query.py，文件声明一致但目标测试仍失败。这是行为判断错误，文件级一致性无法检测，不能把“没有不一致”解释为修复完成。下一步需要公开契约层面的行为检查和有限反馈，独立隐藏验收继续隔离；不硬编码分页答案，也不据此强制增加或降低成功计分。

## 最终v2.1实跑验收

为检查修正的关联边界及剩余业务问题，在最终共同源码下单独执行事件、截止时间和分页三项，不作为新完整对照，也不合并前十次结果。

| 任务 | 清单结构/引用 | 文件声明一致性 | 独立验收 | 总Token |
| --- | --- | --- | --- | --- |
| event-replay | 有效 | 一致 | 通过 | 1,634 |
| job-deadline | 有效 | 一致 | 通过 | 2,174 |
| pagination-cursor | 有效 | 一致 | 未通过 | 1,764 |

三项均一次调用、usage完整、无预算终止，清单诊断错误在这批中消除，分页的业务遗漏仍保留为failed_verification。最终源码哈希`52899084b5c00de9005d18137b212dd2b3d2bc9ca86e9fa50dab90417040eab7`；完整报告`.tmp/evals/patch-coverage-v2-final-smoke/summary-5438e2f87c.json`与同名.md，原输出、补丁、Trace和独立验收按run_id保存。

本阶段共十次v2对照加三次v2.1实跑，离线schema复核另列；未重写旧报告。当前只冻结协议与诊断实现，暂不做三轮收益实验，优先实现仅依赖公开契约的行为检查与有限反馈机制，模型清单继续不作为验收依据。

## 复跑

```powershell
python -m pytest tests/test_patch_coverage.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode pipeline --search-backend keyword --patch-policy baseline --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output .tmp/evals/patch-coverage-v2-replay/baseline
python -m evals --suite evals/fixtures/localization-v1 --mode pipeline --search-backend keyword --patch-policy contract-coverage --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output .tmp/evals/patch-coverage-v2-replay/coverage
```

上述为逐组快速复跑；正式复现交错顺序按v1文档循环或`.tmp/run_patch_coverage.py .tmp/evals/patch-coverage-v2-new`执行。使用新目录，保留失败、取消后停止。脚本与原始报告被Git忽略，应独立备份。
