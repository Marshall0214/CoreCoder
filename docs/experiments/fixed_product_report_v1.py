"""Publish a known-case check repair without claiming repair/generalization gains."""
import argparse
import json
from pathlib import Path

from docs.experiments import fixed_product_checks_v1 as experiment


def publish(source, certificate, destination, validation=None):
    data = experiment.previous.load(source)
    cert = experiment.previous.load(certificate)
    if not data['complete'] or not cert['complete'] or len(data['runs']) != 2:
        raise ValueError('Require certified checks and completed diagnostic')
    for path, value in data['protocol']['frozen_inputs'].items():
        if experiment.policy.admission.history.sha(Path(path)) != value:
            raise ValueError('Frozen input changed')
    data.update(certificate=cert, expected=experiment.previous.load(Path(cert['oracle_path'])),
                source_sha256=experiment.policy.admission.history.sha(source),
                certificate_sha256=experiment.policy.admission.history.sha(certificate))
    if validation:
        data['validation'] = experiment.previous.load(validation)
    data['decision'] = ('known_case_repaired_not_generalization' if data['runs'][-1]['accepted'] else
                        'check_loophole_closed_repair_still_failed')
    experiment.policy.write_json(destination.with_suffix('.json'), data)
    first, final = data['runs']
    worker = data['worker']
    metrics = worker.get('metrics') or {}
    lines = ['# 固定预期：拒绝共享迭代器的假成功', '', '2026-10-08。', '',
             '## 完成了什么', '',
             '修复 more-gray-partial-repeat 公开检查的预期漏洞。为 gray_product/partial_product 各选择三组合法普通序列输入，先在原始源码的独立进程计算完整输出，再保存为固定字面量。之后无论候选怎么改函数，检查预期都不变。', '',
             '同时检查普通序列和单次迭代器的完整输出，包含重复两次、单输入重复和普通遍历。没有从参考补丁或私有测试获取期望；参考版本仅作离线认证。', '',
             '认证结果：原始源码复现组失败、保持组通过；参考版本两组通过；上一轮共享迭代器错误补丁的保持组失败。检查现在能拒绝此前被评分漏掉的错误。', '',
             '## 实际模型修复结果', '',
             f"重新从原始源码运行，复用冻结 Worker 和类范围检索，两次调用共享 15,000 Token。首轮综合验收：{first['accepted']}；最终综合验收：{final['accepted']}。综合验收要求私有 Target/Controls 和固定公开检查都通过。", '',
             f"修正保留：{worker.get('correction_retained', False)}。实际 {metrics.get('llm_calls', 0)} 次请求、{metrics.get('budget_accounted_tokens', 0)} Token。决定：`{data['decision']}`。", '',
             '模型仍把多个重复位置绑定到同一个迭代器，partial_product 输出不符合冻结期望。新检查拒绝该修正，Worker 回退首轮；本轮没有再次追加调用、调 Prompt 或挑样例重跑。', '',
             '结果证明已知假成功能够被拦截，**没有证明这个缺陷已修好或提高了总体修复率**。本项已看过且曾属于留出任务，现在是已知失败诊断，不能再当作独立留出验证。', '',
             '## 为什么旧检查不可靠', '',
             '旧检查在候选中计算普通序列的输出，再与单次迭代器输出比较。候选可以让两边一起变错但仍相等。新检查从调用候选求预期，改为读取事前保存的完整常量，因此普通行为改变也会失败。', '',
             '固定原始输出只适用于需求要求保留的合法行为；不能将原始缺陷输出盲目冻结为答案。本轮先以普通可复用输入冻结，再在参考版本认证，缺陷输入的预期来自其与正常输入应等价的公开需求。覆盖只限六组输入，不保证完整上游行为。', '',
             '## 工程验收与后续', '',
             f"验收：`{json.dumps(data.get('validation', {}), ensure_ascii=False)}`。", '',
             '检查漏洞本轮收尾；旧开发/留出评分及拒绝采用结论保留。默认 Agent/API 未接入。下一步回到核心编辑执行：优先处理已观察到的首轮原文唯一匹配失败，使合法候选能进入行为验证，继续保留版本保护和一次修正预算。', '',
             '- [冻结预期与验证实现](experiments/fixed_product_checks_v1.py)、[检查漏洞测试](../tests/test_fixed_product_checks_v1.py)。',
             '- [期望、认证与真实运行 JSON](fixed-product-checks-v1.json)、[原留出评分和反例](public-feedback-heldout-v1.md)。',
             f'- 原始运行 `{source}`；SHA256 `{data["source_sha256"]}`。', '']
    destination.write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--certificate', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--validation', type=Path)
    args = parser.parse_args()
    publish(args.source, args.certificate, args.destination, args.validation)
