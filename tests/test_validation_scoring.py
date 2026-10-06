"""The corrected scorer enforces the public exception type, not private wording."""

import importlib.util
import io
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from docs.experiments import validation_rescore_v2 as rescore


def color_check():
    path = Path(rescore.__file__).parent / 'validation_checks_v2/click-style-color-validation/test_admission.py'
    spec = importlib.util.spec_from_file_location('corrected_color_checks', path)
    module = importlib.util.module_from_spec(spec)
    fake = ModuleType('click')
    fake.style = lambda *args, **kwargs: None
    with patch.dict('sys.modules', {'click': fake}):
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('message', ['', 'Palette index must be valid', 'RGB component invalid'])
def test_invalid_color_accepts_any_value_error_message(message):
    module = color_check()
    with patch.object(module.click, 'style', side_effect=ValueError(message)):
        result = unittest.TextTestRunner(stream=io.StringIO()).run(
            module.Target('test_invalid_colors_raise_value_error'))
    assert result.wasSuccessful()


@pytest.mark.parametrize('outcome', [TypeError('bad'), KeyError('bad'), 'accepted'])
def test_invalid_color_rejects_wrong_exception_or_acceptance(outcome):
    module = color_check()
    kwargs = {'return_value': outcome} if isinstance(outcome, str) else {'side_effect': outcome}
    with patch.object(module.click, 'style', **kwargs):
        result = unittest.TextTestRunner(stream=io.StringIO()).run(
            module.Target('test_invalid_colors_raise_value_error'))
    assert not result.wasSuccessful()


def test_correction_only_removes_message_constraint():
    base = Path(rescore.__file__).parent
    old = (base / 'validation_checks_v1/click-style-color-validation/test_admission.py').read_text(encoding='utf-8')
    new = (base / 'validation_checks_v2/click-style-color-validation/test_admission.py').read_text(encoding='utf-8')
    assert new == old.replace("except ValueError as exc:\n                        self.assertIn('Unknown color', str(exc))",
                              'except ValueError:\n                        pass')


def test_rescore_cannot_write_inside_saved_experiment(tmp_path):
    with pytest.raises(ValueError, match='outside the saved experiment'):
        rescore.run(tmp_path, tmp_path / 'admission.json', tmp_path / 'nested')
