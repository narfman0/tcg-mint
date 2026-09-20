"""The workbench's routes. `create_app(ws)` returns the FastAPI app; `mint serve` runs it."""
import dataclasses
import json
import os
import queue
import random
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .. import PKG, comfy, frame, newset, render, restyle, sets, style, upscale
from ..art import Art
from ..cards import Cards, default_printing, oddness, warnings
from ..errors import MintError
from ..manifest import Manifest, frame_hash
from .jobs import Jobs
from .thumbs import inside, thumbnail

STATIC = PKG / "web" / "static"


class State:
    def __init__(self, ws):
        self.ws = ws
        self.jobs = Jobs()
        self.art = Art(ws.art)
        self._comfy = (0.0, False)
        self._nodes = (0.0, set())
        self.lock = threading.Lock()  # around set-file writes

    def cards(self):
        return Cards(self.ws.cards_file)  # a SQLite connection per thread

    def comfy(self):
        return comfy.Comfy(self.ws.comfy_url)

    def comfy_alive(self):
        t, alive = self._comfy
        if time.time() - t > 5:
            alive = self.comfy().alive()
            self._comfy = (time.time(), alive)
        return alive

    def comfy_nodes(self):
        """The node types ComfyUI has, asked at most once a minute (the listing is large); empty when down."""
        t, nodes = self._nodes
        if time.time() - t > 60:
            nodes = self.comfy().nodes() if self.comfy_alive() else set()
            self._nodes = (time.time(), nodes)
        return nodes

    def set_paths(self):
        return self.ws.set_files()

    def find_set(self, code):
        for p in self.set_paths():
            try:
                st = sets.load(p)
            except MintError:
                continue
            if st.code.lower() == code.lower():
                return st
        raise HTTPException(404, f"no set with code {code}")

    def codes(self):
        """Every set code in the workspace, lowercased."""
        out = set()
        for p in self.set_paths():
            try:
                out.add(sets.load(p).code.lower())
            except MintError:
                continue
        return out

    def out_dir(self, st):
        return self.ws.home / "out" / st.code.lower()


def variant_dict(v):
    d = v.to_dict()
    d["path"] = str(v.path)
    return d


def source_dict(src):
    return {"kind": src.kind, "path": str(src.path), "hash": src.hash,
            "label": src.variant.label if src.variant else None} if src else None


def card_summary(card):
    keys = ("name", "full_name", "set", "collector_number", "illustration_id", "type_line", "artist", "rarity",
            "mana_cost", "released_at", "layout")
    return {k: card.get(k) for k in keys if k in card}


