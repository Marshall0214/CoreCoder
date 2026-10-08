"""Publish the complete 50-task run and factual failure classification."""
import argparse
import json
from collections import Counter
from pathlib import Path

from docs.experiments import expanded_admission_v2 as admission
from docs.experiments.failure_classification_v1 import LEGACY_TYPES, report
from evals.runner import digest, snapshot

ROOT = admission.ROOT
TYPE_NAMES = {
    'defaults_and_boundaries': '默认值与边界条件',
    'parameter_validation': '参数校验',
    'state_and_consumption': '状态与迭代器消耗',
    'callback_and_exception': '回调与异常传播',
    'numeric_consistency': '数值与序列一致性',
    'type_and_representation': '类型与表示兼容性',
}


def publish(admitted, experiment, destination):
    data = json.loads(admitted.read_text(encoding='utf-8'))
    results = json.loads(experiment.read_text(encoding='utf-8'))
    if not data['complete'] or not results['complete'] or len(results['runs']) != 50:
        raise ValueError('Require a complete admitted 50-task run')
    for case in data['cases']:
        for source, key in [('before', 'before_hash'), ('after', 'after_hash'), ('checks', 'checks_hash')]:
            if digest(snapshot(Path(case[source]))) != case[key]:
                raise ValueError('Frozen inputs changed')
    for path, value in results['protocol']['adapter_hashes'].items():
        if admission.history.sha(Path(path)) != value:
            raise ValueError('Frozen adapter changed')
    classified = report(data['cases'], results['runs'])
    old = {c['task_id']: c for c in json.loads((ROOT / 'docs/expanded-suite-v1.json').read_text(encoding='utf-8'))['cases']}
    manifest = []
    for c in data['cases']:
        row = {key: c[key] for key in ['task_id', 'repo', 'description', 'split', 'allowed_files',
                                      'source_root', 'before_hash', 'after_hash', 'checks_hash']}
        row['defect_type'] = c.get('defect_type') or LEGACY_TYPES[c['task_id']]
        for key in ['before_commit', 'after_commit', 'upstream_url']:
            row[key] = c.get(key) or old[c['task_id']][key]
        manifest.append(row)
    suite = {'protocol': 'expanded-real-suite-v2', 'unique_tasks': 50,
             'repositories': dict(Counter(c['repo'] for c in manifest)),
             'split': dict(Counter(c['split'] for c in manifest)),
             'defect_types': dict(Counter(c['defect_type'] for c in manifest)),
             'selection': '30 carried tasks + 20 purposively selected upstream fixes; no model-outcome-based inclusion.',
             'limits': 'Public fixes inspected by task constructor; unknown pretraining contamination. Related functions and repositories cross splits. Not a cross-file or SWE-bench benchmark.',
             'cases': manifest}
    summary = {'protocol': 'expanded-baseline-summary-v2', 'complete': True, 'summary': results['summary'],
               'classification': classified, 'experiment_protocol': results['protocol'],
               'admission_path': str(admitted), 'experiment_path': str(experiment),
               'admission_sha256': admission.history.sha(admitted),
               'experiment_sha256': admission.history.sha(experiment), 'runs': results['runs'],
               'validation': {'windows_pytest': {'passed': 1198, 'skipped': 2, 'seconds': 192.03},
                              'targeted_pytest': {'passed': 17}, 'ruff': 'passed',
                              'linux_docker_http': 'not rerun'}}
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in [('expanded-suite-v2.json', suite), ('expanded-baseline-v2.json', summary)]:
        path = destination / name
        if path.exists():
            raise ValueError('Refuse to overwrite published report')
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    overall = results['summary']['overall']
    lines = ['# 50 个真实缺陷：完整基线测试与错误分类', '',
             '## 结论', '',
             f"全部 50 个任务重新运行，独立目标与正常行为检查均通过 {overall['passed']}/50；这是扩充后的基线，不是策略提升结果。", '',
             f"模型调用 {overall['model_calls']} 次，返回 Token {overall['tokens']}，worker 耗时合计 {overall['worker_seconds']} 秒（不含入库和评分）。", '',
             '## 任务池和协议', '',
             '- 保留原 30 个任务，新增 20 个不同上游提交的缺陷；五个仓库，开发集 30、heldout 20。',
             '- 全部任务先复现：before 的 Target 失败、Controls 通过；after 的两组检查均通过。模型看不到 reference 或两组私有检查。',
             '- 固定 qwen3.5:27b、模型 digest、6000 字符完整函数 BM25 上下文、最多 5 个函数、依赖深度 0；单次修复，无工具和反馈重试。',
             '- 继续采用唯一原文匹配替换及独立评分。无效补丁、越界修改或正常行为回归均不能计为成功。',
             '- 每任务最多 15000 Token、输出 2048 Token、600 秒。全部任务同一设置，旧 30 个任务也重新调用模型。',
             '- 全部结果保留，不因模型表现排除或重跑任务；旧版 12/30 不与本次 50 个任务直接比较为提升。', '',
             '## 按任务缺陷类型', '',
             '| 缺陷类型 | 任务数 | 通过 |', '|---|---:|---:|']
    for kind, count in classified['by_defect_type'].items():
        lines.append(f"| {TYPE_NAMES[kind]} | {count['tasks']} | {count['passed']} |")
    lines += ['', '## 按修复结果', '', '| 结果类别 | 数量 |', '|---|---:|']
    lines += [f'| {kind} | {count} |' for kind, count in classified['outcomes'].items()]
    lines += ['', 'control_regression 优先记录正常行为失败；若目标也失败，另加 target_also_failed 标签。invalid_patch 优先于评分通过，防止误计。', '',
              '分类记录的是可观察结果。目标检查失败不能直接证明模型推理错误或检索缺失，根因保留 not_established；后续需用检索对照与失败轨迹验证。', '',
              '## 逐任务结果', '', '| 任务 | split | 缺陷类型 | 结果 |', '|---|---|---|---|']
    lines += [f"| {r['task_id']} | {r['split']} | {TYPE_NAMES[r['defect_type']]} | {r['outcome']} |" for r in classified['rows']]
    lines += ['', '## 实际覆盖与局限', '',
              '新增来源为 MoreItertools 15、Boltons 3、Toolz 2。任务数量增加，仓库种类仍是五个；相关函数和缺陷家族有重叠，不能视为 50 个独立业务场景。', '',
              '构造者查看公开修复以编写检查；heldout 仅用于策略调参隔离，包含已跑过基线的旧 10 个任务和新 10 个任务，不保证预训练未见。新任务多数单文件，不证明跨文件修复能力。', '',
              'Target/Controls 是手写契约检查，并未执行全部上游测试。部分描述提供 API 名称，因此难度与真实用户模糊报错不同。检查方法数不等于任务数。', '',
              '## 工程验证', '', 'Windows 全量：1,198 passed、2 skipped，192.03 秒；专项 17 passed；新增代码与检查文件 Ruff 通过。没有重跑 Linux、Docker 或 HTTP。', '',
              '## 复现', '', '在仓库根目录和 corecoder 环境执行：', '', '```powershell',
              'python -m docs.experiments.expanded_admission_v2 --base .tmp/real-defects/expanded-admission-v1-certified-v2/admission.json --output .tmp/real-defects/expanded-admission-v2-new',
              'python -m docs.experiments.expanded_baseline_v2 --admission .tmp/real-defects/expanded-admission-v2-new/admission.json --output .tmp/real-defects/expanded-baseline-v2-new',
              '```', '',
              '需保留历史入库快照与 `.tmp/expanded-research-v1` 的提交元数据；源代码 ZIP 在 D 盘缓存。当前并非仅 clone 仓库即可离线复现的独立数据包。模型须与冻结 digest 一致。', '',
              '结果：[任务清单](expanded-suite-v2.json)、[机器可读结果和分类](expanded-baseline-v2.json)。', '',
              '下一步仅根据开发集失败分布选择一个核心优化，在固定任务和预算下比较；heldout 不用于逐题调整提示词。', '']
    (destination / 'expanded-baseline-v2.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    publish(args.admission.resolve(), args.experiment.resolve(), args.destination.resolve())
