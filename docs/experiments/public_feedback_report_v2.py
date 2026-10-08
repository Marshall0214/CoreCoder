"""Publish the completed development comparison with overlapping usage explicit."""
import argparse
import json
from collections import Counter
from pathlib import Path

from docs.experiments import failure_classification_v1 as classification
from docs.experiments import public_feedback_v2 as experiment


def comparison(rows):
    pairs = {}
    for row in rows:
        group = pairs.setdefault(row['task_id'], {})
        if row['policy'] in group:
            raise ValueError('Duplicate paired result')
        group[row['policy']] = row
    if len(pairs) != 30 or any(set(p) != {'single', 'public-feedback'} for p in pairs.values()):
        raise ValueError('Require all 30 complete development pairs')
    matrix = []
    for task, pair in pairs.items():
        first, final = pair['single'], pair['public-feedback']
        matrix.append({'task_id': task, 'single': classification.classify(first),
                       'public-feedback': classification.classify(final),
                       'gained': final['accepted'] and not first['accepted'],
                       'lost': first['accepted'] and not final['accepted']})
    candidates = [p['public-feedback'] for p in pairs.values()]
    controls = lambda row, policy: row[policy]['controls_passed']
    return {'rows': matrix, 'gained': [r['task_id'] for r in matrix if r['gained']],
            'lost': [r['task_id'] for r in matrix if r['lost']],
            'new_control_failures': [r['task_id'] for r in matrix if controls(r, 'single') and
                                     not controls(r, 'public-feedback')],
            'removed_control_failures': [r['task_id'] for r in matrix if not controls(r, 'single') and
                                         controls(r, 'public-feedback')],
            'feedback_attempts': sum(r['worker'].get('feedback_attempts', 0) for r in candidates),
            'corrections_retained': sum(r['worker'].get('correction_retained', False) for r in candidates),
            'correction_statuses': dict(Counter(r['worker']['correction']['status'] for r in candidates
                                               if 'correction' in r['worker'])),
            'public_valid_but_private_failed': [r['task_id'] for r in candidates if
                r['worker'].get('correction_retained') and not r['accepted']],
            'actual_model_calls': sum((r['worker'].get('metrics') or {}).get('llm_calls', 0) for r in candidates),
            'actual_tokens': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0)
                                 for r in candidates)}