def create_app(ws):
    app = FastAPI(title="tcg-mint workbench")
    S = State(ws)

    @app.exception_handler(MintError)
    async def mint_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    # --- pages and files -----------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.ico")
    def favicon():
        from fastapi.responses import Response
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect x="2" y="1" width="12" height="14" rx="1.5" '
               'fill="#2160a3" stroke="#0d2b4d"/><rect x="4" y="3" width="8" height="5" fill="#d7e3f1"/></svg>')
        return Response(svg, media_type="image/svg+xml")

    # the PWA's manifest and service worker, at the root so the worker's scope is the whole app
    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/static/{name}")
    def static(name: str):
        p = STATIC / name
        if not p.is_file() or "/" in name:
            raise HTTPException(404)
        return FileResponse(p)

    @app.get("/img")
    def img(path: str, w: int = 320):
        return FileResponse(thumbnail(ws, path, w), headers={"Cache-Control": "max-age=3600"})

    @app.get("/file")
    def file(path: str):
        p = inside(ws, path)
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=60"})

    # --- workspace --------------------------------------------------------------------
    @app.get("/api/workspace")
    def workspace_info():
        out = []
        for p in S.set_paths():
            try:
                st = sets.load(p)
                out.append({"code": st.code, "name": st.name, "path": str(p), "size": st.size, "cards": len(st.cards),
                            "style": st.style.name if st.style else None, "private": ws.is_private(p)})
            except MintError as e:
                out.append({"code": p.stem, "name": "", "path": str(p), "error": str(e)})
        try:
            count = S.cards().count()
        except MintError:
            count = 0
        return {"home": str(ws.home), "maker": ws.maker, "maker_code": ws.maker_code,
                "comfy": {"url": ws.comfy_url, "alive": S.comfy_alive(),
                          # what the inspire mode needs: the ComfyUI_IPAdapter_plus node pack
                          "ipadapter": "IPAdapterUnifiedLoader" in S.comfy_nodes()},
                "cards": {"path": str(ws.cards_file), "count": count},
                "sets": out, "themes": list(frame.THEMES), "controls": list(sets.CONTROLS),
                "style_fields": style_fields(), "frame_fields": frame_fields(), "current_job": S.jobs.current.to_dict() if S.jobs.current else None}

    # --- sets ---------------------------------------------------------------------------
    @app.get("/api/sets/{code}")
    def get_set(code: str):
        st = S.find_set(code)
        return set_detail(S, st)

    @app.post("/api/sets")
    def post_set(body: dict):
        """A new set: code, name, the cards (a decklist text or a list of names), an optional style
        template and tier. An existing code is refused; `mint newset` is the way to append to one."""
        code = (body.get("code") or "").strip().upper()
        if not code.isalnum():
            raise HTTPException(400, "a set code is letters and digits, like SAT")
        if code.lower() in S.codes():
            raise HTTPException(400, f"there is already a set {code}")
        names = card_names(body)
        with S.lock:
            path, st, _ = newset.create(ws, code, body.get("name") or code, names, style_name=body.get("style") or None,
                                        private=bool(body.get("private")))
        return set_detail(S, st)

    @app.patch("/api/sets/{code}")
    def patch_set(code: str, body: dict):
        """The set's own fields: name, code, size, note, art_filter, base (null clears one)."""
        st = S.find_set(code)
        allowed = ("name", "code", "size", "note", "art_filter", "base")
        bad = set(body) - set(allowed)
        if bad:
            raise HTTPException(400, f"not a set field: {', '.join(sorted(bad))}; the editor takes {', '.join(allowed)}")
        with S.lock:
            d = st.to_dict()
            for k, v in body.items():
                if v is None or v == "":
                    d.pop(k, None)
                else:
                    d[k] = v
            if "code" in body:
                d["code"] = str(body.get("code") or "").strip().upper()
                if not d["code"].isalnum():
                    raise HTTPException(400, "a set code is letters and digits, like SAT")
                if d["code"].lower() != st.code.lower() and d["code"].lower() in S.codes():
                    raise HTTPException(400, f"there is already a set {d['code']}")
            new = sets.from_dict(d, str(st.path))
            new.path, new.css = st.path, st.css
            sets.save(st.path, new)
        return set_detail(S, new)

    @app.delete("/api/sets/{code}")
    def delete_set(code: str):
        """Remove the set file and its css. Renders under out/ and the art cache stay."""
        st = S.find_set(code)
        with S.lock:
            st.path.unlink()
            css = st.path.with_suffix(".css")
            if css.exists():
                css.unlink()
        return {"deleted": str(st.path)}

    @app.post("/api/sets/{code}/cards")
    def post_cards(code: str, body: dict):
        """Append cards (a decklist text or a list of names) after the set's last number.
        Names the card file does not know are refused, all of them at once, unless `force`."""
        st = S.find_set(code)
        names = newset.dedupe(card_names(body))
        unknown = [n for n in names if not S.cards().printings(n)]
        if unknown and not body.get("force"):
            raise HTTPException(400, f"not in the card file: {', '.join(unknown)}")
        with S.lock:
            added = newset.add_cards(st, names)
            sets.save(st.path, st)
        d = set_detail(S, st)
        d["added"] = added
        return d

    @app.put("/api/sets/{code}/cards")
    def put_cards(code: str, body: dict):
        """The card list in a new order (`order`: every name, once), optionally renumbered 1..n."""
        st = S.find_set(code)
        order = body.get("order") or st.names()
        if sorted(order) != sorted(st.names()):
            raise HTTPException(400, "order must list every card of the set exactly once")
        with S.lock:
            st.cards = {n: st.cards[n] for n in order}
            if body.get("renumber"):
                for i, e in enumerate(st.cards.values(), 1):
                    e.number = i
            sets.save(st.path, st)
        return set_detail(S, st)

    @app.delete("/api/sets/{code}/cards/{name}")
    def delete_card(code: str, name: str):
        st = S.find_set(code)
        with S.lock:
            if name not in st.cards:
                raise HTTPException(404, f"{name} is not in {st.code}")
            del st.cards[name]
            st.size = len(st.cards)
            sets.save(st.path, st)
        return set_detail(S, st)

    @app.post("/api/sets/{code}/cards/{name}/rename")
    def rename_card(code: str, name: str, body: dict):
        """Change which card an entry names (a typo, a different face), keeping its place and edits."""
        st = S.find_set(code)
        new = (body.get("name") or "").strip()
        if not new:
            raise HTTPException(400, "a name is needed")
        with S.lock:
            if name not in st.cards:
                raise HTTPException(404, f"{name} is not in {st.code}")
            if new != name and new in st.cards:
                raise HTTPException(400, f"{new} is already in {st.code}")
            st.cards = {(new if n == name else n): e for n, e in st.cards.items()}
            sets.save(st.path, st)
        return set_detail(S, st)

    @app.put("/api/sets/{code}/style")
    def put_style(code: str, body: dict):
        st = S.find_set(code)
        with S.lock:
            st.style = sets.from_dict({"code": "x", "style": body}).style if body else None
            sets.save(st.path, st)
        return set_detail(S, st)

    @app.post("/api/sets/{code}/style/template")
    def style_from_template(code: str, body: dict):
        """Replace the set's style block with a template's (or a built-in's); its css too when
        `css` is true or the set has none."""
        st = S.find_set(code)
        new_style, css = style.load(ws, body.get("template") or "")
        with S.lock:
            st.style = new_style
            sets.save(st.path, st)
            css_fn = st.path.with_suffix(".css")
            if css and (body.get("css") or not st.css):
                css_fn.write_text(css)
                st.css = css
        return set_detail(S, st)

    # --- style templates ---------------------------------------------------------------------
    @app.get("/api/styles")
    def styles_list():
        return [template_dict(S, name, p, private) for name, p, private in style.templates(ws)]

    @app.get("/api/styles/{name}")
    def get_style(name: str):
        for n, p, private in style.templates(ws):
            if n == name:
                return template_dict(S, n, p, private)
        raise HTTPException(404, f"no style template {name}")

    @app.put("/api/styles/{name}")
    def put_style_template(name: str, body: dict):
        """Create or replace a template: `style` is the block as the file would hold it (every key
        given is spelled out), `css` its frame rules, `private` the tier. A built-in's name makes
        a file that shadows it."""
        block = dict(body.get("style") or {})
        block["name"] = name
        new_style = sets.from_dict({"code": "x", "style": block}, f"styles/{name}.json").style
        with S.lock:
            p = style.write(ws, name, new_style, body.get("css") or "", private=bool(body.get("private")))
        return template_dict(S, name, p, ws.is_private(p))

    @app.post("/api/styles")
    def post_style_from_set(body: dict):
        """Save a set's style block as a template, as `mint style save` does (name, private, force)."""
        st = S.find_set(body.get("set") or "")
        with S.lock:
            p = style.save(ws, st, body.get("name") or None, private=bool(body.get("private")),
                           force=bool(body.get("force")))
        return template_dict(S, p.stem, p, ws.is_private(p))

    @app.delete("/api/styles/{name}")
    def delete_style_template(name: str):
        with S.lock:
            p = style.delete(ws, name)
        return {"deleted": str(p)}

    @app.put("/api/sets/{code}/cards/{name}")
    def put_card(code: str, name: str, body: dict):
        st = S.find_set(code)
        with S.lock:
            if name not in st.cards:
                raise HTTPException(404, f"{name} is not in {st.code}")
            cur = {k: v for k, v in dataclasses.asdict(st.cards[name]).items() if v is not None}
            cur.update(body)
            cur = {k: v for k, v in cur.items() if v is not None}
            st.cards[name] = sets.from_dict({"code": "x", "cards": {name: cur}}).cards[name]
            sets.save(st.path, st)
        return card_detail(S, st, name)

    @app.put("/api/sets/{code}/frame")
    def put_frame(code: str, body: dict):
        """Frame knobs, merged onto the set's; the whole block comes back."""
        st = S.find_set(code)
        with S.lock:
            cur = dataclasses.asdict(st.frame or sets.Frame())
            cur.update(body or {})
            st.frame = sets.from_dict({"code": "x", "frame": cur}).frame
            sets.save(st.path, st)
        return dataclasses.asdict(st.frame)

    @app.put("/api/sets/{code}/css")
    def put_css(code: str, body: dict):
        st = S.find_set(code)
        with S.lock:
            st.path.with_suffix(".css").write_text(body.get("css", ""))
        return {"css": body.get("css", "")}

    @app.post("/api/sets/{code}/promote")
    def promote(code: str, body: dict):
        """Make a variant's recipe the set's style, so it becomes the card's current one."""
        st = S.find_set(code)
        name, h = body["name"], body["hash"]
        card = S.cards().find(name, st.card({"name": name}).printing)
        v = S.art.variant(card, h)
        if not v or v.kind != "restyle":
            raise HTTPException(404, f"no restyle variant {h} for {name}")
        with S.lock:
            st.style = st.promote(v.recipe, card)
            entry = st.cards[name]
            if st.card_seed(name, card["illustration_id"]) != v.recipe.get("seed"):
                entry.seed = v.recipe.get("seed")
            entry.base = None if v.base == "crop" else v.base
            if entry.pick == h:  # the recipe now makes it current; the pick is redundant
                entry.pick = None
            sets.save(st.path, st)
        return set_detail(S, st)

    @app.put("/api/sets/{code}/base")
    def put_base(code: str, body: dict):
        """The set-wide restyle base: a label ("spore"), a variant hash, or null for the crop."""
        st = S.find_set(code)
        with S.lock:
            st.base = body.get("base") or None
            sets.save(st.path, st)
        return set_detail(S, st)

    @app.delete("/api/sets/{code}/cards/{name}/variants/{h}")
    def delete_variant(code: str, name: str, h: str):
        """Remove one variant (image + sidecar). A card entry that named it as its base or pick goes back to the default."""
        st = S.find_set(code)
        card = S.cards().find(name, st.card({"name": name}).printing)
        v = S.art.variant(card, h)
        if not v:
            raise HTTPException(404, f"no variant {h} for {name}")
        with S.lock:
            S.art.delete(v)
            entry = st.cards.get(name)
            if entry and h in (entry.base, entry.pick, entry.pose):
                for k in ("base", "pick", "pose"):
                    if getattr(entry, k) == h:
                        setattr(entry, k, None)
                sets.save(st.path, st)
        return card_detail(S, st, name)

    @app.delete("/api/sets/{code}/renders/{filename}")
    def delete_render(code: str, filename: str):
        """Remove one rendered card (the PNG in out/<set>/ and its manifest entry)."""
        st = S.find_set(code)
        if "/" in filename or not filename.endswith(".png"):
            raise HTTPException(400, "a render is a .png in the set's out directory")
        with S.lock:
            m = Manifest(S.out_dir(st))
            if filename not in m.entries and not (S.out_dir(st) / filename).exists():
                raise HTTPException(404, f"no render {filename} for {st.code}")
            name = m.entries.get(filename, {}).get("card")
            m.remove(filename)
            m.save()
        return card_detail(S, st, name) if name else {"ok": True}

    @app.get("/api/sets/{code}/cards/{name}")
    def get_card(code: str, name: str):
        st = S.find_set(code)
        return card_detail(S, st, name)

    @app.get("/api/sets/{code}/cards/{name}/printings")
    def printings(code: str, name: str):
        st = S.find_set(code)
        entry = st.card({"name": name})
        out = []
        cands = S.cards().printings(name)
        default = default_printing(cands)
        for c in cands:
            penalty, why = oddness(c)
            crop = S.art.crop(c, fetch=False) if c.get("illustration_id") else None
            out.append({**card_summary(c), "ub": bool(warnings(c)), "crop": str(crop) if crop else None,
                        "crop_cached": bool(crop and crop.exists()),
                        "set_name": c.get("set_name"), "odd": why, "penalty": penalty, "default": c is default,
                        "selected": entry.printing == f"{c['set']}:{c['collector_number']}"})
        return out

    @app.get("/api/sets/{code}/cards/{name}/printings/{printing}/crop")
    def printing_crop(code: str, name: str, printing: str, w: int = 320):
        """A printing's art crop as a thumbnail, fetched from Scryfall on first sight (for the picker)."""
        S.find_set(code)  # 404 for an unknown set
        card = S.cards().find(name, printing)
        try:
            crop = S.art.crop(card)
        except (OSError, MintError) as e:
            raise HTTPException(502, f"could not fetch the crop: {e}") from None
        return FileResponse(thumbnail(ws, str(crop), w), headers={"Cache-Control": "max-age=3600"})

    @app.post("/api/sets/{code}/cards/{name}/scan")
    def scan(code: str, name: str):
        """Fetch Scryfall's full-card scan (for the calibration overlay)."""
        st = S.find_set(code)
        card = S.cards().find(name, st.card({"name": name}).printing)
        return {"path": str(S.art.scan(card))}

    # --- jobs ---------------------------------------------------------------------------------
    @app.get("/api/jobs")
    def jobs_list():
        return S.jobs.list()

    @app.post("/api/jobs/{jid}/cancel")
    def jobs_cancel(jid: str):
        job = S.jobs.cancel(jid)
        if not job:
            raise HTTPException(404)
        return job.to_dict()

    @app.post("/api/jobs")
    def jobs_submit(body: dict):
        kind = body.get("kind")
        st = S.find_set(body["set"]) if body.get("set") else None
        names = body.get("names") or (st.names() if st else [])
        submit = {"render": submit_render, "enhance": submit_enhance, "restyle": submit_restyle, "themes": submit_themes}.get(kind)
        if not submit:
            raise HTTPException(400, f"unknown job kind {kind!r}")
        job = submit(S, st, names, body)
        job.params["origin"] = body.get("origin")  # where on the page it was asked for, for the jobs list
        return job.to_dict()

    @app.get("/api/events")
    def events(request: Request):
        q = S.jobs.subscribe()

        def gen():
            try:
                yield "event: hello\ndata: {}\n\n"
                while True:
                    try:
                        event, data = q.get(timeout=15)
                        yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                S.jobs.unsubscribe(q)
        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def app():
    """The app for the workspace in the environment: `mint serve --reload`, or `uvicorn --factory mint.web.server:app`."""
    from .. import workspace
    return create_app(workspace.default())


