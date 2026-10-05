import hashlib

import pytest

from evals.symbol_context import parse_source
from evals.symbol_link_audit import audit
from evals.symbol_links import constructor_aliases, resolve_link


def parse(text):
    return parse_source('module.py', text.encode(), {})


def test_module_constructor_alias_resolves_class_and_method_without_execution():
    info = parse('raise RuntimeError("do not execute")\nclass TextType:\n'
                 '    def convert(self, value): return str(value)\nTOKEN: TextType = TextType()\n')
    aliases = constructor_aliases(info)
    assert aliases['TOKEN']['binding_range'] == [4, 4]
    assert resolve_link(info, 'TOKEN', aliases)['symbol'] == 'TextType'
    assert resolve_link(info, 'TOKEN.convert', aliases)['symbol'] == 'TextType.convert'
    assert resolve_link(info, 'UNKNOWN', aliases) is None


@pytest.mark.parametrize('tail', [
    'TOKEN = TextType()\nTOKEN = None\n',
    'TOKEN = TextType()\nif unknown:\n    TOKEN = None\n',
    'if unknown:\n    TOKEN = TextType()\n',
    'TOKEN = factory()\n',
    'TOKEN = OTHER = TextType()\n',
])
def test_ambiguous_dynamic_or_conditional_bindings_are_not_resolved(tail):
    info = parse('class TextType: pass\n' + tail)
    assert not constructor_aliases(info)


def test_audit_records_missing_constructor_assignment_and_factory_alias(tmp_path):
    text = ('raise RuntimeError("never execute")\nclass TextType:\n'
            '    def convert(self, value): return str(value)\nTOKEN = TextType()\n'
            'def factory():\n    return TOKEN\nclass Service:\n'
            '    def __init__(self):\n        self.type = factory()\n')
    (tmp_path / 'module.py').write_bytes(text.encode())
    version = hashlib.sha256(text.encode()).hexdigest()
    evidence = [{'path': 'module.py', 'symbol': 'factory', 'start_line': 5, 'end_line': 6, 'content_hash': version},
                {'path': 'module.py', 'symbol': 'Service.__init__', 'start_line': 8, 'end_line': 8,
                 'content_hash': version}]
    report = audit(tmp_path, evidence, ['module.py'])
    edge = next(row for row in report['edges'] if row['alias'] == 'TOKEN')
    assert edge['to'] == ['module.py', 'TextType'] and edge['binding_displayed'] is False
    assignment = report['attribute_assignments'][0]
    assert assignment['attribute'] == 'self.type' and assignment['displayed'] is False
    assert any(row['symbol'] == 'TextType' and not row['fully_displayed'] for row in report['nodes'])
    assert not report['limited'] and (tmp_path / 'module.py').read_text() == text
    limited = audit(tmp_path, evidence, ['module.py'], max_nodes=1)
    assert limited['limited'] and len(limited['nodes']) == 1


def test_audit_rejects_stale_evidence_and_escaped_paths(tmp_path):
    (tmp_path / 'module.py').write_text('def run(): return 1\n')
    with pytest.raises(ValueError, match='version changed'):
        audit(tmp_path, [{'path': 'module.py', 'content_hash': 'stale'}], ['module.py'])
    with pytest.raises(ValueError, match='Unsafe'):
        audit(tmp_path, [], ['../escape.py'])
    assert constructor_aliases(parse('def broken(:')) == {}