def publish(source, destination, validation=None):
    data = json.loads(source.read_text(encoding='utf-8'))
    if not data['complete']:
        raise ValueError('Incomplete experiment')
    for path, value in data['protocol']['frozen_inputs'].items():
        if experiment.admission.history.sha(Path(path)) != value:
            raise ValueError('Frozen input changed')
    paired = comparison(data['runs'])
    single = data['summary']['single']['overall']
    candidate = data['summary']['public-feedback']['overall']
    manifest = json.loads((experiment.ROOT / 'docs/expanded-suite-v2.json').read_text(encoding='utf-8'))
    types = {c['task_id']: c['defect_type'] for c in manifest['cases']}
    data['by_defect_type'] = {}
    for kind in sorted({types[r['task_id']] for r in data['runs']}):
        results = {p: [r for r in data['runs'] if r['policy'] == p and types[r['task_id']] == kind]
                   for p in ('single', 'public-feedback')}
        data['by_defect_type'][kind] = {'tasks': len(results['single']),
                                      **{p: sum(r['accepted'] for r in rows) for p, rows in results.items()}}
    data.update(pairs=paired, source_path=str(source.resolve()), source_sha256=experiment.admission.history.sha(source),
                decision='freeze_for_separate_heldout_validation' if data['gate_passed'] else 'stop_policy_development_gate_failed')
    if validation is not None:
        data['validation'] = json.loads(validation.read_text(encoding='utf-8'))
        data['validation_source_sha256'] = experiment.admission.history.sha(validation)
    experiment.write_json(destination.with_suffix('.json'), data)
    lines = ['# 公开复现检查与一次修正：30 项开发集完整对照', '', '2026-10-08。', '',
             '## 做了什么与结果', '',
             '首轮仍按类范围检索生成补丁。随后运行事前认证的公开复现和正常行为检查；失败时，把检查代码、实际失败输出和当前完整函数交给模型，最多修正一次。修正后的两组公开检查全部通过才保留，否则回退首轮结果。私有 Target/Controls 在模型结束后独立评分。', '',
             f"独立修复通过 **{single['passed']}/30 → {candidate['passed']}/30**。新增成功 {len(paired['gained'])} 项、丢失成功 {len(paired['lost'])} 项。",
             f"正常行为 Controls 通过 **{single['controls_passed']}/30 → {candidate['controls_passed']}/30**。", '',
             f"开发门槛：{'通过' if data['gate_passed'] else '未通过'}。决策：`{data['decision']}`。本轮没有运行留出集，没有接入默认 Agent/API。", '',
             '## 检查如何认证', '',
             '- 为全部固定 30 个开发任务手写公开描述示例；模型未自动生成测试。',
             '- 旧源码：Reproduce 必须有实际失败，Preserve 必须通过；参考版本：两组必须通过。每组至少运行一个测试，无跳过、超时或发现失败。',
             '- 在独立 Python 进程导入指定源码，检查来源和执行前后源码/测试哈希；每组 15 秒超时。',
             '- 认证完成并冻结全部描述、检查和检索结果后才调用模型。', '',
             '编写者已查看此前实验结果，这不是盲测。认证时曾根据公开 API 和参考版本的检查结果修正四项错误预期/导入，参考源码和私有测试代码未进入修复模型。参考认证仍可能使公开检查贴近已知修复，不能当作完全独立的测试生成研究。', '',
             '## 固定条件与成本口径', '',
             '- 同一 Qwen digest、不启用思考、temperature=0、top_p=1；单次输出最多 2048 Token。',
             '- 累计 15,000 Token、上下文 16,000、最多两次调用；当前证据仍最多五个完整函数、6000 原文字符，无新增工具。',
             '- 两组共享同一个新首轮结果：single 评分首轮快照，public-feedback 评分经过修正/回退的最终副本。不是两组各自独立采样。',
             '- 第一次提示与原类范围策略一致；第二次只有公开检查、公开运行观察和刷新的当前种子函数，无参考答案/私有评分反馈。', '',
             '| 指标 | 单次首轮 | 包含一次可选修正 |', '|---|---:|---:|',
             f"| 调用 | {single['model_calls']} | {candidate['model_calls']} |",
             f"| Token | {single['tokens']} | {candidate['tokens']} |",
             f"| 执行秒 | {single['worker_seconds']} | {candidate['worker_seconds']} |", '',
             f"实际合计是 **{paired['actual_model_calls']} 次 / {paired['actual_tokens']} Token**；候选列已经包含首轮，不能把两列相加。单次时间为首轮模型和应用耗时，候选时间还包含 Worker 启动和公开检查；两列不适合当作纯模型延迟对照。独立私有评分不计入这里。", '',
             '单次组与反馈组拥有不同的调用机会；本轮评估的是额外修正、公开反馈、当前证据与保留规则的组合收益，未加入同样两次但不提供反馈的消融组，不能单独证明测试反馈的因果收益。', '',
             '## 失败与正常行为保持', '',
             f"反馈尝试 {paired['feedback_attempts']}，保留修正 {paired['corrections_retained']}。修正阶段状态：`{json.dumps(paired['correction_statuses'], ensure_ascii=False)}`。", '',
             f"公开检查通过但私有验收仍失败：{', '.join(paired['public_valid_but_private_failed']) or '无'}。公开检查通过不能替代独立评分。", '',
             f"新增 Controls 失败：{', '.join(paired['new_control_failures']) or '无'}；消除旧 Controls 失败：{', '.join(paired['removed_control_failures']) or '无'}。", '',
             f"新增修复：{', '.join(paired['gained']) or '无'}。丢失修复：{', '.join(paired['lost']) or '无'}。", '',
             '## 按缺陷类型', '', '| 类型 | 任务数 | 首轮通过 | 最终通过 |', '|---|---:|---:|---:|']
    lines += [f"| {kind} | {row['tasks']} | {row['single']} | {row['public-feedback']} |"
              for kind, row in data['by_defect_type'].items()]
    lines += ['', '## 逐项独立评分', '', '| 任务 | 首轮 | 最终 |', '|---|---|---|']
    lines += [f"| {r['task_id']} | {r['single']['outcome']} | {r['public-feedback']['outcome']} |"
              for r in paired['rows']]
    details = {
        'boltons-chunked-bytes': '字节分块：首轮用 b"".join 拼接整数，公开执行报 TypeError；第二轮改为 bytes(chunk)，独立目标与正常行为检查通过。',
        'more-bucket-missing-key': 'bucket：首轮仅将 iter(cache) 改为 iter(cache.keys())，行为未变；第二轮排除空缓存键，独立验收通过。没有验证完整上游套件。',
        'more-combination-size': '组合边界：首轮删除 r 大于池长的错误限制，但空池、r=0 仍失败；反馈后增加空池边界分支，独立验收通过。',
    }
    if paired['gained']:
        lines += ['', '## 新增成功的具体变化', '']
        lines += ['- ' + details[t] for t in paired['gained'] if t in details]
    if validation is not None:
        lines += ['', '## 工程验收', '',
                  f"验收记录：`{json.dumps(data['validation'], ensure_ascii=False)}`。没有重跑 Linux/Docker/HTTP，没有使用 DeepSeek；核心 Agent 与默认服务没有修改。"]
    lines += ['', '## 后续与证据', '',
              '达到事前门槛（净新增至少 2、Controls 通过数不下降）后，下一轮先冻结留出公开检查与相同策略再单独验证。否则收尾本策略，依据剩余失败分类选择下一项核心干预，不扩大重试和提示字段。', '',
              '任务池是小型 Python 库历史缺陷，多数为单文件；开发集收益不代表仓库级或跨文件泛化。既有 50 项检索对照仍保持原报告，不能把本轮开发结果拼入旧留出结果报告一个新总体成功率。', '',
              '- [实现](experiments/public_feedback_v2.py)、[公开检查](experiments/public_feedback_cases_v1.py)、[流程测试](../tests/test_public_feedback_v2.py)。',
              '- [完整逐项 JSON](public-feedback-v2.json)、[前一轮类范围对照](class-scoped-comparison-v1.md)。',
              f'- 原始运行：`{source}`；SHA256：`{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--validation', type=Path)
    args = parser.parse_args()
    publish(args.source, args.destination, args.validation)
