"""Where everything lives.

The *workspace* (MINT_HOME, default: the current directory) holds what is yours
or cached: fonts/, art/, symbols/, sets/, styles/, the Scryfall card file and
.cache/. The package itself ships only code and templates.

sets/ and styles/ each have a private/ subdirectory that git ignores (the repo's
.gitignore lists both): a set or a style template there behaves exactly like
one beside it, but never reaches version control. `mint newset --private` and
`mint style save --private` write there. A Workspace is passed to the
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
    def styles(self):
        return self.home / "styles"

    @property
    def cache(self):
        return self.home / ".cache"

    PRIVATE = "private"

    def set_files(self):
        """Every set file: sets/*.json, then sets/private/*.json (a private set never shadows a shared one)."""
        return _tiers(self.sets)

    def style_files(self):
        """Every style template, styles/private/*.json first: a private template shadows a shared one by name."""
        return _tiers(self.styles, private_first=True)

    def is_private(self, path):
        """Whether a set or template path lies in a git-ignored private/ tier."""
        return Path(path).resolve().parent.name == self.PRIVATE

    def path(self, *parts):
        return self.home.joinpath(*parts)


def _tiers(d, private_first=False):
    shared, private = sorted(d.glob("*.json")), sorted((d / Workspace.PRIVATE).glob("*.json"))
    return private + shared if private_first else shared + private


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
