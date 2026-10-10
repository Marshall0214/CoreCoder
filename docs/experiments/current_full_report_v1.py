"""Audit and report a completed fresh 50-task evaluation against historical results."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from evals.runner import digest, snapshot


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def failure(row):
    if row['accepted']:
        return 'passed'
    worker = row['worker']
    statuses = {worker['status'], worker.get('correction', {}).get('status')}
    for name in ('output_truncated', 'budget_exceeded', 'timeout', 'agent_error', 'invalid_patch'):
        if name in statuses:
            return name
    if worker['status'] == 'failed_public_validation':
        return 'public_validation_failed'
    groups = row['verification'].get('groups', {})
    if not groups.get('Controls', {}).get('passed'):
        return 'control_regression'
    return 'independent_target_failed'


def report(result_path, history_path, manifest_path, output):
    current, history, manifest = load(result_path), load(history_path), load(manifest_path)
    rows = current['runs']
    old = {r['task_id']: r for r in history['runs'] if r['policy'] == 'deepseek-high'}
    expected = {c['task_id']: c for c in manifest['cases']}
    if (not current['complete'] or len(rows) != 50 or len({r['task_id'] for r in rows}) != 50
            or {r['task_id'] for r in rows} != set(expected) or set(old) != set(expected)
            or not history['complete']):
        raise ValueError('Require two completed matching 50-task high-thinking results')
    issues, details = [], []
    for path, expected_hash in current['protocol']['input_hashes'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected_hash:
            issues.append('Input changed: ' + path)
    for r in rows:
        task = r['task_id']
        w = r['worker']
        metrics = w.get('metrics') or {}
        root = result_path.parent / task / r['policy']
        if r['process']['timed_out'] or r['process']['returncode'] != 0:
            issues.append('Worker exit: ' + task)
        if not metrics or metrics.get('missing_usage_calls'):
            issues.append('Missing usage: ' + task)
        if metrics.get('llm_calls', 0) > 2 or metrics.get('budget_accounted_tokens', 0) > 60000:
            issues.append('Budget exceeded: ' + task)
        if w.get('final_source_hash') != digest(snapshot(root / 'workspace')):
            issues.append('Final source mismatch: ' + task)
        job = load(root / 'job.json')
        if job['description_hash'] != expected[task]['description_hash']:
            issues.append('Description mismatch: ' + task)
        for name in ('harness', 'frozen_harness', 'contract_harness'):
            if name in job and digest(snapshot(Path(job[name]))) != job[name + '_hash']:
                issues.append('Harness mismatch: ' + task + '/' + name)
        groups = r['verification'].get('groups', {})
        details.append({'task_id': task, 'package': expected[task]['package'],
                        'before': bool(old[task]['accepted']), 'after': bool(r['accepted']),
                        'failure': failure(r), 'worker_status': w['status'],
                        'feedback_attempts': w.get('feedback_attempts', 0),
                        'correction_status': w.get('correction', {}).get('status'),
                        'tokens': metrics.get('budget_accounted_tokens', 0),
                        'calls': metrics.get('llm_calls', 0),
                        'Target': groups.get('Target', {}).get('passed'),
                        'Controls': groups.get('Controls', {}).get('passed')})
    gained = [r['task_id'] for r in details if r['after'] and not r['before']]
    lost = [r['task_id'] for r in details if r['before'] and not r['after']]
    old_tokens = sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0) for r in old.values())
    tokens = sum(r['tokens'] for r in details)
    packages = {p: {'tasks': len(rr := [r for r in details if r['package'] == p]),
                    'before': sum(r['before'] for r in rr), 'after': sum(r['after'] for r in rr)}
                for p in sorted({r['package'] for r in details})}
    result = {'complete': True, 'audit_passed': not issues, 'audit_issues': issues,
              'before': sum(r['before'] for r in details), 'after': sum(r['after'] for r in details),
              'tasks': 50, 'gained': gained, 'lost': lost, 'packages': packages,
              'failures': dict(Counter(r['failure'] for r in details if not r['after'])),
              'tokens_before': old_tokens, 'tokens_after': tokens,
              'token_change_percent': round((tokens / old_tokens - 1) * 100, 2) if old_tokens else None,
              'calls': sum(r['calls'] for r in details), 'rows': details,
              'limits': 'Known tasks, single fresh run vs historical results; retrieval and scoped validation changed; no causal attribution or blind generalization.',
              'source': str(result_path.resolve()), 'historical_source': str(history_path.resolve())}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# 当前策略完整 50 项修复评测', '',
             f"独立验收：历史 {result['before']}/50 → 本轮 {result['after']}/50。新增 {len(gained)}，丢失 {len(lost)}。",
             f"本轮 {result['calls']} 次模型调用，{tokens:,} Token；相对历史 {result['token_change_percent']:+.2f}%。",
             f"审计：{'通过' if not issues else '有异常，见 JSON'}。", '',
             '全部任务从原始源码重新生成候选，没有复用历史回答。原模型别名、预算及独立评分保持；当前检索应用于全部任务，新增公开契约仅应用于 envvar。已知任务池、单轮历史对比，不能独立归因算法收益，也不是盲测。', '',
             '| 仓库 | 数量 | 历史通过 | 本轮通过 |', '| --- | ---: | ---: | ---: |']
    lines += [f"| {p} | {r['tasks']} | {r['before']} | {r['after']} |" for p, r in packages.items()]
    lines += ['', '新增成功：'+(', '.join(gained) or '无'), '历史成功丢失：'+(', '.join(lost) or '无'), '',
              '失败分类（截断优先；细节保留最终状态和独立分组）：', '']
    lines += [f'- {name}: {n}' for name, n in result['failures'].items()]
    lines += ['', '| 任务 | 历史 | 本轮 | 结果分类 | Token |', '| --- | --- | --- | --- | ---: |']
    lines += [f"| {r['task_id']} | {int(r['before'])} | {int(r['after'])} | {r['failure']} | {r['tokens']} |" for r in details]
    lines += ['', f'完整实验：{result_path.resolve()}', f'历史对照：{history_path.resolve()}',
              '补丁、上下文、请求、Trace、公开/冻结检查和独立验收日志位于每项任务输出目录。']
    output.with_suffix('.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--result', type=Path, required=True)
    p.add_argument('--history', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = report(a.result, a.history, a.manifest, a.output)
    print(json.dumps({k: r[k] for k in ('before', 'after', 'gained', 'lost', 'failures', 'tokens_after', 'audit_passed')}, ensure_ascii=False))
