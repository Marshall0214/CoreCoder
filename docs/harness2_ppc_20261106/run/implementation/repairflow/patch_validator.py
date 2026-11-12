"""Controller-owned patch checks; public feedback only, never independent grading."""
import argparse
import ast
import difflib
import importlib.metadata
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from evals.runner import changes, digest, snapshot
from sandbox.runner import SandboxError

ROOT = Path(__file__).resolve().parents[1]
RULES = 'F821,F822,F823'
PUBLIC_GROUPS = ('Reproduce', 'Preserve')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def inside(path):
    path = Path(path).absolute()
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError('Use explicit exported inputs and outputs inside the project workspace')
    for parent in (path, *path.parents):
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), 'st_file_attributes', 0) & 1024):
            raise ValueError('Reparse points are not validator inputs')
        if parent == ROOT:
            break
    return path.resolve()


def tree(path):
    path = inside(path)
    if not path.is_dir():
        raise ValueError('Expected a prepared directory')
    for directory, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(directory) / name
            if item.is_symlink() or getattr(item.lstat(), 'st_file_attributes', 0) & 1024:
                raise ValueError('Links are not allowed in source or public-check exports')
    return snapshot(path)


def permitted(name):
    if not isinstance(name, str):
        return False
    path = Path(name)
    return (isinstance(name, str) and name and '\\' not in name and ':' not in name
            and not path.is_absolute() and '..' not in path.parts and path.suffix == '.py'
            and not any(part in ('tests', 'test') for part in path.parts)
            and not path.name.startswith('test_') and not path.name.endswith('_test.py'))


def lint(directory, names, output):
    """Parse source with a trusted installed checker; do not import repository modules."""
    version = importlib.metadata.version('ruff')
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B', '-m', 'ruff', 'check', '--isolated', '--no-cache', '--no-fix',
               '--ignore-noqa', '--no-respect-gitignore', '--target-version', 'py311',
               '--select', RULES, '--output-format', 'json', *[str(directory / name) for name in names]]
    process = subprocess.run(command, capture_output=True, timeout=30, check=False, cwd=ROOT)
    (output / 'ruff.stdout.json').write_bytes(process.stdout)
    (output / 'ruff.stderr.txt').write_bytes(process.stderr)
    if process.returncode not in (0, 1):
        raise ValueError('Static checker failed; no success conclusion')
    raw = json.loads(process.stdout)
    if not isinstance(raw, list):
        raise TypeError('Static checker returned malformed output')
    rows = []
    for row in raw:
        filename = Path(row['filename']).resolve().relative_to(directory).as_posix()
        if filename not in names or row['code'] not in RULES.split(','):
            raise ValueError('Unexpected static checker scope')
        rows.append({'file':filename,'code':row['code'],'message':row['message'],
                     'line':row['location']['row'],'column':row['location']['column']})
    return {'version':version,'rules':RULES,'target':'py311','configuration':'isolated; ignore-noqa; no fixes','findings':rows}


def classify(before, after, baseline_findings, candidate_findings):
    """Retained diagnostics need an unchanged mapped line, not merely the same identifier."""
    maps = {}
    for name in after:
        mapping = {}
        for a,b,size in difflib.SequenceMatcher(None, before[name].decode('utf-8').splitlines(),
                                               after[name].decode('utf-8').splitlines(), autojunk=False).get_matching_blocks():
            mapping.update({a+offset+1:b+offset+1 for offset in range(size)})
        maps[name] = mapping
    used, retained, introduced = set(), [], []
    for finding in candidate_findings:
        match = next((i for i,old in enumerate(baseline_findings) if i not in used
            and all(old[key]==finding[key] for key in ('file','code','message','column'))
            and maps[finding['file']].get(old['line'])==finding['line']), None)
        if match is None:
            introduced.append(finding)
        else:
            used.add(match)
            retained.append({**finding,'baseline_line':baseline_findings[match]['line']})
    return {'retained':retained,'introduced':introduced,
            'removed_locations':[r for i,r in enumerate(baseline_findings) if i not in used],
            'limitation':'Exact unchanged-line mapping; moved code may be reported as removed/new, not proven fixed.'}


