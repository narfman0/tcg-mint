"""Build and inspect an order: the batch that goes to the printer as one job.

    mint order                                  list every order, with what each costs
    mint order show october                     the bill of materials, and the bracket
    mint order new october --set slv --set gsh --set ure
    mint order add october --set bls1 [--copies 0]
    mint order drop october --set bls1
    mint order set october SLV "Sol Ring" 2     how many of one card to print
    mint order drop-card october SLV Plains     the same as `set ... 0`
    mint order settings october --stock "(M31) Linen" --dpi 800 --mode styled --foil holo
    mint order rm october

An order is a union of sets (orders.py). It holds only what it *changes* about them -- which sets,
and how many of which cards -- so a card added to a deck is in the order the moment it is in the
set. `mint export --order october` writes the MPC Autofill folder, with each set's cards behind
that set's own back.

`show` is the one worth running before you spend money. MakePlayingCards sells fixed project
sizes, not cards, so an order is billed at the next size up: 283 cards are billed as 396, and the
113 slots you have already paid for are the argument for putting something in them.
"""
import argparse
import sys

from . import orders, workspace
from .errors import MintError


def _bill(ws, o):
    return o, o.bill(orders.loaded_sets(ws, o))


def show(ws, o):
    b = _bill(ws, o)[1]
    head = f"{o.name}  ({o.slug})"
    print(head)
    print("=" * len(head))
    if o.note:
        print(o.note)
    print()
    for r in b["rows"]:
        if r["gone"]:
            print(f"  {r['code']:<6} -- no such set in the workspace any more")
            continue
        back = f"back {r['code']}.png" if r.get("back") else "the common back"
        print(f"  {r['code']:<6} {r['cards']:>4} card(s)  {back:<18} {r['name'] or ''}")
    print()
    print(f"  {'total':<6} {b['total']:>4} card(s)  ->  bracket {b['bracket']}")
    if b["headroom"]:
        print(f"\n{b['headroom']} slot(s) are paid for and empty: MakePlayingCards bills the order at the "
              f"next\nproject size up, so anything you add up to {b['bracket']} costs nothing more.")
    if b["drop"]:
        print(f"Falling back to the {b['under']} bracket would mean {b['drop']} fewer card(s).")
    settings = [f"stock {o.stock}" if o.stock else None, f"{o.dpi} dpi" if o.dpi else None,
                f"{o.mode} renders", f"foil {o.foil}" if o.foil else None]
    print("\n" + ", ".join(x for x in settings if x))
    for p in b["problems"]:
        print(f"warning: {p}")


def listing(ws):
    every = orders.every(ws)
    if not every:
        print("no orders yet: `mint order new <name> --set <code> ...`")
        return
    for o in every:
        if isinstance(o, str):
            print(f"  (broken) {o}")
            continue
        b = o.bill(orders.loaded_sets(ws, o))
        codes = " ".join(e.code for e in o.sets) or "-- empty --"
        print(f"  {o.slug:<16} {b['total']:>4} card(s)  bracket {b['bracket']:<4} {codes}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mint order", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")

    def with_name(p):
        p.add_argument("name", help="the order")
        return p

    sub.add_parser("list", help="every order, with what each costs")
    with_name(sub.add_parser("show", help="the bill of materials, and the bracket"))
    p = with_name(sub.add_parser("new", help="start an order"))
    p.add_argument("--set", action="append", default=[], metavar="CODE", help="a set to put in it; repeatable")
    p.add_argument("--note", help="what this order is for")
    p = with_name(sub.add_parser("add", help="put a set in the order"))
    p.add_argument("--set", required=True, metavar="CODE")
    p.add_argument("--copies", type=int, default=1,
                   help="how many of each of its cards (default 1; 0 = only the cards named by `set`)")
    p = with_name(sub.add_parser("drop", help="take a set out of the order"))
    p.add_argument("--set", required=True, metavar="CODE")
    p = with_name(sub.add_parser("set", help="how many of one card to print"))
    p.add_argument("code", metavar="CODE")
    p.add_argument("card")
    p.add_argument("count", type=int)
    p = with_name(sub.add_parser("drop-card", help="take one card out of the order (the same as `set ... 0`)"))
    p.add_argument("code", metavar="CODE")
    p.add_argument("card")
    p = with_name(sub.add_parser("settings", help="what the order is printed on"))
    p.add_argument("--stock")
    p.add_argument("--dpi", type=int)
    p.add_argument("--mode", choices=orders.MODES)
    p.add_argument("--foil", help="a foil profile, or 'none'")
    p.add_argument("--foil-strength", type=float)
    p.add_argument("--note")
    with_name(sub.add_parser("rm", help="delete the order (the sets and their cards are untouched)"))

    a = ap.parse_args(argv)
    ws = workspace.default()
    try:
        if a.cmd in (None, "list"):
            return listing(ws)
        if a.cmd == "new":
            fn = ws.orders / f"{orders.slug(a.name)}.json"
            if fn.exists():
                raise MintError(f"there is already an order {orders.slug(a.name)!r}; `mint order add` puts a set in it")
            o = orders.Order(name=a.name, note=a.note)
            every = orders.by_code(ws)
            for code in a.set:
                if code.upper() not in every:
                    raise MintError(f"no set with code {code.upper()} in {ws.sets}; `mint check` lists them")
                o.add_set(code)
            orders.save(fn, o)
            print(fn)
            show(ws, o)
            return
        o = orders.find(ws, a.name)
        if a.cmd == "show":
            return show(ws, o)  # None: anything truthy would be `mint`'s exit status
        if a.cmd == "rm":
            o.path.unlink()
            print(f"{o.path} removed; the sets and their cards are untouched")
            return
        if a.cmd == "add":
            if a.set.upper() not in orders.by_code(ws):
                raise MintError(f"no set with code {a.set.upper()} in {ws.sets}; `mint check` lists them")
            o.add_set(a.set, a.copies)
        elif a.cmd == "drop":
            o.drop_set(a.set)
        elif a.cmd == "set":
            o.set_count(a.code, a.card, a.count)
        elif a.cmd == "drop-card":
            o.set_count(a.code, a.card, 0)
        elif a.cmd == "settings":
            for k in ("stock", "dpi", "mode", "note"):
                if getattr(a, k) is not None:
                    setattr(o, k, getattr(a, k))
            if a.foil is not None:
                o.foil = None if a.foil == "none" else a.foil
            if a.foil_strength is not None:
                o.foil_strength = a.foil_strength
        orders.save(o.path, o)
        show(ws, o)
    except MintError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
