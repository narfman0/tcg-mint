"""`mint serve --stop`: the pid file under .cache/ and what stopping does with it."""
import subprocess
import sys

import pytest

from mint import serve, workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("MINT_HOME", str(tmp_path))
    monkeypatch.setattr(workspace, "_default", None)
    return workspace.default()


def test_stop_without_a_record_says_so(ws, capsys):
    assert serve.main(["--stop", "--port", "1"]) == 1
    assert "no workbench is recorded" in capsys.readouterr().err


def test_stop_drops_a_stale_record(ws, capsys):
    ws.cache.mkdir()
    serve.pidfile(ws).write_text("999999999 8300\n")  # beyond pid_max: never a live process
    assert serve.main(["--stop"]) == 0
    assert "already gone" in capsys.readouterr().out
    assert not serve.pidfile(ws).exists()


def test_stop_ends_the_recorded_process(ws, capsys):
    # detached through a shell, as `nohup mint serve &` leaves it: init reaps it, so it is not a
    # zombie of this process (which os.kill(pid, 0) would still count as alive)
    sleeper = f"{sys.executable} -c 'import time; time.sleep(60)' >/dev/null 2>&1 & echo $!"
    pid = int(subprocess.check_output(["sh", "-c", sleeper]))
    assert serve.alive(pid)
    ws.cache.mkdir()
    serve.pidfile(ws).write_text(f"{pid} 8300\n")
    assert serve.main(["--stop"]) == 0
    assert not serve.alive(pid)
    assert "stopped the workbench on port 8300" in capsys.readouterr().out
    assert not serve.pidfile(ws).exists()
