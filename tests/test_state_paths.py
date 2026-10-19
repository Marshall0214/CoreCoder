"""Upstream persistence must be relocatable without changing default locations."""
from pathlib import Path

from corecoder.paths import history_path, state_dir


def test_upstream_defaults_preserved(monkeypatch):
    monkeypatch.delenv('CORECODER_HOME', raising=False)
    assert state_dir() == Path.home() / '.corecoder'
    assert history_path() == Path.home() / '.corecoder_history'


def test_override_keeps_state_and_history_in_selected_directory(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_HOME', str(tmp_path / 'state'))
    assert state_dir() == (tmp_path / 'state').resolve()
    assert history_path() == (tmp_path / 'state/history').resolve()
