import runpy
from pathlib import Path

import pytest

# The standalone container harness must not shadow evals/diagnostics.py.
state_before = runpy.run_path(str(Path(__file__).resolve().parents[1] /
                                'evals/diagnostics/click_style_preservation.py'))['state_before']


@pytest.mark.parametrize('prefix,expected', [
    ('', (None, None, False)),
    ('\x1b[1m\x1b[31m', (31, None, True)),
    ('\x1b[34m\x1b[43m', (34, 43, False)),
    ('\x1b[44m\x1b[31m', (31, 44, False)),
    ('\x1b[31;43;1m\x1b[39m\x1b[22m', (None, 43, False)),
    ('\x1b[31;43;1m\x1b[49m', (31, None, True)),
    ('\x1b[31;43;1m\x1b[0m', (None, None, False)),
    ('\x1b[31m\x1b[m', (None, None, False)),
    ('\x1b[91;104m', (91, 104, False)),
])
def test_probe_oracle_tracks_only_style_active_before_visible_text(prefix, expected):
    # A reset after the marker must not change the style active at the marker.
    state = state_before(prefix + 'probe\x1b[0m')
    assert tuple(state[key] for key in ('foreground', 'background', 'bold')) == expected


def test_probe_oracle_refuses_unsupported_extended_color_and_missing_text():
    with pytest.raises(ValueError, match='does not support'):
        state_before('\x1b[38;5;31mprobe')
    with pytest.raises(ValueError):
        state_before('missing marker')
