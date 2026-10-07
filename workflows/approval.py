"""Durable, opt-in approval with no replay of started repair side effects."""

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from evals.runner import run_task
from workflows.repair import RepairPlan


class ApprovalState(TypedDict, total=False):
    plan: dict
    decision: str
    report: dict
    outcome: str


def run_approval_workflow(task, config, output: Path, decision: Literal['approve', 'reject'] | None = None,
                          execute=run_task):
    """Resume only a saved approval interrupt; never retry started execution."""
    if decision not in {None, 'approve', 'reject'}:
        raise ValueError('Unknown approval decision')
    output = Path(output).resolve()
    if output.is_relative_to(task.root.resolve()):
        raise ValueError('Workflow output cannot be inside task fixtures')
    output.mkdir(parents=True, exist_ok=True)
    snapshot_path = output / 'workflow.json'
    identity = hashlib.sha256(json.dumps({'task': str(task.root.resolve()), 'config': config.to_dict(),
                                         'allowed_files': list(task.allowed_files)}, sort_keys=True).encode()).hexdigest()
    if snapshot_path.exists():
        snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
        if snapshot.get('workflow') != 'langgraph-approval-v1' or snapshot.get('request_hash') != identity:
            raise ValueError('Workflow checkpoint belongs to another request')
    else:
        snapshot = {'schema_version': 2, 'workflow': 'langgraph-approval-v1', 'request_hash': identity,
                    'stage': 'initial', 'plan': None, 'decision': None, 'outcome': 'pending', 'events': [], 'report': None}

    def record(stage, **changes):
        snapshot.update(stage=stage, **changes)
        snapshot['events'].append({'id': len(snapshot['events']) + 1, 'stage': stage, 'time': time.time()})
        temporary = output / 'workflow.tmp'
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(snapshot_path)

    def plan_node(state):
        plan = RepairPlan(task_id=task.task_id, allowed_files=list(task.allowed_files), mode=config.mode,
                          token_budget=config.token_budget).model_dump(mode='json')
        record('planned', plan=plan)
        return {'plan': plan, 'outcome': 'pending'}

    def approval_node(state):
        # No side effects before interrupt: this node restarts on Command(resume=...).
        answer = interrupt({'plan': state['plan'], 'choices': ['approve', 'reject']})
        if answer not in {'approve', 'reject'}:
            raise ValueError('Unknown approval decision')
        record('approved' if answer == 'approve' else 'rejected', decision=answer)
        return {'decision': answer}

    def execute_node(state):
        # Exclusive creation is a durable claim, not an exactly-once transaction with run_task.
        # A crash after claiming intentionally blocks a retry, even if no work was completed.
        with (output / 'execution-started').open('x', encoding='utf-8') as marker:
            marker.write('Do not replay this execution.\n')
        record('executing')
        report = execute(task, config, output / 'runs')
        accepted = (report.get('status') == 'passed' and report.get('accepted') is True
                    and (report.get('verification') or {}).get('passed') is True)
        report = dict(report, accepted=accepted)
        if not accepted and report.get('status') == 'passed':
            report['status'] = 'failed_verification'
        record('reviewing', report={k: report.get(k) for k in ('status', 'accepted', 'verification', 'metrics')})
        return {'report': report, 'outcome': 'accepted' if accepted else 'rejected'}

    def finish_node(state):
        record('succeeded' if state['outcome'] == 'accepted' else 'failed', outcome=state['outcome'])
        return {}

    def reject_node(state):
        record('rejected', outcome='rejected')
        return {'report': {'status': 'approval_rejected', 'accepted': False}, 'outcome': 'rejected'}

    graph = StateGraph(ApprovalState)
    for name, node in [('plan', plan_node), ('approval', approval_node), ('execute_and_verify', execute_node),
                       ('finish', finish_node), ('reject', reject_node)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'plan')
    graph.add_edge('plan', 'approval')
    graph.add_conditional_edges('approval', lambda state: state['decision'],
                                {'approve': 'execute_and_verify', 'reject': 'reject'})
    graph.add_edge('execute_and_verify', 'finish')
    graph.add_edge('finish', END)
    graph.add_edge('reject', END)
    invocation = {'configurable': {'thread_id': output.name}, 'recursion_limit': 8}
    with closing(sqlite3.connect(output / 'checkpoints.sqlite3', check_same_thread=False)) as db:
        saver = SqliteSaver(db, serde=JsonPlusSerializer(allowed_msgpack_modules=[]))
        compiled = graph.compile(checkpointer=saver)
        saved = compiled.get_state(invocation)
        if saved.values and not saved.next:
            if decision is not None and decision != saved.values.get('decision'):
                raise ValueError('Workflow already has another approval decision')
            return saved.values['report']
        if (output / 'execution-started').exists():
            raise ValueError('Execution has already started; create a new task instead of replaying it')
        if decision is not None:
            if saved.next != ('approval',) or not any(t.interrupts for t in saved.tasks):
                raise ValueError('Workflow is not awaiting approval')
            input_state = Command(resume=decision)
        elif saved.values:
            if saved.next != ('approval',) or not any(t.interrupts for t in saved.tasks):
                raise ValueError('Incomplete workflow cannot be automatically replayed')
            return {'status': 'awaiting_approval', 'accepted': False}
        else:
            input_state = {}
        try:
            state = compiled.invoke(input_state, config=invocation)
            if state.get('__interrupt__'):
                record('awaiting_approval')
                return {'status': 'awaiting_approval', 'accepted': False}
            return state['report']
        except Exception as exc:
            record('error', error_type=type(exc).__name__)
            raise
