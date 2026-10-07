"""Zero-inference historical source audit of bounded first-patch differences."""
import argparse
import json
from pathlib import Path

from docs.experiments import anchored_patch_comparison_v1 as preparation
from docs.experiments import patch_delta_context_v1 as delta

ROOT = preparation.ROOT


def run(output):
    output = output.resolve()
    cases, _ = preparation.prepare(output)
    rows = []
    record = ROOT/'.tmp/real-defects/tentative-publication-compare-v1-certified'
    for name in ('click-usage-empty', 'itsdangerous-none-salt'):
        case = next(c for c in cases if c['task_id'] == name)
        history = record/name/'direct-write'
        workspace = history/'public-candidate/source'
        base = json.loads((history/'feedback-context.json').read_text(encoding='utf-8'))
        result = json.loads((history/'worker-result.json').read_text(encoding='utf-8'))
        before = delta.guard.files(case['before'])
        start = delta.guard.files(workspace)
        packed = delta.pack(workspace, case['allowed_files'], base,
                            result['stages'][0]['edited_symbols'], before)
        assert delta.guard.files(workspace) == start
        assert packed['metadata']['combined_chars'] <= 6000
        assert packed['patch_history']['files']
        if name == 'itsdangerous-none-salt':
            assert '-            salt = self.salt' in packed['patch_history']['files'][0]['diff']
        rows.append({'task_id': name, 'packed': packed})
    hashes = {Path(p).relative_to(ROOT).as_posix(): preparation.repair.audit.sha(Path(p))
              for p in (Path(__file__), Path(delta.__file__), ROOT/'docs/experiments/patch_delta_worker_v1.py')}
    report = {'complete': True, 'model_calls': 0, 'private_grader_calls': 0, 'adapter_hashes': hashes,
              'source_record_sha256': preparation.repair.audit.sha(record/'experiment.json'), 'tasks': rows}
    output.mkdir(parents=True, exist_ok=False)
    (output/'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'complete': True, 'model_calls': 0, 'budgets': [r['packed']['metadata']['combined_chars'] for r in rows]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args().output)