# --- detail builders ------------------------------------------------------------------------
def card_names(body):
    """The card names a request carries: `names` (a list) or `decklist` (text, counts optional)."""
    names = list(body.get("names") or [])
    if body.get("decklist"):
        names += newset.parse_decklist(body["decklist"], plain=True)
    names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    if not names:
        raise HTTPException(400, "no card names given")
    return names


def template_dict(S, name, path, private):
    """A style template for the page: the block as its file spells it, its css, and which sets
    carry a style of that name."""
    st, css = style.load(S.ws, name)
    block = sets._slim(dataclasses.asdict(st), sets.Style, st.explicit)
    used = []
    for p in S.set_paths():
        try:
            s = sets.load(p)
        except MintError:
            continue
        if s.style and s.style.name == name:
            used.append(s.code)
    shadowed = path is not None and style.find(S.ws, name) != path
    return {"name": name, "path": str(path) if path else None, "private": private, "builtin": path is None,
            "shadowed": shadowed, "style": block, "css": css, "sets": used}


def style_fields():
    """The Style schema for the recipe form: name, type, default."""
    out = []
    for f in dataclasses.fields(sets.Style):
        if f.name == "explicit":
            continue
        default = f.default if f.default is not dataclasses.MISSING else None
        t = sets._base_type(f.type)
        out.append({"name": f.name, "type": t, "default": default,
                    "choices": list(sets.CONTROLS) if f.name == "control" else
                    list(sets.SEED_RULES) if f.name == "seed_rule" else
                    list(sets.REMIX) if f.name == "remix" else
                    list(sets.INSPIRE_TYPES) if f.name == "inspire_type" else None})
    return out


