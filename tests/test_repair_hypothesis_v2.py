import json

import pytest

from docs.experiments import repair_hypothesis_v2 as planning
from tests.test_repair_hypothesis import CODE, evidence, observation, proposal


def test_existing_public_regression_reference_is_allowed(tmp_path):
    (tmp_path/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    value=proposal()
    value['hypotheses'].append(dict(value['hypotheses'][0],tests=['Contract.test_default'],claim='Preserve existing default behavior.'))
    patch,hypotheses=planning.validate(json.dumps(value),evidence(tmp_path),planning.diagnose(CODE,observation()))
    assert json.loads(patch)['edits']==value['edits'] and len(hypotheses)==2


@pytest.mark.parametrize('tests,error',[(['Contract.test_default'],'not covered'),(['Unknown.test_default'],'Unknown')])
def test_regression_claim_cannot_replace_required_failures(tmp_path,tests,error):
    (tmp_path/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    value=proposal(); value['hypotheses'][0]['tests']=tests
    with pytest.raises(planning.InvalidHypothesis,match=error):
        planning.validate(json.dumps(value),evidence(tmp_path),planning.diagnose(CODE,observation()))

