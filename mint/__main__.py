"""`mint <command> ...` -- one entry point, one module per command."""
import sys

from . import __version__

COMMANDS = {
    "newset":    ("start a set file from a decklist", "newset"),
    "render":    ("render cards from a set file or by name", "render"),
    "calibrate": ("compare our text placement against Scryfall scans", "calibrate"),
    "cards":     ("fetch Scryfall's bulk card file", "bulk"),
    "upscale":   ("4x-upscale card art through a local ComfyUI", "upscale"),
    "restyle":   ("regenerate card art in the set's style through ComfyUI", "restyle"),
    "fonts":     ("report which frame fonts are present", "fonts"),
    "back":      ("render the BLS card back", "back"),
    "impose":    ("lay rendered PNGs out 3x3 on a printable PDF", "impose"),
    "print":     ("send a PDF to the printer at true 100%", "printing"),
}


def usage():
    print(f"tcg-mint {__version__}\n\nusage: mint <command> [args]\n")
    for name, (desc, _) in COMMANDS.items():
        print(f"  {name:10} {desc}")
    print("\n`mint <command> -h` for each command's options.")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        usage()
        return 0
    if argv[0] not in COMMANDS:
        sys.exit(f"unknown command {argv[0]!r}\n\n" + (usage() or ""))
    import importlib
    mod = importlib.import_module("." + COMMANDS[argv[0]][1], __package__)
    rc = mod.main(argv[1:])
    return rc or 0


if __name__ == "__main__":
    sys.exit(main())
