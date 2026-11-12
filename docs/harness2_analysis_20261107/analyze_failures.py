"""Read-only audit of the frozen completed batch; no inference or test execution."""
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / '.tmp/harness2-v2-50-20261106'
OUTPUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def ref(path, needle=None):
    text = path.read_text(encoding='utf-8')
    line = 1
    if needle is not None:
        matches = [i for i, s in enumerate(text.splitlines(), 1) if needle in s]
        if not matches:
            raise ValueError(f'Missing evidence {path}: {needle}')
        line = matches[0]
    return {'path': str(path), 'line': line}


def first_error(log):
    lines = log.read_text(encoding='utf-8').splitlines()
    wanted = ('AssertionError:', 'IndexError:', 'ValueError:', 'RuntimeError:', 'TypeError:', 'NameError:')
    for i, line in enumerate(lines, 1):
        if line.startswith(wanted):
            return {'path': str(log), 'line': i, 'text': line}
    return {'path': str(log), 'line': 1, 'text': '\n'.join(lines[:6])}


def main():
    report = read(BATCH / 'report.json')
    rows = []
    for task_id, row in report['tasks']['harness2'].items():
        if row['resolved']:
            continue
        rollout = Path(row['result']['final_rollout'])
        feedback = read(rollout / 'feedback/report.json')
        grade = row['grade']
        assert not grade['scope_violations']
        assert grade['groups']['Target']['passed'] is False
        category = ('no_final_patch' if not grade['changed_files'] else
                    'regression_and_unfixed_target' if not grade['groups']['Controls']['passed'] else
                    'applied_patch_but_target_failed')
        patch = rollout / 'grading/patch.diff'
        assert bool(patch.read_text(encoding='utf-8').strip()) == bool(grade['changed_files'])
        before_dir = BATCH / 'arms/harness2' / task_id / 'input'
        changed_evidence = []
        for name in grade['changed_files']:
            before = before_dir / name
            final = rollout / 'feedback/workspace' / name
            assert before.read_bytes() != final.read_bytes()
            ast.parse(final.read_text(encoding='utf-8'), filename=str(final))
            changed_evidence.append({'file': name, 'before': str(before), 'final': str(final),
                                     'syntax_parse': 'passed_without_executing_candidate'})
        round_reports = sorted((rollout / 'feedback/rounds').glob('*/report.json'))
        rounds = [read(p) for p in round_reports]
        rejection_counts = Counter((x.get('patch_error') or {}).get('code')
                                   for x in rounds if x.get('patch_status') == 'rejected')
        blocks = []
        for rp in round_reports:
            validation = rp.parent / 'validation/report.json'
            if not validation.exists():
                continue
            v = read(validation)
            if v.get('infrastructure_error'):
                stderr = validation.parent / 'public-logs/Reproduce.stderr.txt'
                blocks.append({'report': ref(validation, 'infrastructure_error'),
                               'error': v['infrastructure_error'],
                               'stderr': ref(stderr), 'stderr_text': stderr.read_text(encoding='utf-8')})
        rows.append({'task_id': task_id, 'category': category,
                     'adopted_label': row['result']['adopted_label'],
                     'target_passed': grade['groups']['Target']['passed'],
                     'controls_passed': grade['groups']['Controls']['passed'],
                     'target_errors': grade['groups']['Target']['errors'],
                     'target_failures': grade['groups']['Target']['failures'],
                     'changed_files': grade['changed_files'], 'changed_evidence': changed_evidence,
                     'patch': ref(patch), 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                     'grading_receipt': ref(BATCH / 'arms/harness2' / task_id / 'post-termination/grading.json'),
                     'target_error': first_error(rollout / 'grading/grading-logs/Target.stderr.txt'),
                     'controls_error': (first_error(rollout / 'grading/grading-logs/Controls.stderr.txt')
                                        if not grade['groups']['Controls']['passed'] else None),
                     'feedback_report': ref(rollout / 'feedback/report.json', 'status'),
                     'feedback_status': feedback['status'],
                     'feedback_rounds_attempted': feedback['feedback_rounds_attempted'],
                     'feedback_applied_patches': feedback['applied_patches'],
                     'feedback_rejected_patches': sum(rejection_counts.values()),
                     'feedback_rejection_codes': dict(rejection_counts),
                     'initial_public_validation': read(rollout / 'feedback/validation-000/report.json')['status'],
                     'public_accepted': feedback['accepted'], 'validation_blocks': blocks})
    assert len(rows) == 25
    summary = {'final_failures': len(rows), 'scope': 'The 25 delivered unresolved candidates only; not all 200 search candidates.',
               'categories': dict(Counter(x['category'] for x in rows)),
               'grading_combinations': dict(Counter(f"Target={x['target_passed']},Controls={x['controls_passed']}" for x in rows)),
               'feedback_statuses': dict(Counter(x['feedback_status'] for x in rows)),
               'final_feedback_rounds_attempted': sum(x['feedback_rounds_attempted'] for x in rows),
               'final_feedback_applied_patches': sum(x['feedback_applied_patches'] for x in rows),
               'final_feedback_rejected_patches': sum(x['feedback_rejected_patches'] for x in rows),
               'final_feedback_rejection_codes': dict(sum((Counter(x['feedback_rejection_codes']) for x in rows), Counter())),
               'public_passed_but_independent_failed': [x['task_id'] for x in rows if x['public_accepted']],
               'changed_python_files_ast_parsed': sum(len(x['changed_evidence']) for x in rows),
               'candidate_code_executed_by_audit': False, 'model_calls_by_audit': 0,
               'independent_test_results_are_not_optimizer_inputs': True}
    artifact = {'schema': 'harness2-final-failures-audit-v1', 'source_report': str(BATCH / 'report.json'),
                'source_report_sha256': hashlib.sha256((BATCH / 'report.json').read_bytes()).hexdigest(),
                'classification_rule': 'No final patch has priority. A nonempty applied patch is not a correct or useful patch. Regression requires independent Controls failure.',
                'summary': summary, 'tasks': rows}
    (OUTPUT / 'failure-analysis.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_notes(artifact, report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def write_notes(artifact, report):
    def link(evidence, label=None):
        return f"[{label or Path(evidence['path']).name}]({evidence['path'].replace(chr(92), '/')}:{evidence['line']})"

    def rollout(task):
        return Path(report['tasks']['harness2'][task]['result']['final_rollout'])

    def source(task, name, final=True, needle=None):
        path = rollout(task) / 'feedback/workspace' / name if final else BATCH / 'arms/harness2' / task / 'input' / name
        return ref(path, needle)

    def check(task, needle):
        job = read(BATCH / 'arms/harness2' / task / 'post-termination/job.json')
        return ref(Path(job['case']['checks']) / 'test_admission.py', needle)

    def error(task, group='Target'):
        return first_error(rollout(task) / f'grading/grading-logs/{group}.stderr.txt')

    exec_ref = ref(ROOT / 'sandbox/runner.py', "code, out, err, timeout, overflow = bounded(['exec'")
    invalid_ref = ref(ROOT / 'sandbox/runner.py', "result['sandbox_status'] = 'sandbox_invalid_result'")
    raise_ref = ref(ROOT / 'sandbox/runner.py', "raise SandboxError(result['sandbox_status'])")
    validator_block_ref = ref(ROOT / 'repairflow/patch_validator.py', "report.update(status='blocked'")
    feedback_block_ref = ref(ROOT / 'repairflow/feedback_repair.py', "if current['status'] == 'blocked'")
    wrong_salt_ref = source('itsdangerous-none-salt', 'src/itsdangerous/serializer.py', True, 'salt = b"itsdangerous.Serializer"')

    summary = artifact['summary']
    lines = ['# Harness² 50 项复跑：25 个最终失败任务审计', '',
             '本报告仅读取冻结产物，不调用模型、不联网、不执行候选代码、不重跑测试。独立评分证据仅供事后分析，未发送给模型或选择器。', '',
             f"- 最终失败 25 项：11 项无最终补丁；12 项补丁已应用但目标未修复；2 项目标与正常行为同时失败。",
             '- Target 失败 / Controls 通过：23 项；Target 与 Controls 同时失败：2 项；其他组合：0。',
             '- 非空最终补丁共 15 个 Python 文件，均仅通过本审计 AST 语法解析；这不证明补丁正确。',
             f"- 25 个最终交付分支的反馈共 {summary['final_feedback_rounds_attempted']} 次请求：4 次 applied、297 次 rejected、5 次 provider_failed。不是全部 200 个搜索候选的统计。",
             '- 拒绝原因：237 次 invalid_patch_schema、48 次 anchor_not_found、11 次 syntax_error、1 次 no_change。',
             '- 最终反馈状态：14 个 feedback_round_limit，4 个 validation_blocked，5 个 local_provider_failed，2 个 ready_for_review。',
             '- 14 个耗尽 20 轮的最终分支全部 0 次有效应用补丁。因此“给了 20 轮”不能解释为“进行了 20 次可验证修复”。', '',
             '## 逐任务结果', '',
             '|任务|主分类|Controls|最终反馈状态|请求/应用|独立评分证据|',
             '|---|---|---|---|---|---|']
    categories = {'no_final_patch': '无最终补丁', 'regression_and_unfixed_target': '引入回归且目标未修复',
                  'applied_patch_but_target_failed': '有补丁但目标失败'}
    for row in artifact['tasks']:
        lines.append(f"|{row['task_id']}|{categories[row['category']]}|{'通过' if row['controls_passed'] else '失败'}|{row['feedback_status']}|{row['feedback_rounds_attempted']}/{row['feedback_applied_patches']}|{link(row['grading_receipt'], 'grading.json')}|")

    lines += ['', '## 有代码证据的错误机制', '',
              '### 1. 格式失败消耗轮数，未形成有效反馈闭环', '',
              'click-style-color-validation 的第 1 次反馈输出 action/patch 包装的统一 Diff；执行接口要求顶层仅含 edits 数组，因此直接拒绝。more-range-equality 输出 action/path/content；more-falsy-exception 输出 status/changes 的完成说明。它们不是测试失败后不断改善补丁，而是多数请求未能落盘。', '']
    for task in ['click-style-color-validation', 'more-range-equality', 'more-falsy-exception']:
        folder = rollout(task) / 'feedback/rounds/001'
        lines.append(f"- {task}: {link(ref(folder / 'response.txt'))}；{link(ref(folder / 'report.json', 'invalid_patch_schema'))}。")
    lines += ['', '证据能证明格式拒绝及无修改，不能仅据此断言修复内容本来正确，也不能断言只修格式即可提高成功率。', '',
              '### 2. 四个验证阻塞发生在容器入口读取阶段', '',
              "四项最后一次已应用补丁的 Reproduce.stderr.txt 完全一致：python: can't open file '/runner.py': [Errno 5] Input/output error。stdout 为空，进程退出码 2。Python 尚未读取测试入口，因此不是被测库导致测试断言失败，也没有证据指向测试结果 JSON 序列化错误。", '']
    for row in artifact['tasks']:
        for block in row['validation_blocks']:
            lines.append(f"- {row['task_id']}: {link(block['stderr'])}；{link(block['report'])}。")
    lines += ['',
              '执行层先把 runner 文件只读 bind mount 为 /runner.py，再 docker exec；后续从 /tmp 取 result.json 失败统一报告 sandbox_invalid_result。检查函数转抛 SandboxError，Validator 转为 blocked，反馈入口遇 blocked 停止。', '',
              f"- 挂载及 exec：{link(ref(ROOT / 'sandbox/runner.py', 'for path, target in'))}、{link(exec_ref)}。",
              f"- 结果读取及异常：{link(invalid_ref)}、{link(raise_ref)}。",
              f"- 传播：{link(ref(ROOT / 'repairflow/checks.py', 'process = runner.run'))}、{link(validator_block_ref)}、{link(feedback_block_ref)}。", '',
              '具体为何 Docker/宿主机挂载返回 EIO 尚无证据；本报告不归因为磁盘已满、权限或某种 Docker Desktop bug。可先在候选哈希不变、测试输入不变时有限重试同一公开检查，并单独记录基础设施尝试；不要给模型追加修代码请求，也不要降级到宿主机执行。', '',
              '### 3. 优化后的指导写入了与源码、需求冲突的默认值', '',
              'itsdangerous-none-salt 的合成指导声称 Serializer 默认 salt 是 itsdangerous.Serializer；实际原始构造函数默认值是 itsdangerous。最终补丁将构造默认值改为 None，再替换为错误的 itsdangerous.Serializer，既不满足显式 None 与 Signer 默认一致的目标，也破坏了不传参时原有签名兼容性。', '',
              f"- 合成指导：{link(ref(rollout('itsdangerous-none-salt') / 'job.json', 'Serializer default salt'))}。",
              f"- 原始默认值：{link(source('itsdangerous-none-salt', 'src/itsdangerous/serializer.py', False, 'salt: _t_str_bytes'))}；最终错误值：{link(wrong_salt_ref)}。",
              f"- 独立目标错误：{link(error('itsdangerous-none-salt'))}；正常行为错误：{link(error('itsdangerous-none-salt', 'Controls'))}。", '',
              '证据支持“指导包含错误事实，最终补丁遵循该错误事实”；并不能把全过程每次模型决策都因果归结为该条指导。首先应让指导中的项目事实关联源码行/内容哈希；无证据的默认值不要升级为强制修法。', '',
              '### 4. 局部方法修复遗漏同一契约的其他实现', '',
              'more-falsy-exception 修改 one()，用 is not None 识别自定义假值异常，但 only() 仍保留 raise too_long or ValueError(msg)。测试覆盖 one 与 only；最终 only 遇假值异常对象仍抛出 ValueError。', '',
              f"- 补丁：{link(ref(rollout('more-falsy-exception') / 'grading/patch.diff'))}。",
              f"- 漏改实现：{link(source('more-falsy-exception', 'more_itertools/more.py', True, 'raise too_long or ValueError(msg)'))}。",
              f"- 测试与报错：{link(check('more-falsy-exception', 'mi.only'))}、{link(error('more-falsy-exception'))}。", '',
              '这提示检索/影响范围要覆盖同一参数契约的多个入口；不是简单追加一条“多检查”即可证明有效。', '',
              '### 5. 修复 __eq__ 后未同步 __hash__，破坏协议不变量', '',
              'more-range-equality 新增“单元素范围只比较起点”的相等规则；__hash__ 仍包含 step，导致相等的两个对象得到不同 hash。', '',
              f"- 新比较规则：{link(source('more-range-equality', 'more_itertools/more.py', True, 'Singleton ranges'))}。",
              f"- 原哈希计算保留：{link(source('more-range-equality', 'more_itertools/more.py', True, 'return hash((self._start'))}。",
              f"- 独立测试/报错：{link(check('more-range-equality', 'hash(a)'))}、{link(error('more-range-equality'))}。", '',
              '这是跨方法协议约束缺失。后续应按语言协议关联 eq/hash、iter/next、enter/exit 等符号，再用公开可见的通用不变量检查，不把本轮隐藏断言直接放入提示词。', '',
              '### 6. 迭代器复用错误未修复，反而破坏笛卡尔积枚举顺序', '',
              'more-product-repeat 只去掉 reversed，并直接返回 result。iterables * repeat 仍先重复同一个单次迭代器对象，再分别 tuple 消耗它；后续池为空，目标抛 IndexError。移除 reversed 还把正常 nth_product(1, AB, CD) 从 (A,D) 改成 (B,C)。', '',
              f"- 原始与最终池构建：{link(source('more-product-repeat', 'more_itertools/more.py', False, 'pools = tuple(map(tuple, reversed'))}、{link(source('more-product-repeat', 'more_itertools/more.py', True, 'pools = tuple(map(tuple, iterables * repeat))'))}。",
              f"- 补丁：{link(ref(rollout('more-product-repeat') / 'grading/patch.diff'))}；目标错误：{link(error('more-product-repeat'))}；正常行为错误：{link(error('more-product-repeat', 'Controls'))}。", '',
              '应区分“缓存输入池后重复”与“重复迭代器对象再消费”，并保持混合进制下标映射约定；此处程序语义问题已被正常行为检查发现，但最后一轮公开验证先被 EIO 阻塞。', '',
              '### 7. 公开检查通过并不覆盖完整需求', '',
              'click-prompt-suffix 只修 prompt()，公开 Reproduce 只调用 prompt()；独立 Target 同时覆盖 confirm()，后者仍插入空格。click-flag-envvar 公开检查仅断言不是 UPPER，None 也能通过；独立目标要求精确 False 及非匹配原值，最终失败。', '',
              f"- prompt 的补丁：{link(ref(rollout('click-prompt-suffix') / 'grading/patch.diff'))}；confirm 未修复的报错：{link(error('click-prompt-suffix'))}。",
              f"- flag-envvar 的公开通过记录：{link(ref(rollout('click-flag-envvar') / 'feedback/validation-000/report.json', 'accepted'))}；精确值断言失败：{link(error('click-flag-envvar'))}。", '',
              '这不是建议把隐藏测试反馈给模型。下一协议应在不读取隐藏答案的条件下，从公开需求独立派生入口×边界×正常行为检查，冻结后再评估。', '',
              '## 优先顺序与结论边界', '',
              '1. 先修反馈交互合同：确定性输出 schema、格式错误反馈与原始任务/代码事实保持一致；记录“请求数/补丁应用数/测试反馈数”三种计数。理由：当前 14 个最终失败任务耗尽 20 轮但零应用，策略收益根本没有被充分检验。修后先做存档响应离线回放及少量本地任务，不立即跑 50。',
              '2. 同时修沙箱入口读取失败的诊断与有限重试：只重试相同候选的检查，保留原 EIO、结果缺失与真实断言失败的区别。理由：4 个已落盘修正被基础设施阻塞，且总表 errors=0 掩盖这种内部中断。', '',
              '公开检查覆盖与关联协议符号是随后最有代码语义价值的方向。当前数据证明了具体阻塞和错误，不足以保证修复它们会把 25/50 提升到某个数；需要新的受控小实验验证。', '',
              '本审计新增 model_calls=0；不修改原批次产物、执行代码或评分规则。']
    (OUTPUT / 'failure-notes.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