def loops(text):
    result = defaultdict(list)

    def walk(node, scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = scope + '.' + node.name
        if isinstance(node, (ast.For, ast.AsyncFor)):
            result[(scope, ast.dump(node, include_attributes=False))].append(node.lineno)
        for child in ast.iter_child_nodes(node):
            walk(child, scope)

    walk(ast.parse(text), '<module>')
    return result


def duplicates(before, after):
    warnings = []
    for name in after:
        old, new = loops(before[name]), loops(after[name])
        for (scope, shape), lines in new.items():
            previous = old.get((scope,shape), [])
            if len(lines)>1 and len(lines)>len(previous):
                warnings.append({'code':'duplicate_loop_review','file':name,'scope':scope,
                    'candidate_lines':lines,'baseline_occurrences':len(previous),
                    'blocking':False,'meaning':'Repeated AST loop; paths may be exclusive. Confirm behavior with tests.'})
    return warnings


def group_passed(row):
    return (type(row.get('tests_run')) is int and row['tests_run']>0
            and row.get('successful') is True and row.get('returncode')==0 and not row.get('timed_out')
            and all(row.get(key)==0 for key in ('errors','failures','skipped','expected_failures','unexpected_successes')))


def validate(baseline, candidate, allowed_files, output, public_checks=None, package=None, source_root='.'):
    baseline, candidate, output = inside(baseline), inside(candidate), inside(output)
    if baseline==candidate or baseline.is_relative_to(candidate) or candidate.is_relative_to(baseline):
        raise ValueError('Baseline and candidate must be separate exports')
    if output.is_relative_to(baseline) or output.is_relative_to(candidate):
        raise ValueError('Artifacts must be outside both inputs')
    before, after = tree(baseline), tree(candidate)
    if public_checks is not None:
        public_checks = inside(public_checks)
        if output.is_relative_to(public_checks) or not isinstance(package,str) or not package:
            raise ValueError('Public checks must be separate and specify a package')
    allowed = set(allowed_files)
    if not allowed or any(not permitted(name) for name in allowed):
        raise ValueError('Only trusted existing non-test Python paths may be allowed')
    output.mkdir(parents=True, exist_ok=False)
    changed, patch = changes(before, after)
    (output / 'patch.diff').write_text(patch, encoding='utf-8')
    violations = sorted(set(changed)-allowed | {name for name in changed if name not in before or name not in after})
    report = {'schema':'patch-validator-v1','status':'checking','accepted':False,'scope':'configured public checks only',
        'independent_grading_used':False,'model_calls':0,'baseline_hash':digest(before),'candidate_hash':digest(after),
        'changed_files':changed,'scope_violations':violations,'reasons':[],'warnings':[],'public_checks':None}
    try:
        if violations:
            report['reasons'].append('scope_violation')
        else:
            names = changed or sorted(allowed & after.keys())
            if not names:
                raise ValueError('No source to inspect')
            b = {name:before[name] for name in names}
            c = {name:after[name] for name in names}
            syntax = []
            for label, files in (('baseline',b),('candidate',c)):
                for name,text in files.items():
                    try:
                        compile(text, name, 'exec')
                    except (SyntaxError, UnicodeError) as exc:
                        syntax.append({'side':label,'file':name,'line':getattr(exc,'lineno',None),
                                       'message':str(exc)})
            report['syntax_errors'] = syntax
            if any(row['side']=='candidate' for row in syntax):
                report['reasons'].append('syntax_error')
            else:
                # Immutable staging copies avoid checker config, caching and source mutation.
                for label, files in (('baseline',before),('candidate',after)):
                    folder = output / label
                    for name,text in files.items():
                        path = folder / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(text)
                baseline_bad = {row['file'] for row in syntax if row['side']=='baseline'}
                baseline_names = [name for name in names if name not in baseline_bad]
                initial = lint(output/'baseline',baseline_names,output/'static-baseline') if baseline_names else {'findings':[]}
                final = lint(output/'candidate',names,output/'static-candidate')
                report['static'] = {'checker':{k:v for k,v in final.items() if k!='findings'},
                    'baseline_syntax_unavailable':sorted(baseline_bad),
                    'baseline_findings':initial['findings'],'candidate_findings':final['findings'],
                    **classify(b,c,initial['findings'],final['findings'])}
                report['warnings'] = duplicates({n:v for n,v in b.items() if n not in baseline_bad},
                                                {n:v for n,v in c.items() if n not in baseline_bad})
                if final['findings']:
                    report['reasons'].append('unresolved_static_findings')
                if public_checks is not None:
                    from repairflow.checks import groups
                    from sandbox import runner

                    if runner.backend()!='docker':
                        raise ValueError('Public validation requires Docker; never execute candidate code on host')
                    checks = inside(public_checks)
                    check_snapshot = tree(checks)
                    policy = runner.preflight()
                    report['sandbox'] = policy
                    report['public_checks_hash'] = digest(check_snapshot)
                    token = runner.ACTIVE_POLICY.set(policy)
                    try:
                        outcomes = groups(output/'candidate',checks,package,source_root,output/'public-logs',PUBLIC_GROUPS)
                    finally:
                        runner.ACTIVE_POLICY.reset(token)
                    report['public_checks'] = outcomes
                    if tree(checks)!=check_snapshot:
                        raise ValueError('Public checks changed')
                    for group in PUBLIC_GROUPS:
                        if not group_passed(outcomes[group]):
                            report['reasons'].append('public_'+group.lower()+'_failed')
                if tree(output/'candidate')!=after or tree(output/'baseline')!=before:
                    raise ValueError('Validation mutated staged inputs')
        if not changed:
            report['reasons'].append('no_patch')
        if tree(baseline)!=before or tree(candidate)!=after:
            raise ValueError('Validation mutated original inputs')
        if public_checks is None:
            report.update(status='static_only',accepted=None)
        else:
            report['accepted'] = not report['reasons'] and report['public_checks'] is not None
            report['status'] = 'validated' if report['accepted'] else 'rejected'
    except (OSError, ValueError, TypeError, SandboxError, subprocess.TimeoutExpired, importlib.metadata.PackageNotFoundError) as exc:
        report.update(status='blocked',accepted=False,infrastructure_error=type(exc).__name__+': '+str(exc))
    finally:
        save(output/'report.json',report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--allowed',nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--public-checks',type=Path)
    parser.add_argument('--package')
    parser.add_argument('--source-root',default='.')
    args = parser.parse_args()
    if not inside(args.output).is_relative_to(ROOT/'.tmp'):
        parser.error('CLI outputs must be fresh directories inside project .tmp on D:')
    result = validate(args.baseline,args.candidate,args.allowed,args.output,args.public_checks,args.package,args.source_root)
    print(json.dumps({'status':result['status'],'accepted':result['accepted'],'report':str(args.output/'report.json')}))
    raise SystemExit(0 if result['accepted'] else 1 if result['status']=='rejected' else 2)


if __name__=='__main__':
    main()
