"""Report anchor application separately from limited grader acceptance."""
import argparse
from pathlib import Path

from docs.experiments import exact_anchor_recovery_v1 as experiment

WITNESS = '''import unittest
from more_itertools import split_before, split_after, split_when

class Reproduce(unittest.TestCase):
    def test_empty_iterators_produce_no_groups(self):
        for function in (split_before, split_after):
            with self.subTest(api=function.__name__):
                self.assertEqual(list(function(iter([]), lambda value: True, maxsplit=0)), [])
        self.assertEqual(list(split_when(iter([]), lambda a, b: True, maxsplit=0)), [])

class Preserve(unittest.TestCase):
    def test_nonempty_iterators_remain_unsplit(self):
        for function in (split_before, split_after):
            self.assertEqual(list(function(iter([2, 3]), lambda value: True, maxsplit=0)), [[2, 3]])
        self.assertEqual(list(split_when(iter([2, 3]), lambda a, b: True, maxsplit=0)), [[2, 3]])
'''


def audit(source, admission, output):
    data = experiment.previous.load(source)
    if not data['complete']:
        raise ValueError('Audit after complete experiment only')
    case = next(c for c in experiment.previous.cases_from(admission) if c['task_id'] == 'more-split-empty')
    workspace = source.resolve().parent / case['task_id'] / 'workspace'
    experiment.previous.fresh_output(output, [case], [workspace])
    harness = output / 'checks'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(WITNESS, encoding='utf-8')
    results = {name: experiment.policy.public_check(path, harness, case['package'], case['source_root'], output / name)
               for name, path in [('before', Path(case['before'])), ('after', Path(case['after'])), ('candidate', workspace)]}
    report = {'complete': True, 'model_calls': 0, 'scope': 'post-hoc public empty-iterator witness, not frozen grading',
              'source_sha256': experiment.policy.admission.history.sha(source), 'outcomes': results,
              'certified': experiment.policy.certified(results),
              'candidate_passed': experiment.policy.all_pass(results['candidate'])}
    experiment.policy.write_json(output / 'audit.json', report)
    print('Empty-iterator witness certified:', report['certified'], 'candidate passed:', report['candidate_passed'])


def publish(source, witness, destination, validation=None):
    data = experiment.previous.load(source)
    observed = experiment.previous.load(witness)
    if not data['complete'] or not observed['certified'] or observed['source_sha256'] != experiment.policy.admission.history.sha(source):
        raise ValueError('Require completed experiment and certified audit')
    for path, expected in data['protocol']['frozen_inputs'].items():
        if experiment.policy.admission.history.sha(Path(path)) != expected:
            raise ValueError('Frozen input changed')
    data['supplemental_audit'] = observed
    data['source_sha256'] = experiment.policy.admission.history.sha(source)
    data['decision'] = 'application_recovery_demonstrated_semantic_failure_blocks_default_adoption'
    if validation:
        data['validation'] = experiment.previous.load(validation)
    experiment.policy.write_json(destination.with_suffix('.json'), data)
    first, final = [data['summary'][p]['overall'] for p in ('single', 'anchor-recovery')]
    applied = sum(r['worker']['status'] == 'completed' for r in data['runs'] if r['policy'] == 'anchor-recovery')
    lines = ['# 原文唯一匹配失败：一次事务恢复', '', '2026-10-08。', '',
             '## 实际结果', '',
             f"三项已知失败的新首轮均为 invalid_patch；一次恢复后 **{applied}/3** 补丁可应用，冻结 Target/Controls 计分 **{first['passed']}/3 → {final['passed']}/3**。", '',
             '**但空拆分补丁仍不能正确处理空迭代器。**额外公开核查失败，因此不能把两项计分成功都宣称为正确修复；当前恢复流程不接入默认 Agent/API。', '',
             '| 任务 | 首轮 | 恢复后 | 解释 |', '|---|---|---|---|',
             '| more-falsy-exception | 无效补丁 | 冻结验收通过 | 两处重复原文得到区分，自定义假值异常按 None 判断，目标与 Controls 通过 |',
             '| more-seekable-zero | 无效补丁 | 仍无效 | 第二轮仍未满足唯一匹配 |',
             '| more-split-empty | 无效补丁 | 计分通过，额外核查失败 | 编辑锚点恢复成功，但 if iterable 未识别空迭代器 |', '',
             '## 实现了什么', '',
             '在首轮事务拒绝后，仅在内存中按顺序重放候选，定位首个不唯一锚点。反馈给模型该编辑序号、当前匹配次数、原始匹配次数、已展示的函数归属和完整被拒绝事务，再要求针对未改动源码重交完整补丁。', '',
             '没有自动替换、模糊匹配或按行号修改。仍要求原文在整文件唯一出现、来源已在上下文展示、文件版本一致、编辑范围合法，并在副本中应用和编译后才写回。先前可成功的前缀也不会从失败事务中提交。', '',
             '同一 Qwen、原类范围证据最多五个完整函数/6000 字符、最多两次调用，共享 15,000 Token。第二轮只反馈编辑器拒绝原因，没有参考源码、私有测试或行为评分。两组共享新首轮，费用按累计候选计数。', '',
             f"实际 {final['model_calls']} 次调用、{final['tokens']} Token；首轮占 {first['model_calls']} 次、{first['tokens']} Token。两列不能相加。未分开测量首轮/恢复耗时，不据此宣称提速。", '',
             '## 额外核查与范围', '',
             'split_before、split_after、split_when 对 iter([])、maxsplit=0 应返回 []；补丁返回 [[]]。见证在旧源码失败、参考版本通过，正常非空迭代器仍通过。该见证是在补丁审阅后新增，不改写冻结计分，也没有追加模型尝试。', '',
             '这些是按既有失败选择的三个已看过任务，证明事务恢复在本组能解决两项应用失败，不能估计 50 项总体效果或宣称新的留出提升。测试通过仅限约定手写评分，不是完整上游套件。', '',
             '## 收尾与下一步', '',
             '保留事务恢复为实验适配器；下一步优先把空迭代器这一真实失败反馈给已恢复的候选，验证编辑恢复与行为修正能否在同一预算内配合，避免只解决格式便结束任务。不继续扩任务、服务或无上限重试。', '',
             f"验收：`{data.get('validation', {})}`。", '',
             '- [恢复实现](experiments/exact_anchor_recovery_v1.py)、[诊断和事务测试](../tests/test_exact_anchor_recovery_v1.py)。',
             '- [运行与额外核查 JSON](exact-anchor-recovery-v1.json)、[此前固定预期结论](fixed-product-checks-v1.md)。',
             f'- 原始运行 `{source}`；SHA256 `{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--audit-output', type=Path)
    parser.add_argument('--witness', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--validation', type=Path)
    args = parser.parse_args()
    if args.admission and args.audit_output:
        audit(args.source.resolve(), args.admission.resolve(), args.audit_output.resolve())
    elif args.witness and args.destination:
        publish(args.source.resolve(), args.witness.resolve(), args.destination.resolve(), args.validation)
    else:
        parser.error('Provide audit or publication arguments')
