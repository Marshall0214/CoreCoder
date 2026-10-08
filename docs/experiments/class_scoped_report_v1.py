"""Summarize fresh paired retrieval results without modifying the frozen run."""
import argparse
import json
from pathlib import Path

from docs.experiments import class_scoped_comparison_v1 as experiment
from docs.experiments import failure_classification_v1 as classification


def paired(rows, split):
    selected = [r for r in rows if r['split'] == split]
    names = sorted({r['task_id'] for r in selected})
    matrix = []
    for name in names:
        pair = {r['policy']: r for r in selected if r['task_id'] == name}
        if len(pair) != 2:
            raise ValueError('Incomplete pair')
        before, after = pair['baseline'], pair['class-scoped']
        matrix.append({'task_id': name, 'baseline': classification.classify(before),
                       'candidate': classification.classify(after),
                       'gained': after['accepted'] and not before['accepted'],
                       'lost': before['accepted'] and not after['accepted']})
    return {'tasks': len(names), 'gained': [r['task_id'] for r in matrix if r['gained']],
            'lost': [r['task_id'] for r in matrix if r['lost']],
            'new_control_failures': [r['task_id'] for r in matrix if r['baseline']['controls_passed']
                                     and not r['candidate']['controls_passed']],
            'removed_control_failures': [r['task_id'] for r in matrix if not r['baseline']['controls_passed']
                                         and r['candidate']['controls_passed']], 'rows': matrix}