def frame_fields():
    """The Frame schema for the frame page's knobs: name, default; every one a float 0-1."""
    return [{"name": f.name, "type": "float", "default": f.default} for f in dataclasses.fields(sets.Frame)]


def set_detail(S, st):
    d = st.to_dict()
    d["path"] = str(st.path)
    d["css"] = st.css
    d["frame"] = dataclasses.asdict(st.frame or sets.Frame())
    d["out_dir"] = str(S.out_dir(st))
    d["cards_detail"] = [card_detail(S, st, n, cards=None) for n in st.names()]
    return d


def card_detail(S, st, name, cards=None):
    entry = st.card({"name": name})
    info = {"name": name, "number": entry.number, "entry": {k: v for k, v in dataclasses.asdict(entry).items()
                                                            if v is not None}}
    try:
        card = (cards or S.cards()).find(name, entry.printing)
    except MintError as e:
        info["error"] = str(e)
        return info
    art = S.art
    info["card"] = card_summary(card)
    info["warnings"] = warnings(card)
    crop = art.crop(card, fetch=False)
    info["crop"] = str(crop) if crop.exists() else None
    info["variants"] = [variant_dict(v) for v in art.variants(card)]
    if st.style:
        recipe = st.recipe(card, art=art)
        info["style_hash"] = sets.recipe_hash(recipe)
        info["recipe"] = recipe
        info["base_missing"] = recipe["base"] if sets.is_label(recipe["base"]) else None
        cur = art.variant(card, info["style_hash"])
        info["current"] = variant_dict(cur) if cur else None
    if entry.pick:  # the styled art the card asked for by hash, whatever the recipe says
        pv = art.variant(card, entry.pick)
        info["picked"] = variant_dict(pv) if pv else None
    want = {}
    if crop.exists() or entry.art:
        plain = art.resolve(card, override=entry.art)
        styled = art.resolve(card, override=entry.art, style_hash=st.styled_hash(card, art=art))
        info["plain"], info["styled"] = source_dict(plain), source_dict(styled)
        want = {"plain": plain.hash, "styled": styled.hash}
    info["renders"] = renders_for(S, st, name, want)
    return info


