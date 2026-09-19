"""Where everything lives.

The *workspace* (MINT_HOME, default: the current directory) holds what is yours
or cached: fonts/, art/, symbols/, sets/, the Scryfall card file and .cache/.
The package itself ships only code and templates. A Workspace is passed to the
library explicitly; the CLI builds one from the environment.

    MINT_HOME    the workspace directory
    MINT_CARDS   the Scryfall bulk file, to share one ~200 MB copy between projects
    COMFY_URL    a ComfyUI server other than http://127.0.0.1:8188

A mint.toml in the workspace sets the rest -- who you are on the cards, and
the printer -- and the environment overrides it:

    maker = "narfman0"          # collector line
    maker_code = "BLS"          # studio code; set codes default to <code>1
    comfy_url = "http://127.0.0.1:8188"
    printer = "EPSON_ET_8500"   # CUPS queue for `mint print`
"""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Workspace:
    home: Path
    cards_file: Path
    maker: str = "narfman0"      # printed on every card's collector line
    maker_code: str = "BLS"      # the studio code; set codes default to <code>1
    comfy_url: str = "http://127.0.0.1:8188"
    printer: str = "EPSON_ET_8500"

    CONFIG = "mint.toml"
    KEYS = ("maker", "maker_code", "comfy_url", "printer")

    @classmethod
    def from_env(cls, home=None):
        home = Path(home or os.environ.get("MINT_HOME") or os.getcwd()).resolve()
        cards = Path(os.environ.get("MINT_CARDS") or home / "oracle-cards.jsonl")
        conf = {k: v for k, v in read_config(home / cls.CONFIG).items() if k in cls.KEYS}
        if os.environ.get("COMFY_URL"):
            conf["comfy_url"] = os.environ["COMFY_URL"]
        return cls(home, cards, **conf)

    @property
    def art(self):
        return self.home / "art"

    @property
    def fonts(self):
        return self.home / "fonts"

    @property
    def symbols(self):
        return self.home / "symbols"

    @property
    def sets(self):
        return self.home / "sets"

    @property
    def cache(self):
        return self.home / ".cache"

    def path(self, *parts):
        return self.home.joinpath(*parts)


def read_config(path):
    if not Path(path).exists():
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:  # 3.10
        import tomli as tomllib
    with open(path, "rb") as f:
        return tomllib.load(f)


_default = None


def default():
    """The workspace the CLI uses, built once from the environment."""
    global _default
    if _default is None:
        _default = Workspace.from_env()
    return _default
