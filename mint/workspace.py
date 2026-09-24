"""Where everything lives.

The *workspace* (MINT_HOME, default: the current directory) holds what is yours
or cached: fonts/, art/, symbols/, sets/, styles/, the Scryfall card file and
.cache/. The package itself ships only code and templates.

sets/ and styles/ are yours: the repo ignores both (docs/examples/ shows the
shapes). A Workspace is passed to the library explicitly; the CLI builds one
from the environment.

    MINT_HOME    the workspace directory
    MINT_CARDS   the Scryfall bulk file, to share one ~200 MB copy between projects
    COMFY_URL    a ComfyUI server other than http://127.0.0.1:8188
    COMFY_TOKEN  a bearer token that server wants on every request (a ComfyUI behind an
                 authenticating proxy, on a GPU host elsewhere); unset for a local one

A mint.toml in the workspace sets the rest -- who you are on the cards, and
the printer -- and the environment overrides it:

    maker = "narfman0"          # collector line
    maker_code = "BLS"          # studio code; set codes default to <code>1
    comfy_url = "http://127.0.0.1:8188"
    comfy_token = ""            # better in the environment (COMFY_TOKEN) than in a file
    printer = "EPSON_ET_8500"   # CUPS queue for `mint print`
    describer = "claude"        # who reads a card's picture for `mint describe`: claude | ollama
    describe_model = ""         # its model; empty = the describer's default (describe.py)
    ollama_url = "http://127.0.0.1:11434"

ANTHROPIC_API_KEY in the environment is what the claude describer sends.
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
    comfy_token: str = ""        # sent as `Authorization: Bearer` when set; a remote ComfyUI behind a proxy wants one
    printer: str = "EPSON_ET_8500"
    export_dir: str = "~/Desktop"  # where the workbench's pdf page exports a PDF to, for another app to print
    describer: str = "claude"      # the vision model behind `mint describe`: claude (the API) or ollama (local)
    describe_model: str = ""       # its model name; empty = the describer's default
    ollama_url: str = "http://127.0.0.1:11434"
    # the ComfyUI checkout itself, when it is on this machine. Only `mint doctor` wants it, and
    # only for the weights a node pack downloads for itself: those never appear in the node's
    # options list (it offers every name it could fetch), so the server cannot be asked.
    comfy_root: str = ""

    CONFIG = "mint.toml"
    KEYS = ("maker", "maker_code", "comfy_url", "comfy_token", "printer", "export_dir", "describer", "describe_model",
            "ollama_url", "comfy_root")

    @classmethod
    def from_env(cls, home=None):
        home = Path(home or os.environ.get("MINT_HOME") or os.getcwd()).resolve()
        cards = Path(os.environ.get("MINT_CARDS") or home / "oracle-cards.jsonl")
        conf = {k: v for k, v in read_config(home / cls.CONFIG).items() if k in cls.KEYS}
        if os.environ.get("COMFY_URL"):
            conf["comfy_url"] = os.environ["COMFY_URL"]
        if os.environ.get("COMFY_TOKEN"):
            conf["comfy_token"] = os.environ["COMFY_TOKEN"]
        if os.environ.get("COMFY_ROOT"):
            conf["comfy_root"] = os.environ["COMFY_ROOT"]
        return cls(home, cards, **conf)

    @property
    def art(self):
        return self.home / "art"

    @property
    def export_path(self):
        """export_dir with ~ expanded; a relative one lies under the workspace."""
        p = Path(os.path.expanduser(self.export_dir))
        return p if p.is_absolute() else self.home / p

    @property
    def comfy_path(self):
        """The ComfyUI checkout as a Path, or None when it is not set or not there."""
        if not self.comfy_root:
            return None
        p = Path(os.path.expanduser(self.comfy_root))
        return p if p.is_dir() else None

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

    def set_files(self):
        """Every set file, sets/*.json, by name."""
        return sorted(self.sets.glob("*.json"))

    def style_files(self):
        """Every style template, styles/*.json, by name."""
        return sorted(self.styles.glob("*.json"))

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