def renders_for(S, st, name, want=None):
    """The card's newest plain and styled render, its proof and its theme sheet. `want` is the art
    hash each of plain / styled should render with now; a render is `stale` when the frame (template,
    knobs, set css) or that art has changed since it was made."""
    out = {}
    m = Manifest(S.out_dir(st))
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    for fn, e in m.entries.items():
        if e.get("card") != name:
            continue
        p = S.out_dir(st) / fn
        if not p.exists():
            continue
        key = ("styled" if e.get("styled") else "plain") if e.get("theme") == "wizards" or not e.get("theme") else None
        if key and key not in out or (key and e["rendered_at"] > out[key]["rendered_at"]):
            out[key] = {**e, "file": fn, "path": str(p)}
            if want is not None:
                out[key]["stale"] = ("the frame changed" if e.get("frame") != fh
                                     else "the art changed" if (e.get("source") or {}).get("hash") != want.get(key) else None)
    proof = S.out_dir(st) / "proof"
    if proof.is_dir():
        pm = Manifest(proof)
        for fn, e in pm.entries.items():
            if e.get("card") == name and not e.get("styled") and (proof / fn).exists():
                if "proof" not in out or e["rendered_at"] > out["proof"]["rendered_at"]:
                    out["proof"] = {**e, "file": fn, "path": str(proof / fn)}
    themes = S.out_dir(st) / "themes"
    if themes.is_dir():
        tm = Manifest(themes)
        out["themes"] = [{**e, "file": fn, "path": str(themes / fn)} for fn, e in tm.entries.items()
                         if e.get("card") == name and (themes / fn).exists()]
    return out


