"""Run the workbench: a local web page to compare art, recipes and frames, and drive the tools.

    mint serve [--port 8300] [--host 127.0.0.1] [--open] [--reload]

Needs the [web] extra (pip install -e .[web]). The page is read from the
workspace: its sets, the art cache with every variant, and the render
manifests under out/<set code>/. Restyles, enhances and renders run as jobs
on one worker thread and stream their progress to the page. --reload restarts
the server when the package's code changes (the page itself is read from disk
on every request; a browser refresh is enough for it) -- for hacking on the
workbench; a running job is lost on a restart.
"""
import argparse
import sys
import webbrowser

from . import workspace


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint serve", description=__doc__.split("\n\n")[0])
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true", help="open the page in a browser")
    ap.add_argument("--reload", action="store_true", help="restart when the code changes (development)")
    a = ap.parse_args(argv)
    try:
        import uvicorn

        from .web.server import create_app
    except ImportError:
        sys.exit("the workbench needs fastapi and uvicorn: pip install -e '.[web]'")
    ws = workspace.default()
    url = f"http://{a.host}:{a.port}/"
    print(f"workbench on {url}  (workspace {ws.home})" + ("  -- reloading on code changes" if a.reload else ""))
    if a.open:
        webbrowser.open(url)
    if a.reload:  # uvicorn's reloader needs an import string; the factory rebuilds the app from the environment
        from . import PKG
        # a page's event stream (/api/events) never closes on its own, and uvicorn waits for open
        # connections before restarting: without a limit a reload hangs for as long as a tab is open
        uvicorn.run("mint.web.server:app", factory=True, host=a.host, port=a.port, log_level="warning",
                    reload=True, reload_dirs=[str(PKG)], timeout_graceful_shutdown=3)
    else:
        uvicorn.run(create_app(ws), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
