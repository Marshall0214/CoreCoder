"""Apply the predeclared public-only delivery rule after failure; zero inference."""
from pathlib import Path

from integrations import harness2 as bridge
from integrations.harness2_feedback import options
from integrations.harness2_runtime import ROOT
from integrations.harness2_selection import select

output = ROOT / '.tmp/harness2-indexed-ppc-20261106'
protocol = bridge.read(output / 'protocol.json')
original_hash = bridge.sha(output / 'report.json')
result_hash = bridge.sha(output / 'experiment/result.json')
report = bridge.read(output / 'report.json')
result = report['result']
assert report['status'] == 'completed_with_ppc_error'
case = protocol['case']
folder = output / 'recovery'
folder.mkdir(exist_ok=False)
public_hash = bridge.sha(Path(result['rollouts'][0]['folder']) / 'public.json')
config = options(case['harness'], case['package'], 20, source_root=case['source_root'])
decision = select(result['rollouts'], None, public_hash, case['before_hash'], config)
bridge.write(folder / 'candidate-selection.json', decision)
assert decision['chosen_label'] is not None
bridge.write(folder / 'job.json', {'kind': 'grade', 'case': case,
    'rollouts': [{'label': 'final', 'folder': decision['chosen_folder']}]})
bridge.child(folder / 'job.json', 180)
grading = bridge.read(folder / 'grading.json')['final']
assert original_hash == bridge.sha(output / 'report.json')
assert result_hash == bridge.sha(output / 'experiment/result.json')
bridge.write(folder / 'report.json', {
    'status': 'completed', 'post_termination_only': True, 'model_calls': 0,
    'original_ppc_status': report['status'], 'does_not_complete_ppc': True,
    'original_report_sha256': original_hash, 'original_result_sha256': result_hash,
    'delivery_rule': 'predeclared public-preserve-v1; no independent scores used',
    'selection': decision, 'grading': grading})
print({'chosen': decision['chosen_label'], 'resolved': grading['resolved'], 'model_calls': 0})