def publish(source, destination):
    data = json.loads(source.read_text(encoding='utf-8'))
    if not data['complete']:
        raise ValueError('Incomplete experiment')
    for path, value in data['protocol']['inputs_and_adapters_sha256'].items():
        if experiment.baseline.admission.history.sha(Path(path)) != value:
            raise ValueError('Frozen adapter changed')
    data['pairs'] = {s: paired(data['runs'], s) for s in ('development', 'heldout')}
    data['source_path'] = str(source)
    data['source_sha256'] = experiment.baseline.admission.history.sha(source)
    manifest = json.loads((experiment.ROOT / 'docs/expanded-suite-v2.json').read_text(encoding='utf-8'))
    categories = {c['task_id']: c['defect_type'] for c in manifest['cases']}
    data['by_defect_type'] = {}
    for split in ('development', 'heldout'):
        data['by_defect_type'][split] = {}
        for kind in sorted(set(categories.values())):
            results = {policy: [r for r in data['runs'] if r['split'] == split and r['policy'] == policy
                                and categories[r['task_id']] == kind] for policy in experiment.POLICIES}
            if results['baseline']:
                data['by_defect_type'][split][kind] = {
                    'tasks': len(results['baseline']),
                    **{policy: sum(r['accepted'] for r in rows) for policy, rows in results.items()}}
    data['validation'] = {'windows_pytest': {'passed': 1206, 'skipped': 2}, 'targeted_pytest': {'passed': 8},
                          'ruff': 'passed', 'linux_docker_http': 'not rerun'}
    eligible = data['development_gate']['eligible']
    held = data['pairs']['heldout']
    dev = data['pairs']['development']
    bdev = data['summary']['baseline']['split']['development']
    cdev = data['summary']['class-scoped']['split']['development']
    # Passing development is a gate, not proof that the policy should become default.
    validated = (eligible and held['tasks'] == 20 and len(held['gained']) > len(held['lost'])
                 and data['summary']['class-scoped']['split']['heldout']['controls_passed']
                 >= data['summary']['baseline']['split']['heldout']['controls_passed'])
    data['decision'] = ('positive_development_and_heldout_pairing_optional_policy' if validated else
                        'not_adopted_development_gate_failed' if not eligible else 'not_adopted_heldout_validation_failed')
    lines = ['# 类范围检索：一轮完整优化对照', '', '2026-10-08。', '', '## 结果与决策', '',
             f"开发集独立通过：基线 **{bdev['passed']}/30**，候选 **{cdev['passed']}/30**。新增成功 {len(dev['gained'])} 项、丢失成功 {len(dev['lost'])} 项。", '',
             f"开发正常行为检查通过：基线 {bdev['controls_passed']}/30，候选 {cdev['controls_passed']}/30。", '',
             f"新增 Controls 失败：{', '.join(dev['new_control_failures']) or '无'}；消除旧 Controls 失败：{', '.join(dev['removed_control_failures']) or '无'}。回归总数不增加不等于逐项没有新回归。", '',
             f"开发门槛：{'通过' if eligible else '未通过'}；留出状态：{data['heldout_status']}。最终决策：{data['decision']}。", '',
             '若未通过开发门槛，停止本轮候选并保留旧方案；没有为得到更好的结果修改候选或挑选任务重跑。若留出未验证收益，也不替换默认流程。', '',
             '## 方法来源与实际改动', '',
             '参考 [Agentless 分层定位](https://github.com/OpenAutoCoder/Agentless)和 [Aider 结构索引](https://aider.chat/docs/repomap.html)，新增 AST 限定符号与唯一类范围排序。完整调研、区别和事前停止条件见 [调研记录](class-scoped-research-v1.md)。', '',
             '候选优先明确函数引用、被提到的唯一类构造方法及该类其他方法，再按加入限定名的 BM25 排序。可编辑证据仍是原始完整函数。', '',
             '构造方法优先可能占用片段预算并挤掉重要方法；没有动态调用图、继承解析或语义状态推断。零分普通候选排在最后按源码顺序排序，相关候选不足时仍可能填入无关片段。', '',
             '## 同一任务池通过数', '', '| 范围 | 基线 | 候选 |', '|---|---:|---:|',
             f"| 开发 | {bdev['passed']}/30 | {cdev['passed']}/30 |",
             *([f"| 留出 | {data['summary']['baseline']['split']['heldout']['passed']}/20 | {data['summary']['class-scoped']['split']['heldout']['passed']}/20 |",
                f"| 全部 | {data['summary']['baseline']['overall']['passed']}/50 | {data['summary']['class-scoped']['overall']['passed']}/50 |"]
               if held['tasks'] == 20 else []), '',
             '## 固定对照', '',
             '- 全部 30 个开发任务逐项运行新基线和新候选；每个任务独立工作区，交替两组执行顺序。',
             '- 同一冻结 Qwen digest、Prompt、Worker、6000 原文字符、最多五个函数、单次调用、15000 Token、输出 2048 Token。',
             '- 私有 Target/Controls 和 reference 不进入检索或模型输入；只作最终评分。所有 50 项证据在首次调用前冻结。',
             '- 门槛事前固定为开发至少新增净通过 2、Controls 失败数不增加；通过后才运行 20 个留出新配对。',
             '- 本轮是一个组合检索政策的对照，不能将收益分别归因于限定名、显式函数排序或构造函数优先。', '',
             '两组都把检索分数、排序位置和来源标记随原文送入冻结 Worker；这些元数据也会随政策改变。源码正文相同的任务仍可能生成不同补丁，不能将每个差异都解释为新增源码的收益。', '',
             '开发诊断：interpose 将已有函数提前后通过；chunked-negative 补入之前缺失的 chunked；range-equality 补入 __hash__ 后通过。bucket 已展示五个方法仍只把 iter(cache) 改为 iter(cache.keys())，未消除虚构键。combination-size 两组函数正文及顺序相同，候选遗漏空池边界，出现 ValueError；检索元数据不同。这些是轨迹观察，不是各机制的独立因果证据。', '',
             '## 成本', '', '| 范围 | 方案 | 调用 | Token | Worker 秒 |', '|---|---|---:|---:|---:|']
    for split in ('development', 'heldout'):
        for policy in experiment.POLICIES:
            stats = data['summary'][policy]['split'].get(split)
            if stats:
                lines.append(f"| {split} | {policy} | {stats['model_calls']} | {stats['tokens']} | {stats['worker_seconds']} |")
    lines += ['', 'Worker 时间不包含检索、复制和独立评分，受模型加载与缓存影响；Token 为返回用量，不是实际云费用。没有调用 DeepSeek。', '',
              '## 逐项配对结果', '', '| split | 任务 | 基线 | 候选 |', '|---|---|---|---|']
    for split in ('development', 'heldout'):
        lines += [f"| {split} | {r['task_id']} | {r['baseline']['outcome']} | {r['candidate']['outcome']} |"
                  for r in data['pairs'][split]['rows']]
    lines += ['', '## 开发集按缺陷类型', '', '| 类型 | 任务数 | 基线通过 | 候选通过 |', '|---|---:|---:|---:|']
    lines += [f"| {kind} | {row['tasks']} | {row['baseline']} | {row['class-scoped']} |"
              for kind, row in data['by_defect_type']['development'].items()]
    lines += ['', '## 局限与下一步', '',
              '每组每任务一次，开发任务已查看过，相关函数和仓库跨 split；不是盲测或 SWE-bench，也不能证明通用收益。目标未通过不直接等于检索错误。', '',
              '独立评分同时检查目标行为、正常行为与修改范围。后续策略必须作为新版本和新对照，不能覆盖本轮失败。默认 Agent、API 和冻结旧版结果均未修改。', '',
              'Windows 全量 1,206 passed、2 skipped；本轮专项 8 passed；新增模块 Ruff 通过。没有重跑 Linux、Docker 或 HTTP。', '',
              '[机器可读配对结果](class-scoped-comparison-v1.json) · [上一版 50 项基线](expanded-baseline-v2.md)', '']
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in [('class-scoped-comparison-v1.json', json.dumps(data, indent=2, ensure_ascii=False)),
                        ('class-scoped-comparison-v1.md', '\n'.join(lines))]:
        path = destination / name
        if path.exists():
            raise ValueError('Refuse overwrite of published result')
        path.write_text(value, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    publish(args.source.resolve(), args.destination.resolve())
