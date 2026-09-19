"""Run the workbench: a local web page to compare art, recipes and frames, and drive the tools.

    mint serve [--port 8300] [--host 127.0.0.1] [--open]

Needs the [web] extra (pip install -e .[web]). The page is read from the
workspace: its sets, the art cache with every variant, and the render
manifests under out/<set code>/. Restyles, enhances and renders run as jobs
on one worker thread and stream their progress to the page.
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
    a = ap.parse_args(argv)
    try:
        import uvicorn

        from .web.server import create_app
    except ImportError:
        sys.exit("the workbench needs fastapi and uvicorn: pip install -e '.[web]'")
    ws = workspace.default()
    app = create_app(ws)
    url = f"http://{a.host}:{a.port}/"
    print(f"workbench on {url}  (workspace {ws.home})")
    if a.open:
        webbrowser.open(url)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
