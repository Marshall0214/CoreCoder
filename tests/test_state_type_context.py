import pytest

from docs.experiments import state_type_context_v1 as context
from docs.experiments.state_type_repair_v1 import run, trial_config
from docs.experiments.function_index_audit_v1 import FunctionIndex


@pytest.mark.parametrize('description,expect_state', [('flag_value must activate only valid input', True),
                                                       ('Environment input must work', False)])
def test_state_producer_and_runtime_converter_not_annotation(tmp_path, monkeypatch, description, expect_state):
    source = '''import types_impl as types
class Option:
    def __init__(self, flag_value=None):
        self.type: types.ParamType = None
        self.default = False
        self.is_bool = isinstance(self.type, types.BoolParamType)
        self.flag_value = flag_value
        self.unrelated = "not required"
    def resolve_envvar_value(self, ctx):
        return self.flag_value
'''
    (tmp_path / 'app.py').write_text(source)
    (tmp_path / 'types_impl.py').write_text('class ParamType:\n    def convert(self, value):\n        return value\nclass BoolParamType(ParamType):\n    def convert(self, value):\n        return value == "true"\n')
    allowed = ['app.py', 'types_impl.py']
    index = FunctionIndex(tmp_path, allowed)
    index.refresh()
    info = index.parsed['app.py']
    start, end, _ = info['symbols']['Option.resolve_envvar_value']
    row = dict(path='app.py', symbol='Option.resolve_envvar_value', start_line=start, end_line=end,
               content=''.join(info['lines'][start-1:end]), content_hash=info['hash'],
               symbol_range=[start, end], complete_symbol=True, reason='public_factory_class_method')
    monkeypatch.setattr(context.previous, 'retrieve', lambda *args: {
        'evidence': [row], 'metadata': {'public_api_owners': ['Option']}})
    result = context.retrieve(tmp_path, allowed, description, 'option(flag_value="UPPER")')
    symbols = {r['symbol'] for r in result['evidence']}
    assert ('Option.__init__' in symbols) is expect_state
    assert ('BoolParamType.convert' in symbols) is expect_state
    assert 'ParamType.convert' not in symbols
    assert len(result['evidence']) <= 5 and result['metadata']['chars'] <= 6000
    for r in result['evidence']:
        assert r['content'] in (tmp_path / r['path']).read_bytes().decode('utf-8')
    if expect_state:
        constructor = next(r for r in result['evidence'] if r['symbol'] == 'Option.__init__')
        assert 'self.default = False' in constructor['content']
        assert 'self.flag_value = flag_value' in constructor['content']
        assert 'unrelated' not in constructor['content']
        assert not constructor['complete_symbol']


def test_runner_scope_and_original_budget(tmp_path):
    with pytest.raises(ValueError, match='Only the envvar failure'):
        run(tmp_path / 'output', 'full')
    assert not (tmp_path / 'output').exists()
    c = trial_config('deepseek-high')
    assert (c.token_budget, c.max_output_tokens, c.context_tokens, c.wall_timeout) == (60000, 32768, 65536, 1200)
