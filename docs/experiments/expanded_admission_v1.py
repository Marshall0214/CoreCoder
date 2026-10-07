"""Pinned 17-task expansion and reproduction admission, never invokes a model."""
import argparse
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from docs.experiments import anchored_patch_comparison_v1 as existing
from docs.experiments import real_retrieval_audit_v1 as history
from evals.process import run_process, test_environment
from evals.real_admission import extract_archive
from evals.runner import digest, snapshot

ROOT = history.ROOT
DATA = Path(__file__).with_name('expanded_suite_v1')
PYTHON = ROOT/'.tmp/real-defects/click-stdlib-env/Scripts/python.exe'
BOOT = r'''
import collections, collections.abc, importlib, json, pathlib, sys, unittest
source, checks, package, group, destination = sys.argv[1:]
source = pathlib.Path(source).resolve()
# Identical historical-library compatibility in before, reference and candidate.
for name in ('Mapping','MutableMapping','Sequence','MutableSequence','Set','MutableSet','Iterable','Iterator','Callable','Container','Hashable','ItemsView','KeysView','ValuesView'):
    if not hasattr(collections,name): setattr(collections,name,getattr(collections.abc,name))
sys.path.insert(0,str(source))
module = importlib.import_module(package)
assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Installed package shadowed source'
suite = unittest.defaultTestLoader.discover(checks, pattern='test_admission.py')
if unittest.defaultTestLoader.errors: raise RuntimeError('Discovery failed')
selected = unittest.TestSuite()
def select(items):
    for item in items:
        if isinstance(item,unittest.TestSuite): select(item)
        elif item.__class__.__name__==group: selected.addTest(item)
select(suite)
result=unittest.TextTestRunner(verbosity=2).run(selected)
record={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'skipped':len(result.skipped),'expected_failures':len(result.expectedFailures),
        'unexpected_successes':len(result.unexpectedSuccesses),'successful':result.wasSuccessful()}
for name,module in list(sys.modules.items()):
    if name==package or name.startswith(package+'.'):
        if getattr(module,'__file__',None):
            assert pathlib.Path(module.__file__).resolve().is_relative_to(source), 'Submodule shadowed source'
pathlib.Path(destination).write_text(json.dumps(record),encoding='utf-8')
sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)
'''


def groups(source, checks, package, source_root, logs):
    before, code = digest(snapshot(source)), digest(snapshot(checks))
    logs.mkdir(parents=True,exist_ok=False)
    output={}
    for name in ('Target','Controls'):
        record_path=logs/(name+'.json')
        process=run_process([str(PYTHON),'-I','-B','-c',BOOT,str((source/source_root).resolve()),
                             str(checks.resolve()),package,name,str(record_path.resolve())],source,15,
                            logs/(name+'.stdout.txt'),logs/(name+'.stderr.txt'),test_environment(source))
        record=json.loads(record_path.read_text()) if record_path.exists() else {}
        passed=(process['returncode']==0 and not process['timed_out'] and record.get('tests_run',0)>0
                and record.get('successful') and not any(record.get(k,0) for k in
                    ('skipped','expected_failures','unexpected_successes','errors','failures')))
        output[name]=dict(process,**record,passed=bool(passed))
    if digest(snapshot(source))!=before or digest(snapshot(checks))!=code:
        raise ValueError('Source or grading tests mutated')
    return output


def old_cases(output):
    six, grades=existing.prepare(output)
    rows=[]
    for case,grade in zip(six,grades):
        rows.append({'task_id': case['task_id'],'repo': 'pallets/itsdangerous' if case['task_id'].startswith('itsdangerous-') else 'pallets/click',
                         'package': 'itsdangerous' if case['task_id'].startswith('itsdangerous-') else 'click',
                         'source_root': 'src','description': case['description'],'before': str(case['before']),
                         'after': str(grade['source_root']/'after'),'checks': str(grade['checks']),
                         'allowed_files': case['allowed_files'],'split': 'development','previously_inspected': True})
    observed=json.loads((ROOT/'.tmp/real-defects/real-retrieval-audit-v1/protocol.json').read_text())
    inputs=observed['inputs']
    for item in inputs:
        case_id=item['task_id'];admission=Path(item['admission_path']); catalog=Path(item['catalog'])
        report=json.loads(admission.read_text()); raw=next(c for c in json.loads(catalog.read_text())['cases'] if c['case_id']==case_id)
        checks=ROOT/'evals/real_defects/checks'/case_id
        before=admission.parent/case_id/'before';after=admission.parent/case_id/'after'
        admitted=next(c for c in report['cases'] if c['case_id']==case_id)
        if (not admitted['admitted'] or digest(snapshot(before))!=item['before_hash']
                or digest(snapshot(checks))!=admitted['checks_hash']): raise ValueError('Historical admission changed')
        rows.append({'task_id': case_id,'repo': raw['repo'],'package': 'click','source_root': 'src','description': item['description'],
                         'before': str(before),'after': str(after),'checks': str(checks),'allowed_files': item['allowed_files'],
                         'split': 'development','previously_inspected': True})
    if len(rows)!=13 or len({r['task_id'] for r in rows})!=13:raise ValueError('Expected 13 unique historical tasks')
    return rows


