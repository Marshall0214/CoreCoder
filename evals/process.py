"""Bounded subprocesses and deterministic test invocation."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def terminate_tree(proc: subprocess.Popen):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def test_environment(workspace: Path) -> dict:
    # Do not pass model credentials or inherited Python import hooks to candidate code.
    keys = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keys if k in os.environ}
    env.update(PYTHONPATH=str(workspace), PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    return env


def run_process(command: list[str], cwd: Path, timeout: int, stdout_path: Path, stderr_path: Path,
                env: dict | None = None) -> dict:
    started = time.perf_counter()
    kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    timed_out = False
    with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=out, stderr=err, stdin=subprocess.DEVNULL, **kwargs)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_tree(proc)
        except BaseException:
            terminate_tree(proc)
            raise
    return {"returncode": proc.returncode, "timed_out": timed_out, "seconds": round(time.perf_counter() - started, 4)}


def run_tests(workspace: Path, directory: str, timeout: int, log_root: Path, label: str) -> dict:
    import re

    stdout = log_root / f"{label}.stdout.txt"
    stderr = log_root / f"{label}.stderr.txt"
    result = run_process([sys.executable, "-m", "unittest", "discover", "-s", directory, "-v"], workspace,
                         timeout, stdout, stderr, test_environment(workspace))
    # unittest can exit successfully when it discovers zero tests: never count that as verification.
    text = stderr.read_text(encoding="utf-8", errors="replace")
    count = re.search(r"Ran (\d+) tests?", text)
    result["tests_run"] = int(count.group(1)) if count else 0
    result["passed"] = result["returncode"] == 0 and not result["timed_out"] and result["tests_run"] > 0
    result.update(stdout=stdout.name, stderr=stderr.name)
    return result
