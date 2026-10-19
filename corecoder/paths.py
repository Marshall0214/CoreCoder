"""Optional application state directory; preserve upstream locations by default."""
import os
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get('CORECODER_HOME')
    return Path(override).expanduser().resolve() if override else Path.home() / '.corecoder'


def history_path() -> Path:
    return state_dir() / 'history' if os.environ.get('CORECODER_HOME') else Path.home() / '.corecoder_history'
