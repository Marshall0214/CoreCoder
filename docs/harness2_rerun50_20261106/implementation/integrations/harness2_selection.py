"""Opt-in delivery policy based only on frozen public validation receipts, never grades."""
from pathlib import Path

from evals.runner import digest, snapshot
from integrations import harness2 as bridge
from integrations.harness2_feedback import verify_options
from repairflow.patch_validator import group_passed

POLICY = 'public-preserve-v1'
PRIORITY = ('agg1', 'base1', 'inv1', 'dom1')


def select(rollouts, official_label, public_hash, source_hash, config):
    """Prefer a publicly accepted final, otherwise a publicly accepted existing probe.

    This is a separate controller policy, not an upstream selector vote or independent
    correctness guarantee. No model calls, private-test paths, grades or learned ranking.
    """
    verify_options(config)
    checks_hash = digest(snapshot(Path(config['checks'])))
    rows, folders = {}, {}
    for rollout in rollouts:
        label, folder = rollout['label'], Path(rollout['folder'])
        if label not in PRIORITY or label in rows:
            raise ValueError('Require unique declared PPC rollout labels')
        row = {'public_accepted': False, 'folder': str(folder)}
        rows[label], folders[label] = row, folder
        try:
            job = bridge.read(folder / 'job.json')
            if (job['public_sha256'] != public_hash or job['source_hash'] != source_hash or
                    job['public_feedback'] != config or bridge.sha(folder / 'public.json') != public_hash):
                raise ValueError('Task, source or public-check configuration mismatch')
            final = folder / 'feedback'
            report = bridge.read(final / 'report.json')
            protocol = bridge.read(final / 'protocol.json')
            if (protocol['baseline_hash'] != source_hash or protocol['public_checks_hash'] != checks_hash or
                    protocol['source_root'] != config.get('source_root', '.')):
                raise ValueError('Feedback protocol mismatch')
            if digest(snapshot(final / 'workspace')) != report['final_candidate_hash']:
                raise ValueError('Final candidate changed after public validation')
            if (report['status'] != 'ready_for_review' or report['accepted'] is not True or
                    report['original_inputs_unchanged'] is not True):
                row['reason'] = 'Public checks not accepted at termination'
                continue
            receipts = [final / 'validation-000/report.json', *sorted(final.glob('rounds/*/validation/report.json'))]
            for path in receipts:
                if not path.exists():
                    continue
                receipt = bridge.read(path)
                if (receipt.get('candidate_hash') == report['final_candidate_hash'] and
                        receipt.get('baseline_hash') == source_hash and receipt.get('public_checks_hash') == checks_hash and
                        receipt.get('status') == 'validated' and receipt.get('accepted') is True and
                        receipt.get('independent_grading_used') is False and
                        all(group_passed(receipt.get('public_checks', {}).get(group, {}))
                            for group in ('Reproduce', 'Preserve'))):
                    row.update(public_accepted=True, validation_receipt=str(path))
                    break
            if not row['public_accepted']:
                row['reason'] = 'Missing matching nonempty public validation receipt'
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['reason'] = str(exc)
            row['integrity_error'] = True

    chosen = next((label for label in PRIORITY if rows.get(label, {}).get('public_accepted')), None)
    # No successful probe is fabricated. A valid official failure can still be independently graded.
    if chosen is None and official_label in rows and not rows[official_label].get('integrity_error'):
        chosen = official_label
    return {'policy': POLICY, 'official_label': official_label, 'chosen_label': chosen,
            'chosen_folder': str(folders[chosen]) if chosen else None, 'candidates': rows,
            'independent_grading_used': False, 'model_calls': 0,
            'changed_delivery': chosen != official_label, 'not_upstream_selector_vote': True}
