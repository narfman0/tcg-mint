"""Errors the library raises. Commands catch MintError and turn it into an exit code;
nothing outside a main() calls sys.exit, so a server or a test can render a list and
report what failed."""


class MintError(Exception):
    """Anything the user can act on: a missing file, an unknown card, a bad set file."""


class CardNotFound(MintError):
    pass


class SetError(MintError):
    pass


class ComfyError(MintError):
    pass