# --- jobs ----------------------------------------------------------------------------------------
def submit_render(S, st, names, body):
    styled, dpi = bool(body.get("styled")), int(body.get("dpi") or 1200)
    sub = body.get("sub")
    if sub and (sub != os.path.basename(sub) or sub.startswith(".")):
        raise HTTPException(400, "bad sub directory")
    out_dir = str(S.out_dir(st) / sub if sub else S.out_dir(st))
    title = f"render {st.code} {'styled ' if styled else ''}{len(names)} card(s) @ {dpi}"
    what = (f"composes {len(names)} card(s) of {st.code} -- frame, text and their {'styled' if styled else 'plain'} art -- "
            f"at {dpi} dpi; the art must already exist, none is made")

    def run(job):
        job.step(0, len(names))
        done = []

        def on_rendered(r):
            done.append(r.out)
            job.say(f"{os.path.basename(r.out)}" + (f"  text {r.sizes['text']}px" if r.shrunk else "") +
                    "".join(f"  warning: {w}" for w in r.warnings))
            job.made(set=st.code, name=r.name, kind="render", key=f"render-{'styled' if styled else 'plain'}",
                     file=os.path.basename(r.out), path=r.out)
            job.step(len(done))
        render.render_cards(S.ws, names, set_path=st.path, styled=styled, dpi=dpi, out_dir=out_dir,
                            on_rendered=on_rendered)
        return {"files": done, "out_dir": out_dir}
    return S.jobs.submit("render", title, {"set": st.code, "names": names, "styled": styled, "dpi": dpi,
                                           "what": what, "dest": out_dir}, run)


