"""Finite LangGraph orchestration around the existing execution/grading boundary."""

import json
import time
from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from evals.runner import run_task


class RepairPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    task_id: str
    allowed_files: list[str]
    mode: str
    token_budget: int = Field(gt=0)
    attempt_limit: Literal[1] = 1
    actions: tuple[Literal['execute_and_verify'], Literal['review_outcome']] = ('execute_and_verify', 'review_outcome')


class RepairState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    plan: RepairPlan | None = None
    report: dict | None = None
    outcome: Literal['pending', 'accepted', 'rejected'] = 'pending'


def run_workflow(task, config, output: Path, execute=run_task):
    """One execution, no retries and no resumption of interrupted side effects."""
    output = Path(output).resolve()
    if output.is_relative_to(task.root.resolve()):
        raise ValueError('Workflow output cannot be inside task fixtures')
    if (output / 'workflow.json').exists():
        raise ValueError('Workflow already has a snapshot; use a new task instead of replaying execution')
    output.mkdir(parents=True, exist_ok=True)
    snapshot = {'schema_version': 1, 'workflow': 'langgraph-v1', 'stage': 'initial', 'plan': None,
                'outcome': 'pending', 'events': [], 'report': None}

    def record(stage, **changes):
        snapshot.update(stage=stage, **changes)
        snapshot['events'].append({'id': len(snapshot['events']) + 1, 'stage': stage, 'time': time.time()})
        temporary = output / 'workflow.tmp'
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(output / 'workflow.json')

    def plan_node(state: RepairState):
        plan = RepairPlan(task_id=task.task_id, allowed_files=list(task.allowed_files), mode=config.mode,
                          token_budget=config.token_budget)
        record('planned', plan=plan.model_dump())
        return {'plan': plan}

    def execute_node(state: RepairState):
        record('executing')
        report = execute(task, config, output / 'runs')
        record('reviewing', report={k: report.get(k) for k in ('status', 'accepted', 'verification', 'metrics')})
        return {'report': report}

    def route(state: RepairState):
        report = state.report or {}
        accepted = (report.get('status') == 'passed' and report.get('accepted') is True
                    and (report.get('verification') or {}).get('passed') is True)
        return 'accept' if accepted else 'reject'

    def accept_node(state: RepairState):
        record('succeeded', outcome='accepted')
        return {'outcome': 'accepted'}

    def reject_node(state: RepairState):
        record('failed', outcome='rejected')
        return {'outcome': 'rejected'}

    graph = StateGraph(RepairState)
    for name, node in [('plan', plan_node), ('execute_and_verify', execute_node), ('accept', accept_node), ('reject', reject_node)]:
        graph.add_node(name, node)
    graph.add_edge(START, 'plan')
    graph.add_edge('plan', 'execute_and_verify')
    graph.add_conditional_edges('execute_and_verify', route, {'accept': 'accept', 'reject': 'reject'})
    graph.add_edge('accept', END)
    graph.add_edge('reject', END)
    try:
        state = graph.compile().invoke({}, config={'recursion_limit': 5})
        report = dict(state['report'])
        report['accepted'] = state['outcome'] == 'accepted'
        if not report['accepted'] and report.get('status') == 'passed':
            report['status'] = 'failed_verification'
        return report
    except Exception as exc:
        record('error', error_type=type(exc).__name__)
        raise
