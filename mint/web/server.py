"""The workbench's routes. `create_app(ws)` returns the FastAPI app; `mint serve` runs it."""
import dataclasses
import json
import os
import queue
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .. import PKG, comfy, frame, render, restyle, sets, upscale
from ..art import Art
from ..cards import Cards, default_printing, oddness, warnings
from ..errors import MintError
from ..manifest import Manifest
from .jobs import Jobs
from .thumbs import inside, thumbnail

STATIC = PKG / "web" / "static"


class State:
    def __init__(self, ws):
        self.ws = ws
        self.jobs = Jobs()
        self.art = Art(ws.art)
        self._comfy = (0.0, False)
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
                "comfy": {"url": ws.comfy_url, "alive": S.comfy_alive()},
                "cards": {"path": str(ws.cards_file), "count": count},
                "sets": out, "themes": list(frame.THEMES), "controls": list(sets.CONTROLS),
                "style_fields": style_fields(), "current_job": S.jobs.current.to_dict() if S.jobs.current else None}

    # --- sets ---------------------------------------------------------------------------
    @app.get("/api/sets/{code}")
    def get_set(code: str):
        st = S.find_set(code)
        return set_detail(S, st)

    @app.put("/api/sets/{code}/style")
    def put_style(code: str, body: dict):
        st = S.find_set(code)
        with S.lock:
            st.style = sets.from_dict({"code": "x", "style": body}).style if body else None
            sets.save(st.path, st)
        return set_detail(S, st)

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
        """Remove one variant (image + sidecar). A card entry that named it as its base goes back to the default."""
        st = S.find_set(code)
        card = S.cards().find(name, st.card({"name": name}).printing)
        v = S.art.variant(card, h)
        if not v:
            raise HTTPException(404, f"no variant {h} for {name}")
        with S.lock:
            S.art.delete(v)
            entry = st.cards.get(name)
            if entry and entry.base == h:
                entry.base = None
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
        if kind == "render":
            return submit_render(S, st, names, body).to_dict()
        if kind == "enhance":
            return submit_enhance(S, st, names, body).to_dict()
        if kind == "restyle":
            return submit_restyle(S, st, names, body).to_dict()
        if kind == "themes":
            return submit_themes(S, st, names, body).to_dict()
        raise HTTPException(400, f"unknown job kind {kind!r}")

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


# --- detail builders ------------------------------------------------------------------------
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
                    list(sets.REMIX) if f.name == "remix" else None})
    return out


def set_detail(S, st):
    d = st.to_dict()
    d["path"] = str(st.path)
    d["css"] = st.css
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
    if crop.exists() or entry.art:
        info["plain"] = source_dict(art.resolve(card, override=entry.art))
        info["styled"] = source_dict(art.resolve(card, override=entry.art, style_hash=info.get("style_hash")))
    info["renders"] = renders_for(S, st, name)
    return info


def renders_for(S, st, name):
    out = {}
    m = Manifest(S.out_dir(st))
    for fn, e in m.entries.items():
        if e.get("card") != name:
            continue
        p = S.out_dir(st) / fn
        if not p.exists():
            continue
        key = ("styled" if e.get("styled") else "plain") if e.get("theme") == "wizards" or not e.get("theme") else None
        if key and key not in out or (key and e["rendered_at"] > out[key]["rendered_at"]):
            out[key] = {**e, "file": fn, "path": str(p)}
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

    def run(job):
        job.step(0, len(names))
        done = []

        def on_rendered(r):
            done.append(r.out)
            job.say(f"{os.path.basename(r.out)}" + (f"  text {r.sizes['text']}px" if r.shrunk else "") +
                    "".join(f"  warning: {w}" for w in r.warnings))
            job.step(len(done))
        render.render_cards(S.ws, names, set_path=st.path, styled=styled, dpi=dpi, out_dir=out_dir,
                            on_rendered=on_rendered)
        return {"files": done, "out_dir": out_dir}
    return S.jobs.submit("render", title, {"set": st.code, "names": names, "styled": styled, "dpi": dpi}, run)


def submit_themes(S, st, names, body):
    name = names[0]
    out_dir = str(S.out_dir(st) / "themes")

    def run(job):
        job.step(0, len(frame.THEMES))
        done = []

        def on_rendered(r):
            done.append(r.out)
            job.say(f"{r.theme}: {os.path.basename(r.out)}")
            job.step(len(done))
        render.render_cards(S.ws, [name], set_path=st.path, themes=list(frame.THEMES), dpi=int(body.get("dpi") or 300),
                            out_dir=out_dir, compare=True, on_rendered=on_rendered)
        return {"files": done}
    return S.jobs.submit("themes", f"themes for {name}", {"set": st.code, "names": [name]}, run)


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
            job.step(i + 1)
        return {"variants": made}
    title = f"enhance {len(names)} card(s) from {base}"
    return S.jobs.submit("enhance", title, {"set": st.code if st else None, "names": names, "base": base, "model": model}, run)


def submit_restyle(S, st, names, body):
    if st.style is None and not body.get("style"):
        raise HTTPException(400, f"{st.code} has no style block")
    overrides = body.get("style") or {}
    style = st.style
    if overrides:
        base = dataclasses.asdict(st.style) if st.style else {"name": "lab", "prompt": ""}
        base.pop("explicit", None)
        base.update(overrides)
        if body.get("label"):
            base["name"] = body["label"]
        style = sets.from_dict({"code": "x", "style": base}).style
    force, up = bool(body.get("force")), body.get("upscale", True)

    def run(job):
        server = S.comfy()
        server.require()
        cards = S.cards()
        job.step(0, len(names))
        made = []
        for i, name in enumerate(names):
            card = cards.find(name, st.card({"name": name}).printing)
            v, did = restyle.restyle(server, S.art, card, st, style=style, force=force, upscale=up)
            job.say(f"{'restyled' if did else 'cached'} {name} -> {v.label}-{v.hash}")
            made.append(v.hash)
            job.step(i + 1)
        return {"variants": made}
    title = f"restyle {len(names)} card(s) as {style.name}" + (" (lab)" if overrides else "")
    params = {"set": st.code, "names": names, "style": overrides, "label": style.name}
    return S.jobs.submit("restyle", title, params, run)