def submit_themes(S, st, names, body):
    name = names[0]
    out_dir = str(S.out_dir(st) / "themes")

    def run(job):
        job.step(0, len(frame.THEMES))
        done = []

        def on_rendered(r):
            done.append(r.out)
            job.say(f"{r.theme}: {os.path.basename(r.out)}")
            job.made(set=st.code, name=name, kind="theme", file=os.path.basename(r.out), path=r.out)
            job.step(len(done))
        render.render_cards(S.ws, [name], set_path=st.path, themes=list(frame.THEMES), dpi=int(body.get("dpi") or 300),
                            out_dir=out_dir, compare=True, on_rendered=on_rendered)
        return {"files": done}
    return S.jobs.submit("themes", f"themes for {name}", {"set": st.code, "names": [name], "dest": out_dir,
                                                          "what": f"renders {name} once in every frame theme, side by side"}, run)


def submit_enhance(S, st, names, body):
    base, model, force = body.get("base") or "crop", body.get("model") or upscale.DEFAULT_MODEL, bool(body.get("force"))

    def run(job):
        server = S.comfy()
        server.require()
        cards = S.cards()
        job.step(0, len(names))
        made = []
        for i, name in enumerate(names):
            entry = st.card({"name": name}) if st else sets.CardEntry()
            card = cards.find(name, entry.printing)
            v, did = upscale.enhance(server, S.art, card, model, base, force)
            job.say(f"{'enhanced' if did else 'cached'} {name} -> {v.label}-{v.hash}")
            made.append(v.hash)
            if st:
                job.made(set=st.code, name=name, kind=v.kind, key=v.hash, label=v.label, path=str(v.path))
            job.step(i + 1)
        return {"variants": made}
    title = f"enhance {len(names)} card(s) from {base}"
    what = f"an ESRGAN pass ({model}) over the {'crop' if base == 'crop' else 'variant ' + base} of {len(names)} card(s); a new enhance variant each"
    return S.jobs.submit("enhance", title, {"set": st.code if st else None, "names": names, "base": base, "model": model,
                                            "what": what, "dest": str(S.art.dir)}, run)


