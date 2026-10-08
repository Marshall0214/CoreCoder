"""Publish heldout results separately; retain the frozen development report."""
import argparse
import json
from collections import Counter
from pathlib import Path

from docs.experiments import failure_classification_v1 as classification
from docs.experiments import public_feedback_heldout_v1 as experiment


def cost(rows):
    candidates = [r for r in rows if r['policy'] == 'public-feedback']
    return {'model_calls': sum((r['worker'].get('metrics') or {}).get('llm_calls', 0) for r in candidates),
            'tokens': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0) for r in candidates),
            'feedback_attempts': sum(r['worker'].get('feedback_attempts', 0) for r in candidates),
            'corrections_retained': sum(r['worker'].get('correction_retained', False) for r in candidates),
            'correction_statuses': dict(Counter(r['worker']['correction']['status'] for r in candidates
                                               if 'correction' in r['worker'])),
            'public_valid_but_private_failed': [r['task_id'] for r in candidates if
                r['worker'].get('correction_retained') and not r['accepted']]}


def decision(pairs, audit=None):
    if audit and audit.get('known_regression'):
        return 'do_not_adopt_known_public_regression'
    return 'validated_optional_policy' if experiment.eligible(pairs) else 'do_not_adopt_heldout_gate_failed'


def publish(source, destination, validation=None, audit=None):
    data = experiment.load(source)
    if not data['complete'] or len(data['runs']) != 40:
        raise ValueError('Require complete heldout validation')
    for path, value in data['protocol']['frozen_inputs'].items():
        if experiment.policy.admission.history.sha(Path(path)) != value:
            raise ValueError('Frozen runtime/input changed')
    pairs = experiment.paired(data['runs'])
    if pairs['tasks'] != 20 or pairs != data['pairs']:
        raise ValueError('Incorrect paired summary')
    data['cost'] = cost(data['runs'])
    data['source_path'] = str(source.resolve())
    data['source_sha256'] = experiment.policy.admission.history.sha(source)
    if audit:
        observed = experiment.load(audit)
        if (not observed['complete'] or not observed['original_expectation_validated'] or
                observed['source_sha256'] != data['source_sha256'] or observed['model_calls'] != 0
                or observed['grading_changed'] or observed['private_grader_used'] or observed['reference_used']):
            raise ValueError('Require a valid independent post-run public witness for this run')
        data['posthoc_audit'] = observed
        data['posthoc_audit_source_sha256'] = experiment.policy.admission.history.sha(audit)
    data['decision'] = decision(pairs, data.get('posthoc_audit'))
    data['score_interpretation'] = 'frozen limited Target/Controls acceptance; not proof of full public-contract correctness'
    manifest = experiment.load(experiment.policy.ROOT / 'docs/expanded-suite-v2.json')
    kinds = {c['task_id']: c['defect_type'] for c in manifest['cases']}
    data['by_defect_type'] = {}
    for kind in sorted({kinds[r['task_id']] for r in data['runs']}):
        selected = {p: [r for r in data['runs'] if r['policy'] == p and kinds[r['task_id']] == kind]
                    for p in ('single', 'public-feedback')}
        data['by_defect_type'][kind] = {'tasks': len(selected['single']),
                                      **{p: sum(r['accepted'] for r in rows) for p, rows in selected.items()}}
    if validation:
        data['validation'] = experiment.load(validation)
        data['validation_source_sha256'] = experiment.policy.admission.history.sha(validation)
    experiment.policy.write_json(destination.with_suffix('.json'), data)
    first, final = [data['summary'][p]['overall'] for p in ('single', 'public-feedback')]
    lines = ['# 公开检查反馈：冻结策略的 20 项留出验证', '', '2026-10-08。', '', '## 结果与决定', '',
             f"冻结 Target/Controls 计分通过 **{first['passed']}/20 → {final['passed']}/20**；新增计分成功 {len(pairs['gained'])}、丢失计分成功 {len(pairs['lost'])}。", '',
             f"私有 Controls 通过 **{first['controls_passed']}/20 → {final['controls_passed']}/20**。新增 Controls 失败：{', '.join(pairs['new_control_failures']) or '无'}。", '',
             f"事前留出门槛：{'通过' if experiment.eligible(pairs) else '未通过'}；决定：`{data['decision']}`。默认 Agent/API 未改动。", '',
             ('**额外公开核查发现 more-gray-partial-repeat 的正常行为回归，评分漏检，因此不采用当前策略。**具体反例与检查缺口见下方补丁审计。'
              if data.get('posthoc_audit', {}).get('known_regression') else ''), '',
             '门槛是全部 20 个配对完成、净新增成功为正且零新增 Controls 失败。通过允许继续审阅，不自动接入；发现已知行为回归仍阻止采用。失败则停止扩大该策略，不挑题重跑或更改 Prompt。', '',
             '## 固定策略', '',
             '直接运行前一轮 `public_feedback_v2.worker`，没有复制或修改修复逻辑：首轮按类范围检索生成补丁；公开 Reproduce/Preserve 失败后最多一次修正，两轮共享 15,000 Token；修正必须通过两组公开检查才保留，否则保留首轮。', '',
             '- 同一 Qwen digest、无思考、temperature=0、top_p=1，输出最多 2048 Token，上下文 16,000；无新增工具。',
             '- 证据最多五个完整函数、6000 原文字符；修正仅刷新原种子函数，不扩展检索。',
             '- 全部 20 项公开检查与检索结果在第一次调用前冻结，并核对导入的 Provider、预算、解析和源码模块哈希。',
             '- 模型不接收参考源码/私有评分；完成模型调用后，才在干净评分副本运行 Target/Controls。',
             '- 两组共享同一次新首轮：single 评分首轮快照，public-feedback 评分最终副本，节省重复运行。', '',
             '## 公开检查与验证边界', '',
             '20 项检查均为手写公开描述/API 示例。认证要求旧源码 Reproduce 有实际失败、Preserve 通过，参考版本两组通过；检查来源、非空执行、无跳过、超时和源码/测试哈希。认证阶段未调用模型。', '',
             '认证时修正了组合索引的触发示例和 xfrange 参数顺序，不基于本轮模型结果调试。参考版本仅作离线认证；检查代码不是自动生成的，也不是独立盲测产物。', '',
             '这些任务先前已用于类范围检索实验，作者也看过相关结果，部分缺陷家族跨开发/留出共享。因此这里只验证新增反馈策略在固定留出任务上的表现，不能宣称新的仓库级盲测或排除训练污染。评分也是手写 Target/Controls，没有运行完整上游套件。', '',
             '## 收益与成本', '', '| 指标 | 单次首轮 | 包含一次可选修正 |', '|---|---:|---:|',
             f"| 独立通过 | {first['passed']}/20 | {final['passed']}/20 |",
             f"| 调用 | {first['model_calls']} | {final['model_calls']} |",
             f"| Token | {first['tokens']} | {final['tokens']} |",
             f"| 执行秒 | {first['worker_seconds']} | {final['worker_seconds']} |", '',
             f"实际总消耗 **{data['cost']['model_calls']} 次 / {data['cost']['tokens']} Token**；额外 {final['tokens'] - first['tokens']} Token。候选包含首轮，不能相加两列。", '',
             '首轮时间是首次请求及应用，候选还包含 Worker 启动和公开检查，均不含独立私有评分；时间不作为纯模型延迟比较。反馈组拥有额外一次调用机会，尚无等调用次数的无反馈消融，不能单独归因于测试内容。', '',
             f"反馈尝试 {data['cost']['feedback_attempts']}；保留修正 {data['cost']['corrections_retained']}；阶段状态：`{json.dumps(data['cost']['correction_statuses'], ensure_ascii=False)}`。", '',
             f"公开检查通过但私有验收仍失败：{', '.join(data['cost']['public_valid_but_private_failed']) or '无'}。公开检查不能替代独立评分。", '',
             f"新增成功：{', '.join(pairs['gained']) or '无'}。", '',
             f"丢失成功：{', '.join(pairs['lost']) or '无'}。消除旧 Controls 失败：{', '.join(pairs['removed_control_failures']) or '无'}。", '',
             '## 分类结果', '', '| 缺陷类型 | 任务数 | 首轮 | 最终 |', '|---|---:|---:|---:|']
    lines += [f"| {kind} | {row['tasks']} | {row['single']} | {row['public-feedback']} |"
              for kind, row in data['by_defect_type'].items()]
    lines += ['', '## 逐项独立评分', '', '| 任务 | 首轮 | 最终 |', '|---|---|---|']
    for task in [r['task_id'] for r in data['runs'] if r['policy'] == 'single']:
        pair = {r['policy']: r for r in data['runs'] if r['task_id'] == task}
        lines.append(f"| {task} | {classification.classify(pair['single'])['outcome']} | "
                     f"{classification.classify(pair['public-feedback'])['outcome']} |")
    if validation:
        lines += ['', '## 工程验收', '', f"`{json.dumps(data['validation'], ensure_ascii=False)}`。"]
    if audit:
        lines += ['', '## 补丁审计发现的漏检回归', '',
                  '**计分门槛通过，但发现已知正常行为回归，因此不采用当前策略。**原始 11/20 → 13/20 与逐项计分记录保留，不事后改写评分或挑选重跑。', '',
                  '新增计分成功 more-gray-partial-repeat 中，模型把 `tuple(map(iter, iterables * repeat))` 改成 `tuple(map(iter, iterables)) * repeat`，多个位置因此共享迭代器。正常序列 `partial_product([2,3],[8,9], repeat=2)` 的首项从 `(2,8,2,8)` 变成 `(2,8,3,9)`；零模型调用的独立公开见证在原始源码通过、最终补丁失败。', '',
                  '公开检查用“当前函数在普通序列上的结果”与“当前函数在单次迭代器上的结果”作相等比较；补丁可以同时改变两边，使错误输出一致。私有 Target/Controls 也漏掉了这项原有行为。因此两项新增计分成功中至少一项不能当作正确修复，不能宣称新增两项均完整满足需求。', '',
                  '该见证是在本轮完成后按补丁审阅新增的单项核查，不是事前冻结评分，也不是全量回归覆盖率。没有参考修复或私有答案进入见证，没有修改候选或再次调用模型。', '',
                  f"审计来源 `{audit}`；SHA256 `{data['posthoc_audit_source_sha256']}`。见 [独立公开核查](experiments/public_feedback_heldout_audit_v1.py)。"]
    lines += ['', '## 后续与证据', '',
              '保留 [开发集 14/30 → 17/30 的原报告](public-feedback-v2.md)。本次使用同一冻结策略，但公开检查的编写批次与执行时间不同；两阶段分开报告，未重跑全部 50 项同一批次，不用拼接总体比例代替开发/留出结果。', '',
              ('下一步先修复检查中会随候选变化的预期：从描述和修复前源码的合法行为冻结预期，认证后不随补丁重新计算；把迭代器共享见证加入新版本检查。旧报告保持不变，再判断如何有限修正。当前流程不接入默认服务。'
               if data.get('posthoc_audit', {}).get('known_regression') else
               '通过后下一步优先比较同样两次调用的无反馈修正，判断收益是否值得额外 Token；未通过则收尾本方向，依据剩余失败选择证据定位优化。两种情况下都不直接接入默认服务。'), '',
              '- [留出执行器](experiments/public_feedback_heldout_v1.py)、[公开检查](experiments/public_feedback_heldout_cases_v1.py)、[冻结 Worker](experiments/public_feedback_v2.py)。',
              '- [流程测试](../tests/test_public_feedback_heldout_v1.py)、[完整结果 JSON](public-feedback-heldout-v1.json)。',
              f'- 原始运行 `{source}`；SHA256 `{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--validation', type=Path)
    parser.add_argument('--audit', type=Path)
    args = parser.parse_args()
    publish(args.source, args.destination, args.validation, args.audit)