def download(case, output):
    directory=output/case['task_id'];directory.mkdir()
    metadata_path=ROOT/'.tmp/expanded-research-v1'/(case['after_commit']+'.json')
    metadata=json.loads(metadata_path.read_text())
    if metadata['sha']!=case['after_commit'] or metadata['parents'][0]['sha']!=case['before_commit']:
        raise ValueError('Fix/parent mismatch')
    shutil.copyfile(metadata_path,directory/'commit-metadata.json')
    for label in ('before','after'):
        cache=ROOT/'.tmp/expanded-research-v1/archives';cache.mkdir(exist_ok=True)
        cached=cache/(case[label+'_commit']+'.zip')
        if not cached.exists():
            url=f"https://codeload.github.com/{case['repo']}/zip/{case[label+'_commit']}"
            process=subprocess.run(['curl.exe','--fail','--location','--silent','--show-error','--max-time','45',
                                    '--output',str(cached),url],capture_output=True,check=False,timeout=50)
            if process.returncode:raise ValueError('Source archive download failed')
        archive=cached.read_bytes()
        if len(archive)>32000000:raise ValueError('Source archive too large')
        (directory/(label+'.zip')).write_bytes(archive)
        extract_archive(archive,directory/label)
    if not list((directory/'before').glob('*LICENSE*')) and not list((directory/'before').glob('*COPYING*')):
        raise ValueError('Missing preserved upstream license')
    before=directory/'before'
    allowed=sorted(p.relative_to(before).as_posix() for p in (before/case['package']).rglob('*.py')
                   if 'tests' not in p.relative_to(before).parts)
    return dict(case,before=str(before.resolve()),after=str((directory/'after').resolve()),
                checks=str((DATA/'checks'/case['task_id']).resolve()),allowed_files=allowed,previously_inspected=False)


def run(output):
    output=output.resolve()
    if output.exists():raise ValueError('Fresh output required')
    historical=old_cases(output)
    output.mkdir(parents=True)
    catalog=json.loads((DATA/'new-candidates.json').read_text())
    report={'protocol':'expanded-admission-v1','complete':False,'model_calls':0,'cases':[],
            'catalog_sha256':history.sha(DATA/'new-candidates.json'), 'checks_sha256':digest(snapshot(DATA/'checks')),
            'adapter_sha256':history.sha(Path(__file__)), 'python':str(PYTHON),
            'compatibility':'Python 3 collections.abc aliases restored equally for all versions; no source changes or dependencies installed'}
    for case in historical+list(ThreadPoolExecutor(4).map(lambda c:download(c,output),catalog['cases'])):
        name=case['task_id'];case_logs=output/'admission-logs'/name
        outcomes={label:groups(Path(case[label]),Path(case['checks']),case['package'],case['source_root'],case_logs/label)
                  for label in ('before','after')}
        target=outcomes['before']['Target']
        admitted=(target.get('tests_run',0)>0 and not target['timed_out'] and not target['passed']
                  and target.get('failures',0)+target.get('errors',0)>0 and outcomes['before']['Controls']['passed']
                  and all(g['passed'] for g in outcomes['after'].values()))
        row=dict(case,admitted=admitted,admission=outcomes,before_hash=digest(snapshot(Path(case['before']))),
                 after_hash=digest(snapshot(Path(case['after']))),checks_hash=digest(snapshot(Path(case['checks']))))
        report['cases'].append(row)
        (output/'admission.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(name, 'admitted' if admitted else 'REJECTED',flush=True)
    report['complete']=len(report['cases'])==30 and all(c['admitted'] for c in report['cases'])
    (output/'admission.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output)
