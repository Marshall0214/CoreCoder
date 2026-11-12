"""Exercise the real 3.12 -> 3.11 selection boundary without inference."""
import sys

from integrations import harness2 as bridge
from integrations import harness2_batch as batch
from integrations.harness2_feedback import options
from integrations.harness2_reader import Store, prepare
from integrations.harness2_runtime import ROOT

old = ROOT / '.tmp/harness2-indexed-ppc-20261106'
root = ROOT / '.tmp/harness2-indexed-ppc-v2-preflight-20261106'
root.mkdir(exist_ok=False)
case = bridge.read(old / 'protocol.json')['case']
original = bridge.read(old / 'experiment/result.json')
config = options(case['harness'], case['package'], 20, source_root=case['source_root'])
public_hash = bridge.sha(bridge.workspace(original['rollouts'][0]['folder']) / 'public.json')
decision = batch.public_selection(root, original['rollouts'], None, public_hash, case['before_hash'], config)
assert decision['chosen_label'] == 'base1' and decision['model_calls'] == 0
assert not decision['independent_grading_used']
assert 'openai' not in sys.modules and 'corecoder.llm' not in sys.modules
context = old / 'experiment/runs/issue-cc-agg1/toolz-join-unmatched/context/agg1'
manifest = prepare(context, root / 'evidence')
store = Store(manifest, bridge.sha(manifest))
packet = store.index['review_packet']
assert len(packet['candidates']) == 3
short = {row['path'] for row in packet['short_files'] if row.get('complete_file')}
assert {'pool/inv1/produced.md', 'pool/dom1/produced.md',
        'pool/inv1/harness/systemprompt.md', 'pool/dom1/harness/systemprompt.md'} <= short
bridge.write(root / 'report.json', {'status': 'passed', 'model_calls': 0,
    'controller_python': sys.version, 'controller_did_not_import_model_sdk': True,
    'candidate_selection': decision, 'review_files': len(packet['short_files']),
    'public_candidate_summaries': len(packet['candidates']), 'manifest_sha256': bridge.sha(manifest)})
print({'status': 'passed', 'model_calls': 0, 'candidate': decision['chosen_label'], 'review_files': len(short)})
