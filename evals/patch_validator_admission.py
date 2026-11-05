"""No-inference acceptance on saved Toolz candidates; independent scores stay separate."""
import argparse
import importlib.metadata
import shutil
from pathlib import Path

from evals.runner import digest, snapshot
from integrations.harness2 import read, sha, write
from integrations.harness2_runtime import ROOT, workspace
from repairflow.checks import groups
from repairflow.patch_validator import validate
from sandbox import runner


def run(output):
    trial = ROOT/'.tmp/harness2-autonomous-20261104'
    case = read(trial/'identity/job.json')['case']
    output.mkdir(parents=True,exist_ok=False)
    policy = runner.preflight()
    if policy!=read(trial/'identity/identity.json')['sandbox']:
        raise ValueError('Use the previously frozen independent scoring image')
    runner.ACTIVE_POLICY.set(policy)
    original = trial/'input'
    current = trial/'executions/issue-cc-agg1/toolz-join-unmatched/agg1/agent/workspace'
    if digest(snapshot(original))!=case['before_hash']:
        raise ValueError('Original source changed')
    before = (original/'toolz/itertoolz.py').read_text(encoding='utf-8')
    candidate = (current/'toolz/itertoolz.py').read_text(encoding='utf-8')
    variants = {'unchanged':before,'agent_agg1':candidate,
                'names_only':candidate.replace('iteritems(d)','d.items()'),
                'names_and_duplicate':before.replace('iteritems(d)','d.items()')}
    assert before.count('iteritems(d)')==1 and candidate.count('iteritems(d)')==2
    public = ROOT/'repairflow/validation_checks/toolz_join'
    code = ('repairflow/patch_validator.py','repairflow/validation_checks/toolz_join/test_admission.py',
            'evals/patch_validator_admission.py','repairflow/checks.py','sandbox/runner.py')
    write(output/'protocol.json',{'model_calls':0,'validator_mutable_by_optimizer':False,
        'source_files':{name:sha(ROOT/name) for name in code},'ruff_version':importlib.metadata.version('ruff'),
        'sandbox':policy,'case':case,'allowed_files':['toolz/itertoolz.py'],
        'public_check_origin':'New explicit examples from public join contract; no heldout or unseen-task claim',
        'public_checks_sha256':sha(public/'test_admission.py'),
        'independent_check_hash':case['checks_hash'],'independent_results_location':'separate controller-only folders',
        'variants':list(variants),'expected_acceptance':{'unchanged':False,'agent_agg1':False,
            'names_only':False,'names_and_duplicate':True},
        'authorship':'agent_agg1 is saved actual output; the two changed diagnostic variants are analyst-authored'})
    results = {}
    for label,text in variants.items():
        folder = output/label
        source = folder/'source'
        shutil.copytree(original,source)
        (source/'toolz/itertoolz.py').write_text(text,encoding='utf-8',newline='\n')
        report = validate(original,source,['toolz/itertoolz.py'],folder/'validation',public,'toolz')
        independent = groups(source,case['checks'],'toolz','.',folder/'independent-logs',('Target','Controls'))
        write(folder/'independent.json',independent)
        expected = label=='names_and_duplicate'
        assert report['accepted'] is expected and report['status'] in ('rejected','validated'), label
        assert independent['Target']['passed'] is expected and independent['Controls']['passed'], label
        static = report['static']
        results[label] = {'validator_status':report['status'],'accepted':report['accepted'],
            'baseline_static_findings':len(static['baseline_findings']),
            'retained_static_findings':len(static['retained']),'introduced_static_findings':len(static['introduced']),
            'candidate_static_findings':len(static['candidate_findings']),'review_warnings':report['warnings'],
            'public':{name:{k:row[k] for k in ('tests_run','errors','failures','passed')}
                      for name,row in report['public_checks'].items()},
            'independent':{name:{k:row[k] for k in ('tests_run','errors','failures','passed')}
                           for name,row in independent.items()},'reasons':report['reasons']}
        print(label+': '+report['status'],flush=True)
    assert results['agent_agg1']['retained_static_findings']==1
    assert results['agent_agg1']['introduced_static_findings']==1
    assert results['names_only']['candidate_static_findings']==0
    assert results['names_only']['public']['Reproduce']['failures']==2
    protected = {}
    for manifest,packet in (('harness2-autonomous-20261104.json','harness2_autonomous_20261104'),
                            ('harness2-agg1-failure-20261104.json','harness2_agg1_failure_20261104'),
                            ('local50-unmetered-20261103.json','local50_unmetered_20261103')):
        data = read(ROOT/'docs'/manifest)
        assert all(sha(ROOT/'docs'/packet/name)==value for name,value in data['files'].items())
        protected[manifest] = {'sha256':sha(ROOT/'docs'/manifest),'verified_files':len(data['files'])}
    assert digest(snapshot(original))==case['before_hash']
    frozen = read(ROOT/'.tmp/local50-unmetered-checkpoint-20261103-v2/protocol.json')['source_files']
    assert all(sha(ROOT/name)==value for name,value in frozen.items())
    assert all(sha(ROOT/name)==value for name,value in read(output/'protocol.json')['source_files'].items())
    write(output/'report.json',{'status':'passed','model_calls':0,'cases':results,'previous_packets':protected,
        'public_checks_per_variant':5,'independent_checks_per_variant':2,
        'scope':'Four curated mechanism controls, not model repair results or a general validator accuracy benchmark',
        'agent_loop_changed':False,'baseline_source_unchanged':True,'hidden_grading_feedback':False})


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(workspace(parser.parse_args().output))
