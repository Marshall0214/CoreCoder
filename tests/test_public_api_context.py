import pytest

from docs.experiments.public_api_context_v1 import retrieve
from docs.experiments.public_api_repair_v1 import run, trial_config


def test_factory_methods_super_and_typed_receiver_are_retrieved_without_executing_tests(tmp_path):
    source = '''class Context:
    def lookup_default(self, name):
        return False
class Parameter:
    def get_default(self, ctx: Context):
        return ctx.lookup_default('fast')
class Option(Parameter):
    def __init__(self, show_default=False):
        self.show_default = show_default
    def get_default(self, ctx: Context):
        return super().get_default(ctx)
    def get_help_record(self, ctx: Context):
        return str(self.get_default(ctx))
def option(**kwargs):
    return Option(**kwargs)
def command():
    return None
'''
    (tmp_path / 'app.py').write_text(source)
    public = "raise RuntimeError('must never execute')\noption(show_default=True)"
    packed = retrieve(tmp_path, ['app.py'], 'Help must display the effective default. Preserve command-line behavior.', public)
    symbols = {r['symbol'] for r in packed['evidence']}
    assert {'Option.get_help_record', 'Option.get_default', 'Parameter.get_default', 'Context.lookup_default'} <= symbols
    assert all(r['reason'] == 'keyword_fallback' for r in packed['evidence'] if r['symbol'] == 'command')
    assert packed['metadata']['chars'] <= 6000 and len(packed['evidence']) <= 5


def test_imported_factory_class_and_base_are_resolved(tmp_path):
    (tmp_path / 'api.py').write_text('from model import Option\ndef option(**kwargs):\n    return Option(**kwargs)\n')
    (tmp_path / 'model.py').write_text('class Parameter:\n    def resolve_envvar_value(self, ctx):\n        return None\nclass Option(Parameter):\n    def __init__(self, flag_value=None):\n        pass\n    def resolve_envvar_value(self, ctx):\n        return super().resolve_envvar_value(ctx)\n    def value_from_envvar(self, ctx):\n        return self.resolve_envvar_value(ctx)\n')
    packed = retrieve(tmp_path, ['api.py', 'model.py'], 'Environment-variable flags must distinguish activation.', 'option(flag_value="UPPER", envvar="MODE")')
    symbols = {r['symbol'] for r in packed['evidence']}
    assert {'Option.resolve_envvar_value', 'Option.value_from_envvar', 'Parameter.resolve_envvar_value'} <= symbols


def test_no_factory_owner_is_guessed_from_an_unresolved_call(tmp_path):
    (tmp_path / 'app.py').write_text('class Option:\n    def get_help(self):\n        return "ok"\ndef fallback():\n    return 0\n')
    packed = retrieve(tmp_path, ['app.py'], 'help must work', 'unknown_option(show_default=True)')
    assert packed['metadata']['public_api_owners'] == []


def test_runner_only_allows_two_failures_and_preserves_limits(tmp_path):
    with pytest.raises(ValueError, match='two flag failures'):
        run(tmp_path / 'output', 'full')
    c = trial_config('deepseek-high')
    assert c.token_budget == 60000 and c.max_output_tokens == 32768
    assert c.context_tokens == 65536 and c.wall_timeout == 1200
