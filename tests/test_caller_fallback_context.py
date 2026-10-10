import pytest

from docs.experiments import caller_fallback_context_v1 as context
from docs.experiments.function_index_audit_v1 import FunctionIndex
from docs.experiments.caller_fallback_repair_v1 import run, trial_config


def test_inherited_consumer_uses_effective_override_and_excludes_unrelated_class(tmp_path, monkeypatch):
    (tmp_path / 'app.py').write_text('''class Parameter:
    def consume(self):
        value = self.from_env()
        return self.get_default() if value is None else value
    def get_default(self):
        return "base"
class Option(Parameter):
    def from_env(self):
        return None
    def get_default(self):
        return "override"
class Other:
    def consume(self):
        return self.from_env()
''')
    index = FunctionIndex(tmp_path, ['app.py'])
    index.refresh()
    info = index.parsed['app.py']
    start, end, _ = info['symbols']['Option.from_env']
    row = dict(path='app.py', symbol='Option.from_env', start_line=start, end_line=end,
               content=''.join(info['lines'][start-1:end]), content_hash=info['hash'],
               symbol_range=[start, end], complete_symbol=True, reason='public_factory_class_method')
    monkeypatch.setattr(context.previous, 'retrieve', lambda *args: {
        'evidence': [row], 'metadata': {'public_api_owners': []}})
    result = context.retrieve(tmp_path, ['app.py'], 'Read environment and preserve defaults')
    symbols = {r['symbol'] for r in result['evidence']}
    assert symbols == {'Option.from_env', 'Parameter.consume', 'Option.get_default'}
    assert len(result['evidence']) <= 5 and result['metadata']['chars'] <= 6000
    for row in result['evidence']:
        assert row['content'] in (tmp_path / row['path']).read_bytes().decode()


def test_repair_runner_keeps_scope_and_budget(tmp_path):
    with pytest.raises(ValueError, match='Only the envvar failure'):
        run(tmp_path / 'output', 'full')
    assert not (tmp_path / 'output').exists()
    c = trial_config('deepseek-high')
    assert (c.token_budget, c.max_output_tokens, c.context_tokens, c.wall_timeout) == (60000, 32768, 65536, 1200)
