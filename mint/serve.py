"""Run the workbench: a local web page to compare art, recipes and frames, and drive the tools.

    mint serve [--port 8300] [--host 127.0.0.1] [--open] [--reload]
    mint serve --stop

Needs the [web] extra (pip install -e .[web]). The page is read from the
workspace: its sets, the art cache with every variant, and the render
manifests under out/<set code>/. Restyles, enhances and renders run as jobs
on one worker thread and stream their progress to the page. --reload restarts
the server when the package's code changes (the page itself is read from disk
on every request; a browser refresh is enough for it) -- for hacking on the
workbench; a running job is lost on a restart.

While it runs, .cache/serve.pid in the workspace records the process and its
port; `mint serve --stop` ends that server (Ctrl-C does the same in its
terminal). Stopping loses a running job.
"""
import argparse
import os
import signal
import socket
import sys
import time
import webbrowser

from . import workspace

PIDFILE = "serve.pid"


def pidfile(ws):
    return ws.cache / PIDFILE


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def listening(port, host="127.0.0.1"):
    try:
        socket.create_connection((host, port), timeout=0.3).close()
        return True
    except OSError:
        return False


def stop(ws, port):
    """End the workbench .cache/serve.pid records: TERM, then KILL after five seconds. Returns an exit code.
    `port` is only for the hint when nothing is recorded."""
    p = pidfile(ws)
    try:
        pid, on = p.read_text().split()
        pid, on = int(pid), int(on)
    except (OSError, ValueError):  # (a ValueError: a pid file this version did not write)
        print(f"no workbench is recorded for {ws.home} ({p} is missing)", file=sys.stderr)
        if listening(port):
            print(f"something answers on port {port}, started before this workspace recorded one: "
                  f"stop it by hand (pgrep -af 'mint serve')", file=sys.stderr)
        return 1
    if not alive(pid):
        p.unlink(missing_ok=True)
        print(f"the workbench recorded on port {on} (pid {pid}) is already gone")
        return 0
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not alive(pid):
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)
    p.unlink(missing_ok=True)
    print(f"stopped the workbench on port {on} (pid {pid})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint serve", description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="open the page in a browser")
    ap.add_argument("--reload", action="store_true", help="restart when the code changes (development)")
    ap.add_argument("--stop", action="store_true", help="stop the workbench running for this workspace")
    a = ap.parse_args(argv)
    ws = workspace.default()
    if a.stop:
        return stop(ws, a.port)
    try:
        import uvicorn

        from .web.server import create_app
    except ImportError:
        sys.exit("the workbench needs fastapi and uvicorn: pip install -e '.[web]'")
    url = f"http://{a.host}:{a.port}/"
    print(f"workbench on {url}  (workspace {ws.home})" + ("  -- reloading on code changes" if a.reload else ""))
    if a.open:
        webbrowser.open(url)
    ws.cache.mkdir(parents=True, exist_ok=True)
    pidfile(ws).write_text(f"{os.getpid()} {a.port}\n")
    try:
        # a page's event stream (/api/events) never closes on its own, and uvicorn waits for open
        # connections before stopping: without a limit Ctrl-C, --stop and a reload all hang for as
        # long as a tab is open
        if a.reload:  # uvicorn's reloader needs an import string; the factory rebuilds the app from the environment
            from . import PKG
            uvicorn.run("mint.web.server:app", factory=True, host=a.host, port=a.port, log_level="warning",
                        reload=True, reload_dirs=[str(PKG)], timeout_graceful_shutdown=3)
        else:
            uvicorn.run(create_app(ws), host=a.host, port=a.port, log_level="warning", timeout_graceful_shutdown=3)
    finally:
        pidfile(ws).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
