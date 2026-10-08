"""Publish a bounded context pilot and its historical evidence-coverage audit."""
import argparse
from pathlib import Path

from docs.experiments import failure_context_pilot_v1 as experiment


def publish(source, audit, destination, validation):
    data = experiment.previous.load(source)
    history = experiment.previous.load(audit)
    if not data['complete'] or len(data['runs']) != 6 or len(history['cases']) != 16:
        raise ValueError('Require complete pilot and historical audit')
    for path, expected in data['protocol']['frozen_inputs'].items():
        if experiment.policy.admission.history.sha(Path(path)) != expected:
            raise ValueError('Frozen runtime/input changed')
    if history['selector_hash'] != experiment.policy.admission.history.sha(Path(experiment.selection.__file__)):
        raise ValueError('Historical selector changed')
    if experiment.paired(data['runs'], data['workers']) != data['pairing']:
        raise ValueError('Pair accounting mismatch')
    data['audit'] = history
    data['audit_sha256'] = experiment.policy.admission.history.sha(audit)
    data['source_sha256'] = experiment.policy.admission.history.sha(source)
    data['validation'] = experiment.previous.load(validation)
    data['decision'] = ('known_case_gain_requires_broader_validation' if data['pairing']['gate_passed'] else
                        'no_paired_gain_stop_this_context_variant')
    experiment.policy.write_json(destination.with_suffix('.json'), data)
    a, b = [data['summary'][s]['overall'] for s in experiment.STRATEGIES]
    lines = ['# 公开失败驱动的第二轮函数上下文', '', '2026-10-08。', '',
             '## 实际结果', '',
             f'两项已知语义失败和一项此前修好的控制任务，新配对独立修复 **{a["passed"]}/3 → {b["passed"]}/3**。', '',
             f'新增 {data["pairing"]["gained"]}；丢失 {data["pairing"]["lost"]}；新 Controls 失败 {data["pairing"]["new_control_failures"]}。', '',
             f'决策：`{data["decision"]}`。已知任务小范围试验不是新盲测，不更新 30/50 项总体通过率或留出数字。默认 Agent/API 未接入。', '',
             '| 任务 | 刷新原函数 | 失败驱动函数 |', '|---|---|---|']
    pairs = {}
    for row in data['runs']:
        pairs.setdefault(row['task_id'], {})[row['policy']] = row
    for task, pair in pairs.items():
        lines.append(f'| {task} | {pair["refreshed-seeds"]["status"]} | {pair["failure-context"]["status"]} |')
    lines += ['', '## 本轮失败观察', '',
              '签名候选将 dumps/loads 的 salt 位置参数改为关键字参数，公开 round-trip 仍失败，修正未保留。浮点成员候选已修改 __contains__，但委托 index 后仍错误拒绝 0.5，修正同样未保留。说明实际修改了新展示的位置，也不等于正确理解被调用函数的边界行为。', '',
              '此前修好的 bytes 分块任务两组仍通过。当前没有新增独立成功，不扩到完整开发集，不接入默认流程。', '',
              '## 为什么做及改动', '',
              '此前公开反馈后仍失败 13 项。对全部 16 次反馈尝试做只读审计，其中 13 项仍失败、3 项修好；没有新增模型调用。发现两项缺少可直接关联公开失败的函数：签名 round-trip 堆栈涉及 Serializer.loads；浮点成员检查实际调用 numeric_range.__contains__。这说明覆盖缺口存在，不证明它就是失败原因。', '',
              '第二轮优先装入公开失败堆栈行号所在的完整当前函数，以及公开 assertIn/assertNotIn 经局部构造变量绑定对应的 __contains__，再填充原种子。只用允许文件和公开检查，不读取参考实现或私有评分。行号用于 AST 定位，编辑仍要求原文唯一匹配和文件版本一致。', '',
              '不因测试中构造 CliRunner 等工具就装入初始化函数，避免测试准备代码挤走修复位置。同名类歧义不猜测，普通测试函数分别分析；外部或范围外堆栈忽略。局部绑定是静态启发式，未完整建模嵌套作用域、继承、导入别名和执行顺序。', '',
              '首轮完全一致，两组共享新首轮。第二轮公开测试、失败观察、提示、保留规则相同，差异是源码证据集合及顺序。仍最多五个完整函数/6000 字符，每组最多两次请求、累计 15,000 Token；未通过两组公开检查则回退首轮副本。没有追加第三次修正。', '',
              f'实际调用与用量：`{data["actual_usage"]}`。首轮只计一次，各策略累计数不能相加；不据共享 worker 时间宣称提速。', '',
              '## 范围与后续', '',
              '两项失败按已知的证据新增选择，另选 boltons-chunked-bytes 检查已修好任务是否丢失。编写者已见历史结果，不能宣称自动定位所有错误或全新留出增益。Target/Controls 在模型结束后独立运行，测试通过不等于完整上游行为。', '',
              '有收益且无回归时再扩大开发集；没有收益则停止这版上下文策略，不继续为同一任务手写更多定位提示。', '',
              f'工程验收：`{data["validation"]}`。', '',
              '- [函数重选实现](experiments/failure_context_v1.py)、[配对执行器](experiments/failure_context_pilot_v1.py)。',
              '- [边界与版本测试](../tests/test_failure_context_v1.py)、[审计和逐项结果](failure-context-pilot-v1.json)。',
              '- [原开发反馈](public-feedback-v2.md)、[锚点策略停止结论](anchor-public-development-v1.md)。',
              f'- 原始运行 `{source}`；SHA256 `{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--audit', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--validation', required=True, type=Path)
    args = parser.parse_args()
    publish(args.source.resolve(), args.audit.resolve(), args.destination.resolve(), args.validation.resolve())
