"""Publish paired recovery without conflating patch application with repair."""
import argparse
from pathlib import Path

from docs.experiments import anchor_public_recovery_v1 as experiment


def publish(source, destination, validation):
    data = experiment.previous.load(source)
    if not data['complete'] or len(data['runs']) != 6:
        raise ValueError('Require all three complete pairs')
    for path, expected in data['protocol']['frozen_inputs'].items():
        if experiment.policy.admission.history.sha(Path(path)) != expected:
            raise ValueError('Frozen experiment input changed')
    pairs = {}
    for row in data['runs']:
        group = pairs.setdefault(row['task_id'], {})
        if row['policy'] in group:
            raise ValueError('Duplicate paired row')
        group[row['policy']] = row
    if any(set(p) != set(experiment.STRATEGIES) for p in pairs.values()):
        raise ValueError('Incomplete paired rows')
    strong = lambda r: r['accepted'] and r['public_passed']
    data['public_verified_counts'] = {s: sum(strong(p[s]) for p in pairs.values()) for s in experiment.STRATEGIES}
    data['public_verified_gained'] = [t for t, p in pairs.items() if not strong(p['anchor-only']) and strong(p['anchor-public'])]
    data['public_verified_lost'] = [t for t, p in pairs.items() if strong(p['anchor-only']) and not strong(p['anchor-public'])]
    data['decision'] = ('known_case_gain_requires_broader_validation' if data['public_verified_gained'] and
                        not data['public_verified_lost'] else 'no_paired_gain_stop_this_feedback_variant')
    data['source_sha256'] = experiment.policy.admission.history.sha(source)
    data['validation'] = experiment.previous.load(validation)
    experiment.policy.write_json(destination.with_suffix('.json'), data)
    before, after = [data['summary'][s]['overall'] for s in experiment.STRATEGIES]
    b, a = [data['public_verified_counts'][s] for s in experiment.STRATEGIES]
    lines = ['# 同一次恢复：锚点诊断与公开边界检查', '', '2026-10-08。', '',
             '## 结果', '',
             f'三个已知失败共享新的首轮补丁。冻结 Target/Controls：锚点组 {before["passed"]}/3，联合组 {after["passed"]}/3。', '',
             f'同时通过冻结评分与本轮公开边界检查：**{b}/3 → {a}/3**。新增 {data["public_verified_gained"]}；丢失 {data["public_verified_lost"]}。', '',
             '| 任务 | 仅锚点：状态 / 公开检查 | 联合：状态 / 公开检查 |', '|---|---|---|']
    for task, p in pairs.items():
        cells = [f'{p[s]["status"]} / {"通过" if p[s]["public_passed"] else "失败"}' for s in experiment.STRATEGIES]
        lines.append(f'| {task} | {cells[0]} | {cells[1]} |')
    lines += ['', '## 实现与约束', '',
              '上一轮仅纠正唯一匹配错误，空拆分补丁仍对 iter([]) 返回 [[]]。本轮把认证过的公开用例和旧源码失败观察加入同一次重交请求，同时处理编辑应用与行为边界。', '',
              '空列表、空迭代器应无分组；非空输入 maxsplit=0 应保持单组。固定期望来自公开需求与 API 语义，先在旧源码/参考版本认证，再用于模型反馈。其他两项沿用假值异常和 maxlen=0 公开检查。参考源码仅供离线认证，不进入模型输入。', '',
              '首轮提示、类范围检索证据、模型、输出限制和编辑器保持一致。两组共享新首轮及诊断，各有一次重交；联合组提供公开测试与观察并要求通过后保留。变化同时包含反馈和保留规则，不能把效果仅归于某句话。', '',
              '每组最多两次请求，累计 15,000 Token。没有追加第三次修复。唯一匹配、范围、源码版本检查保留，补丁在副本应用及编译。公开验证失败或出错会恢复首轮快照。', '',
              f'实际调用与用量：`{data["actual_usage"]}`。每列累计含共享首轮，不能直接相加；实际账目只计一次首轮，再计两种重交。没有分别测量策略耗时，不宣称提速。', '',
              '## 范围与决策', '',
              f'决策：`{data["decision"]}`。三项均为已看过的困难任务，不能据此更新 50 项总体通过率或宣称新留出提升。默认 Agent/API 未接入；冻结评分与新增公开检查分列，不改历史结果。', '',
              '独立手写缺陷与正常行为检查仍可能遗漏边界，不等于完整上游测试。下一步优先扩大已冻结开发集验证，避免继续围绕单例追加提示。', '',
              f'工程验收：`{data["validation"]}`。', '',
              '- [流程实现](experiments/anchor_public_recovery_v1.py)、[反馈与回滚测试](../tests/test_anchor_public_recovery_v1.py)。',
              '- [完整结果](anchor-public-recovery-v1.json)、[上轮锚点恢复](exact-anchor-recovery-v1.md)。',
              f'- 原始运行 `{source}`；SHA256 `{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--validation', required=True, type=Path)
    args = parser.parse_args()
    publish(args.source.resolve(), args.destination.resolve(), args.validation.resolve())
