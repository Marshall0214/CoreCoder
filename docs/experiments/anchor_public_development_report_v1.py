"""Report development coverage before attributing gain to a dormant recovery branch."""
import argparse
from collections import Counter
from pathlib import Path

from docs.experiments import anchor_public_development_v1 as experiment


def classify(row):
    if row['worker']['status'] != 'completed':
        return row['worker']['status']
    groups = row['verification'].get('groups') or {}
    target = bool(groups.get('Target', {}).get('passed'))
    control = bool(groups.get('Controls', {}).get('passed'))
    if not target and not control:
        return 'target_and_control_failed'
    if not target:
        return 'target_failed'
    if not control:
        return 'control_regression'
    return 'passed'


def publish(source, destination, validation):
    data = experiment.previous.load(source)
    if not data['complete'] or len(data['runs']) != 60 or len(data['workers']) != 30:
        raise ValueError('Require all 30 complete development pairs')
    if len({w['task_id'] for w in data['workers']}) != 30:
        raise ValueError('Duplicate worker task')
    for path, expected in data['protocol']['frozen_inputs'].items():
        if experiment.policy.admission.history.sha(Path(path)) != expected:
            raise ValueError('Frozen runtime/input changed')
    paired = experiment.paired(data['runs'], data['workers'])
    if paired != data['pairing']:
        raise ValueError('Pair accounting mismatch')
    for row in data['runs']:
        metrics = row['worker'].get('metrics')
        if metrics and (metrics['llm_calls'] > 2 or metrics['budget_accounted_tokens'] > 15000):
            raise ValueError('Task budget exceeded')
    data['outcome_classes'] = {s: dict(Counter(classify(r) for r in data['runs'] if r['policy'] == s))
                              for s in experiment.STRATEGIES}
    data['initial_statuses'] = dict(Counter((w.get('initial') or {}).get('status', 'missing') for w in data['workers']))
    data['source_sha256'] = experiment.policy.admission.history.sha(source)
    data['validation'] = experiment.previous.load(validation)
    experiment.policy.write_json(destination.with_suffix('.json'), data)
    before, after = [data['summary'][s]['overall'] for s in experiment.STRATEGIES]
    rows = [r for r in data['runs'] if r['policy'] == 'anchor-public']
    worker_by_id = {w['task_id']: w for w in data['workers']}
    lines = ['# 原文恢复策略：30 项开发集扩大验证', '', '2026-10-08。', '',
             '## 结果与决策', '',
             f'独立 Target/Controls 通过 **{before["passed"]}/30 → {after["passed"]}/30**；新增 {paired["gained"]}，丢失 {paired["lost"]}。', '',
             f'正常行为 Controls **{before["controls_passed"]}/30 → {after["controls_passed"]}/30**。实际恢复触发 **{paired["eligible_count"]}/30**，触发任务 {paired["eligible_tasks"]}。', '',
             f'决策：`{paired["decision"]}`；推广门槛通过：`{paired["gate_passed"]}`。', '',
             '恢复只针对首轮原文唯一匹配事务拒绝。若首轮补丁能应用，即使后来语义测试失败，也不会调用这条恢复分支。没有触发时，两组共享完全相同的候选；不能把其通过任务数归功于恢复策略，也不能证明该策略解决了语义失败。', '',
             '## 实施与固定条件', '',
             '完整重跑既有 30 项开发任务，没有按失败结果挑子集，也没有继续逐题改提示。沿用上轮联合恢复适配器；两个策略共享新首轮，分别为只含锚点诊断与同时包含认证公开检查的重交。', '',
             '保留同一 Qwen digest、首轮提示、类范围检索、五个完整函数/6000 字符证据限制。每组最多两次调用、累计 15,000 Token；未触发任务只调用一次。唯一匹配、范围和源码版本保护保持不变，默认 Agent/API 未改变。', '',
             '全部 30 项公开检查使用此前认证的固定用例，不重写预期；worker 只收到描述、原始证据和公开检查。参考版本和私有评分未进入模型输入，Target/Controls 在 worker 结束后独立执行。已见过的开发集不是新盲测；本轮不再运行留出。', '',
             f'实际调用账目：`{data["actual_usage"]}`。共享首轮只计一次，不把两组累计 Token 相加。两组进程耗时来自同一 worker，不用于宣称速度提升。', '',
             f'首轮状态：`{data["initial_statuses"]}`。联合组结果分类：`{data["outcome_classes"]["anchor-public"]}`。分类仅描述可观察失败，不直接归因于检索或模型推理。', '',
             '## 逐项核查', '',
             '| 任务 | 恢复触发 | 联合组结果 | 公开检查 |', '|---|---|---|---|']
    for row in rows:
        lines.append(f'| {row["task_id"]} | {worker_by_id[row["task_id"]]["eligible"]} | {classify(row)} | '
                     f'{"通过" if row["public_passed"] else "失败"} |')
    lines += ['', '## 下一项核心问题', '',
              '当补丁可应用但行为错误时，需要进入公开缺陷与正常行为反馈流程，而不是再扩展锚点诊断。此前独立开发配对的公开反馈已达到 14/30 → 17/30；本轮未执行该语义纠正分支，不能拿这里的比例与 17/30 直接比较策略优劣。', '',
              '停止把局部原文恢复当作总体优化，保留为编辑拒绝时的可选实验路径。后续优先分析已应用的错误补丁及公开反馈未修好的案例，并选定一个流程级干预后做新配对，不继续围绕三个已知单例堆提示。', '',
              '手写 Target/Controls 和公开检查不等于完整上游测试；没有总体增益时不接入默认流程。旧 50 项统计和留出报告不改写。', '',
              f'工程验收：`{data["validation"]}`。', '',
              '- [完整逐项结果](anchor-public-development-v1.json)、[扩大验证执行器](experiments/anchor_public_development_v1.py)。',
              '- [覆盖与推广门槛测试](../tests/test_anchor_public_development_v1.py)、[三项已知诊断](anchor-public-recovery-v1.md)。',
              '- [此前语义反馈配对](public-feedback-v2.md)。',
              f'- 原始运行 `{source}`；SHA256 `{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--validation', required=True, type=Path)
    args = parser.parse_args()
    publish(args.source.resolve(), args.destination.resolve(), args.validation.resolve())