def submit_restyle(S, st, names, body):
    """A restyle job: the set's style, or `template` (a template / built-in by name, taken whole,
    so a set's own knobs never leak into it), or `style` overrides on top of the set's (the lab).
    Whichever, each card keeps its own base, subject, seed and remix mode."""
    overrides, template = body.get("style") or {}, body.get("template")
    if st.style is None and not overrides and not template:
        raise HTTPException(400, f"{st.code} has no style block; pick a template to restyle as")
    sty = st.style
    if template:
        sty, _ = style.load(S.ws, template)
    elif overrides:
        base = dataclasses.asdict(st.style) if st.style else {"name": "lab", "prompt": ""}
        base.pop("explicit", None)
        base.update(overrides)
        if body.get("label"):
            base["name"] = body["label"]
        sty = sets.from_dict({"code": "x", "style": base}).style
    # `takes`: several variants per card, each from its own random seed, to choose between. They
    # are drafts: the ESRGAN pass (a large share of a take's time) is skipped unless `upscale` says
    # otherwise -- enhance the keeper instead, and the renderer picks the enhance up.
    takes = max(1, min(int(body.get("takes") or 1), 16))
    force, up = bool(body.get("force")), bool(body.get("upscale", takes == 1))
    seed = body.get("seed")
    seeds = [seed] if takes == 1 else [random.randrange(1, 2 ** 31) for _ in range(takes)]

    def run(job):
        server = S.comfy()
        server.require()
        cards = S.cards()
        job.step(0, len(names) * takes)
        made = []
        for i, name in enumerate(names):
            card = cards.find(name, st.card({"name": name}).printing)
            for t, sd in enumerate(seeds):
                v, did = restyle.restyle(server, S.art, card, st, style=sty, force=force, upscale=up, seed=sd)
                take = f"  (take {t + 1}, seed {sd})" if takes > 1 else ""
                job.say(f"{'restyled' if did else 'cached'} {name} -> {v.label}-{v.hash}{take}")
                made.append(v.hash)
                job.made(set=st.code, name=name, kind=v.kind, key=v.hash, label=v.label, path=str(v.path))
                job.step(i * takes + t + 1)
        return {"variants": made}
    title = f"restyle {len(names)} card(s) as {sty.name}" + (f" x {takes} takes" if takes > 1 else "")
    title += (" (lab)" if overrides else "") + ("" if up else ", drafts: enhance the keeper")
    what = (f"makes art for {len(names)} card(s) of {st.code} in the look {sty.name} (mode {sty.remix}; a card's own mode, "
            f"base, subject and seed win), {takes} take(s) each, {'with' if up else 'without'} the ESRGAN pass; "
            f"{'the template taken whole' if template else 'the lab knobs over the set style' if overrides else 'the set style'}")
    params = {"set": st.code, "names": names, "style": overrides, "template": template, "label": sty.name, "takes": takes,
              "what": what, "dest": str(S.art.dir)}
    return S.jobs.submit("restyle", title, params, run)
