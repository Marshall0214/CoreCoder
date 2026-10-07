"""Zero-inference trace audit on frozen historical first candidates."""
import argparse
import json
from pathlib import Path

from docs.experiments import parameter_trace_worker_v1 as worker

ROOT = worker.public.ROOT
HISTORY = ROOT/'.tmp/real-defects/restart-feedback-compare-v1'


def run(output):
    prior = json.loads((HISTORY/'experiment.json').read_text(encoding='utf-8'))
    assert prior['complete']
    output.mkdir(parents=True, exist_ok=False)
    rows=[]
    for row in prior['runs']:
        if row['policy'] != 'continue': continue
        name=row['task_id']; root=HISTORY/name/'continue'
        job=json.loads((root/'job.json').read_text(encoding='utf-8'))
        workspace=root/'public-candidate/source'
        packed=worker.pack_feedback(workspace, job)
        if name==worker.relations.TASK:
            packed=worker.contracts.pack(workspace,dict(job,evidence=packed['evidence']))
        packed=worker.retention.pack(workspace,job['allowed_files'],packed,row['worker']['stages'][0]['edited_symbols'])
        record=worker.tracing.capture(workspace,Path(job['harness']),job['harness_hash'],output/name,
                                     Path(job['test_python']),name,packed['evidence'])
        equivalent=worker.tracing.equivalent(row['worker']['public_checks']['candidate']['observation'],record)
        assert equivalent
        cap=min(1700,6000-sum(len(r['content']) for r in packed['evidence']))
        diagnostic=worker.tracing.pack(record,cap)
        rows.append({'task_id':name,'ordinary_equivalent':equivalent,'captured_events':len(record['parameter_trace']),
                     'available_chars':cap,'diagnostic':diagnostic})
    report={'complete':len(rows)==2,'model_calls':0,'private_grader_calls':0,'rows':rows,
            'adapter_hashes':{p.relative_to(ROOT).as_posix():worker.repair.audit.sha(p)
                              for p in (Path(__file__),Path(worker.tracing.__file__))}}
    (output/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(rows),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args().output.resolve())
