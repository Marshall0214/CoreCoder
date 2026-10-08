"""Export a complete development comparison without overwriting raw evidence."""
import argparse
import json
from collections import Counter
from pathlib import Path

from docs.experiments import patch_self_review_v1 as experiment


def build(data):
    rows = data['runs']
    expected = [{r['task_id'] for r in rows if r['policy'] == policy} for policy in experiment.POLICIES]
    if (not data['complete'] or len(rows) != 60 or len(expected[0]) != 30 or expected[0] != expected[1]
            or any(r['split'] != 'development' for r in rows)):
        raise ValueError('Require all 30 unique development pairs')
    calculated = experiment.summary(rows)
    pairs = {key: {r['policy']: r for r in rows if r['task_id'] == key} for key in expected[0]}
    changes = {label: sorted(key for key, pair in pairs.items() if predicate(pair))
               for label, predicate in {
                   'gained': lambda p: not p['single']['accepted'] and p['self-review']['accepted'],
                   'lost': lambda p: p['single']['accepted'] and not p['self-review']['accepted'],
               }.items()}
    aggregate = {policy: calculated[policy]['overall'] for policy in experiment.POLICIES}
    before, after = aggregate.values()
    ratio = after['tokens'] / before['tokens'] if before['tokens'] else None
    decisions = dict(Counter(r.get('review_status', 'missing') for r in rows if r['policy'] == 'self-review'))
    machine = {'complete': True, 'protocol': data['protocol'], 'summary': calculated,
               'changes': changes, 'gate': data['gate'], 'token_ratio': ratio, 'review_decisions': decisions,
               'physical_model_calls': after['model_calls'],
               'limits': ['Development only; inspected tasks; one run per distinct issue.',
                          'Shared initial response; do not add branch call totals.',
                          'Extra call and patch context change together; no isolated causal claim.',
                          'Private hand-authored checks, not full upstream regression suites.']}
    lines = ['# 补丁自审：30 项开发集完整对照', '',
             '在类范围检索基础上，共享同一次首轮回答；候选再审查一次 Issue、原始源码和首轮补丁。',
             '不读取私有测试或参考修复，最终评分在两个候选都生成后执行。', '',
             '| 指标 | 单次修复 | 一次自审 |', '|---|---:|---:|',
             f"| 独立通过 | {before['passed']}/30 | {after['passed']}/30 |",
             f"| Controls 通过 | {before['controls_passed']}/30 | {after['controls_passed']}/30 |",
             f"| 策略调用数 | {before['model_calls']} | {after['model_calls']} |",
             f"| Token | {before['tokens']} | {after['tokens']} |",
             f"| 生成阶段秒 | {before['worker_seconds']} | {after['worker_seconds']} |", '',
             f"实际新增调用总数：{after['model_calls']}，两组共享首轮，不能相加为两个独立实验的调用数。",
             '生成阶段计时含证据检查、请求和候选复制，不含独立评分或父进程开销。', '',
             '自审选择分布：' + json.dumps(decisions, ensure_ascii=False) + '。', '',
             '## 收益与回归', '',
             '新增成功：' + (', '.join(changes['gained']) or '无') + '。',
             '丢失成功：' + (', '.join(changes['lost']) or '无') + '。',
             '新增 Controls 失败：' + (', '.join(data['gate']['new_control_regressions']) or '无') + '。',
             f"事前门槛结果：{data['gate']['eligible']}（净新增至少 2 项，且无新增 Controls 回归）。", '',
             '## 可观察失败分类', '', '| 类别 | 单次修复 | 一次自审 |', '|---|---:|---:|']
    categories = sorted(set(calculated['single']['failure_categories']) | set(calculated['self-review']['failure_categories']))
    lines += [f"| {key} | {calculated['single']['failure_categories'].get(key, 0)} | "
              f"{calculated['self-review']['failure_categories'].get(key, 0)} |" for key in categories]
    lines += ['', '## 决策与边界', '',
              ('达到开发门槛；仍需新协议的完整留出对照，当前不设为默认。' if data['gate']['eligible']
               else '未达到开发门槛，停止扩展自审策略，不跑留出、不替换默认流程。'),
              '额外一次调用和补丁上下文同时改变；不能把差异单独归因于推理能力或检索。',
              '30 项为已查看的开发任务，每项只运行一次；结果不能宣称通用收益或优于 Claude/Codex。',
              'Target 未通过只是观察结果，不能直接归因为定位错误或模型理解不足。', '',
              '## 复现', '', '```powershell',
              'python -m docs.experiments.patch_self_review_v1 --admission .tmp/real-defects/expanded-admission-v2-final/admission.json --output .tmp/real-defects/patch-self-review-rerun',
              'python -m docs.experiments.patch_self_review_report_v1 --input .tmp/real-defects/patch-self-review-rerun/experiment.json --output .tmp/real-defects/patch-self-review-rerun/report',
              '```', '', '需要已有冻结任务快照、指定测试解释器和身份一致的本地 Ollama。输出目录必须不存在。']
    return machine, '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    machine, markdown = build(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'summary.json').write_text(json.dumps(machine, indent=2), encoding='utf-8')
    (args.output / 'report.md').write_text(markdown, encoding='utf-8')
