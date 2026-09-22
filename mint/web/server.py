"""The workbench's routes. `create_app(ws)` returns the FastAPI app; `mint serve` runs it."""
import dataclasses
import json
import os
import queue
import random
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .. import PKG, animate, comfy, describe, frame, impose, loop, newset, printing, render, restyle, sets, style, upscale, wan
from ..art import Art
from ..cards import Cards, default_printing, oddness, warnings
from ..errors import MintError
from ..manifest import Manifest, frame_hash
from . import pdfs
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
        self._wan = (0.0, None)
        self._describer = (0.0, None)
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

    def wan_info(self):
        """Whether `animate` could run now: ComfyUI up with the Wan nodes and every file the sets'
        motion blocks (or the defaults) name, and ffmpeg on PATH; else why not, in one line."""
        t, info = self._wan
        if time.time() - t > 60 or info is None:
            info = self._wan_check()
            self._wan = (time.time(), info)
        return info

    def _wan_check(self):
        if not loop.have_ffmpeg():
            return {"ready": False, "hint": "no ffmpeg on PATH; animate encodes the clip with it"}
        if not self.comfy_alive():
            return {"ready": False, "hint": "ComfyUI is down"}
        nodes = self.comfy_nodes()
        missing = [n for n in wan.NODES if n not in nodes]
        if missing:
            return {"ready": False, "hint": f"ComfyUI lacks the Wan nodes ({', '.join(missing)}): update it"}
        motions = [sets.Motion()]
        for p in self.set_paths():
            try:
                st = sets.load(p)
            except MintError:
                continue
            if st.motion:
                motions.append(st.motion)
        server = self.comfy()
        for knob, (node, inp, folder) in wan.FILES.items():
            avail = server.options(node, inp) or []
            for m in motions:
                fn = getattr(m, knob)
                if fn not in avail:
                    return {"ready": False, "hint": f"ComfyUI has no {fn} in models/{folder}: fetch {wan.url(knob, fn)}"}
        return {"ready": True, "hint": ""}

    def describer(self):
        return describe.Describer.from_workspace(self.ws)

    def describer_info(self):
        """Who would read a card's picture, and whether they could now; asked at most every 30 s
        (an Ollama check is a request)."""
        t, info = self._describer
        if info is None or time.time() - t > 30:
            try:
                d = self.describer()
                ok, why = d.ready()
                alive = ok and d.alive()
                info = {"kind": d.kind, "model": d.model, "ready": alive,
                        "hint": why or ("" if alive else f"nothing answers at {d.url}; start Ollama, or set ollama_url")}
            except MintError as e:
                info = {"kind": self.ws.describer, "model": "", "ready": False, "hint": str(e)}
            self._describer = (time.time(), info)
        return info

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
    d["videos"] = [str(p) for p in v.videos]
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
    S = app.state.S = State(ws)  # on the app too, for tests to reach the caches

    @app.exception_handler(MintError)
    async def mint_error(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=400)

    # --- pages and files -----------------------------------------------------------
    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.ico")
    def favicon():
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
    def img(request: Request, path: str, w: int = 320):
        """A thumbnail. A render is overwritten in place under the same name, so the browser must ask
        again each time: the thumbnail's cache key (path, size, mtime) is the ETag, and an unchanged
        file costs a stat and a 304."""
        thumb = thumbnail(ws, path, w)
        etag = f'"{thumb.stem}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
        return FileResponse(thumb, headers={"ETag": etag, "Cache-Control": "no-cache"})

    @app.get("/file")
    def file(path: str, download: bool = False):
        """A file inside the workspace; `download` makes the browser save it instead of showing it."""
        p = inside(ws, path)
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "max-age=60"}, filename=p.name if download else None)

    @app.get("/pdfpage")
    def pdf_page(path: str, n: int = 1, w: int = 800):
        """One page of a PDF inside the workspace as a PNG (see pdfs.py)."""
        if n < 1:
            raise HTTPException(400, "n is 1-based")
        return FileResponse(pdfs.page_image(ws, path, n, w), headers={"Cache-Control": "max-age=3600"})

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
                          "ipadapter": "IPAdapterUnifiedLoader" in S.comfy_nodes(),
                          # what animate needs: the Wan 2.2 files in ComfyUI and ffmpeg here (else why not)
                          "wan": S.wan_info()},
                "cards": {"path": str(ws.cards_file), "count": count},
                # who writes subject lines from pictures (describe.py), and whether they could now
                "describer": S.describer_info(),
                "sets": out, "themes": list(frame.THEMES), "controls": list(sets.CONTROLS),
                "loops": list(sets.LOOPS), "motion_remix": list(sets.MOTION_REMIX),
                "style_fields": style_fields(), "frame_fields": frame_fields(),
                "current_job": S.jobs.current.to_dict() if S.jobs.current else None,
                "print": {"stocks": sorted(printing.STOCKS), "paper": list(impose.PAPER), "printer": ws.printer,
                          "export_dir": str(ws.export_path)}}

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
        submit_crops(S, st, st.names(), {}, origin="new set")  # the board fills in as each crop lands
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
        if added:
            submit_crops(S, st, names, {}, origin=f"{st.code} edit: cards added")
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

    @app.post("/api/sets/{code}/cards/{name:path}/rename")
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
        t = style.read(ws, body.get("template") or "")
        new_style, css = t["style"], t["css"]
        with S.lock:
            st.style = new_style
            if t["frame"] is not None and body.get("frame", True):  # the template's dressing comes along
                st.frame = t["frame"]
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
        fr = body.get("frame")
        parsed = sets.from_dict({"code": "x", "style": block, **({"frame": fr} if fr else {})}, f"styles/{name}.json")
        with S.lock:
            p = style.write(ws, name, parsed.style, body.get("css") or "", private=bool(body.get("private")), frame=parsed.frame)
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

    @app.put("/api/sets/{code}/cards/{name:path}")
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

    @app.delete("/api/sets/{code}/cards/{name:path}/variants/{h}")
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

    @app.get("/api/sets/{code}/cards/{name:path}/printings")
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

    @app.get("/api/sets/{code}/cards/{name:path}/printings/{printing}/crop")
    def printing_crop(code: str, name: str, printing: str, w: int = 320):
        """A printing's art crop as a thumbnail, fetched from Scryfall on first sight (for the picker)."""
        S.find_set(code)  # 404 for an unknown set
        card = S.cards().find(name, printing)
        try:
            crop = S.art.crop(card)
        except (OSError, MintError) as e:
            raise HTTPException(502, f"could not fetch the crop: {e}") from None
        return FileResponse(thumbnail(ws, str(crop), w), headers={"Cache-Control": "max-age=3600"})

    @app.post("/api/sets/{code}/cards/{name:path}/scan")
    def scan(code: str, name: str):
        """Fetch Scryfall's full-card scan (for the calibration overlay)."""
        st = S.find_set(code)
        card = S.cards().find(name, st.card({"name": name}).printing)
        return {"path": str(S.art.scan(card))}

    # the card itself, after its sub-routes: {name:path} is greedy (a double-faced name holds a slash)
    @app.get("/api/sets/{code}/cards/{name:path}")
    def get_card(code: str, name: str):
        st = S.find_set(code)
        return card_detail(S, st, name)

    @app.delete("/api/sets/{code}/cards/{name:path}")
    def delete_card(code: str, name: str):
        st = S.find_set(code)
        with S.lock:
            if name not in st.cards:
                raise HTTPException(404, f"{name} is not in {st.code}")
            del st.cards[name]
            st.size = len(st.cards)
            sets.save(st.path, st)
        return set_detail(S, st)

    # --- jobs ---------------------------------------------------------------------------------
    # --- pdfs ---------------------------------------------------------------------------
    @app.get("/api/sets/{code}/pdfs")
    def list_pdfs(code: str):
        """The set's PDFs: its print runs and `mint impose`'s file, newest first."""
        st = S.find_set(code)
        return {"pdfs": pdfs.pdfs(ws, st, S.out_dir(st)), "export_dir": str(ws.export_path)}

    @app.post("/api/sets/{code}/pdfs/export")
    def export_pdf(code: str, body: dict):
        """Copy one of the set's PDFs (`file`) into the export directory; 409 when a file of that
        name is already there and `force` is not set."""
        st = S.find_set(code)
        src = pdfs.find(ws, st, S.out_dir(st), body.get("file") or "")
        try:
            dest = pdfs.export(ws, src, force=bool(body.get("force")))
        except FileExistsError as e:
            raise HTTPException(409, f"{e} is already there") from None
        return {"exported": str(dest)}

    @app.delete("/api/sets/{code}/pdfs/{file}")
    def delete_pdf(code: str, file: str):
        st = S.find_set(code)
        p = pdfs.find(ws, st, S.out_dir(st), file)
        p.unlink()
        return {"deleted": str(p)}

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
        submit = {"render": submit_render, "enhance": submit_enhance, "restyle": submit_restyle, "themes": submit_themes,
                  "printrun": submit_printrun, "describe": submit_describe, "animate": submit_animate,
                  "crops": submit_crops}.get(kind)
        if not submit:
            raise HTTPException(400, f"unknown job kind {kind!r}")
        job = submit(S, st, names, body)
        if job is None:
            raise HTTPException(400, "nothing to do: every card named has its crop")
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
    t = style.read(S.ws, name)
    st, css = t["style"], t["css"]
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
            "shadowed": shadowed, "style": block, "css": css, "sets": used,
            "frame": dataclasses.asdict(t["frame"]) if t["frame"] is not None else None}


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
    d["motion_knobs"] = {k: v for k, v in dataclasses.asdict(st.motion or sets.Motion()).items() if k != "explicit"}
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
    info["described"] = art.described(card)  # the describer's reading of the base, if one was asked
    if st.style:
        recipe = st.recipe(card, art=art)
        info["style_hash"] = sets.recipe_hash(recipe)
        info["recipe"] = recipe
        info["base_missing"] = recipe["base"] if sets.is_label(recipe["base"]) else None
        cur = art.variant(card, info["style_hash"])
        info["current"] = variant_dict(cur) if cur else None
    if crop.exists() or entry.art:  # the clip the motion recipe would make now, and from which image
        try:
            mr = st.motion_recipe(card, art=art)
            info["motion_recipe"], info["motion_hash"] = mr, sets.recipe_hash(mr)
        except MintError:
            pass
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
    hash each of plain / styled should render with now; a render is `stale` when the frame (template, frame.py,
    knobs, set css) or that art has changed since it was made."""
    out = {}
    m = Manifest(S.out_dir(st))
    fh = frame_hash(st.css, frame.frame_css(st.frame))
    mine = {name, name.split(" // ")[0]}  # a double-faced card's render is filed under its front face's name
    for fn, e in m.entries.items():
        if e.get("card") not in mine:
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


def submit_printrun(S, st, names, body):
    """A print run: the cards rendered (only those without a fresh render), imposed onto pages as a
    PDF under out/<set>/print/, and -- with a `stock` -- sent to the workspace's printer at 100%."""
    styled, dpi = bool(body.get("styled")), int(body.get("dpi") or 1200)
    paper, bleed, sheet_dpi = body.get("paper") or "letter", float(body.get("bleed") or 0.04), int(body.get("sheet_dpi") or 600)
    stock, copies = body.get("stock") or None, max(1, int(body.get("copies") or 1))
    if paper not in impose.PAPER:
        raise HTTPException(400, f"paper is one of {', '.join(impose.PAPER)}")
    if stock and stock not in printing.STOCKS:
        raise HTTPException(400, f"stock is one of {', '.join(sorted(printing.STOCKS))}")
    out_dir = S.out_dir(st)
    key = "styled" if styled else "plain"
    title = (f"print run: {st.code} {key}, {len(names)} card(s) on {paper}"
             + (f", {copies}x on {stock}" if stock else ", PDF only"))
    what = (f"renders the {len(names)} card(s) whose {key} render is missing or stale at {dpi} dpi, lays them out 3x3 on "
            f"{paper} with {bleed}in bleed at {sheet_dpi} dpi into out/{st.code.lower()}/print/"
            + (f", and prints {copies} copy(ies) on {stock} to {S.ws.printer}" if stock else ""))

    def run(job):
        # named when it runs, with the job's id: two runs queued in the same minute keep their own files
        pdf = out_dir / "print" / f"{st.code}-{key}-{time.strftime('%Y%m%d-%H%M')}-{job.id[:4]}.pdf"
        need = [n for n in names if not (r := renders_for(S, st, n, want_for(S, st, n)).get(key)) or r.get("stale")]
        job.step(0, len(need) + 2)
        done = 0
        if need:
            def on_rendered(r):
                nonlocal done
                done += 1
                job.say(f"rendered {os.path.basename(r.out)}")
                job.made(set=st.code, name=r.name, kind="render", key=f"render-{key}", file=os.path.basename(r.out), path=r.out)
                job.step(done)
            render.render_cards(S.ws, need, set_path=st.path, styled=styled, dpi=dpi, out_dir=str(out_dir),
                                on_rendered=on_rendered)
        else:
            job.say("every card has a fresh render")
        files = []
        for n in names:
            r = renders_for(S, st, n).get(key)
            if not r:
                raise MintError(f"{n}: no {key} render to print")
            files.append(r["path"])
        pages = impose.impose(files, str(pdf), paper, bleed, sheet_dpi, log=job.say)
        job.made(set=st.code, name=f"{pages} page(s)", kind="pdf", file=pdf.name, path=str(pdf))
        job.step(len(need) + 1)
        if stock:
            page_size = "Letter" if paper == "letter" else "A4"
            try:
                printing.print_pdf(str(pdf), stock, S.ws.printer, page_size, copies, log=job.say)
            except printing.PrintError as e:
                raise MintError(str(e)) from None
        job.step(len(need) + 2)
        return {"pdf": str(pdf), "pages": pages, "rendered": need}
    return S.jobs.submit("printrun", title, {"set": st.code, "names": names, "styled": styled, "dpi": dpi, "paper": paper,
                                             "stock": stock, "copies": copies, "what": what, "dest": str(out_dir / "print")}, run)


def want_for(S, st, name):
    """The art hash each of plain / styled should render with now, for the stale check."""
    entry = st.card({"name": name})
    try:
        card = S.cards().find(name, entry.printing)
    except MintError:
        return {}
    art = S.art
    return {"plain": art.resolve(card, override=entry.art).hash,
            "styled": art.resolve(card, override=entry.art, style_hash=st.styled_hash(card, art=art)).hash}


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


def submit_crops(S, st, names, body, origin=None):
    """A crops job: each card's Scryfall art crop into the art cache, skipping the ones on disk.
    A new set or added cards queue one by themselves, so the board fills in without a render;
    the board's button and the card page's fetch the ones still missing. Returns the job, or None
    when every card named has its crop already."""
    cards = S.cards()
    todo = []
    for name in names:
        try:
            card = cards.find(name, st.card({"name": name}).printing)
        except MintError:
            continue  # not on file: the card page says so
        if card.get("illustration_id") and not S.art.crop(card, fetch=False).exists():
            todo.append(name)
    if not todo:
        return None

    def run(job):
        cards = S.cards()
        job.step(0, len(todo))
        failed = []
        for i, name in enumerate(todo):
            card = cards.find(name, st.card({"name": name}).printing)
            try:
                crop = S.art.crop(card)
            except OSError as e:
                failed.append(name)
                job.say(f"could not fetch {name}: {e}")
            else:
                job.say(f"fetched {name} <- {card['set'].upper()} {card['collector_number']}")
                job.made(set=st.code, name=name, kind="crop", key="crop", path=str(crop))
            job.step(i + 1)
        if failed:
            raise MintError(f"{len(failed)} of {len(todo)} crop(s) could not be fetched from Scryfall: {', '.join(failed[:5])}"
                            + (" ..." if len(failed) > 5 else ""))
        return {"fetched": len(todo)}
    job = S.jobs.submit("crops", f"fetch {len(todo)} crop(s) for {st.code}",
                        {"set": st.code, "names": todo, "what": f"Scryfall's art crop of {len(todo)} card(s) into the art cache",
                         "dest": str(S.art.dir)}, run)
    if origin:
        job.params["origin"] = origin
    return job


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
    what = (f"an ESRGAN pass ({model}) over the {'crop' if base == 'crop' else 'variant ' + base} of {len(names)} card(s); "
            "a new enhance variant each")
    return S.jobs.submit("enhance", title, {"set": st.code if st else None, "names": names, "base": base, "model": model,
                                            "what": what, "dest": str(S.art.dir)}, run)


def submit_animate(S, st, names, body):
    """An animate job (animate.py): a clip of each card's art. `base` is the image to start from (a
    variant hash or "crop"; default the card's styled art), `motion` any knobs over the set's block
    (loop, length, remix ...) for this run alone, and `takes` several clips each from its own random
    seed, as restyle does."""
    overrides = body.get("motion") or {}
    base_knobs = dataclasses.asdict(st.motion or sets.Motion())
    base_knobs.pop("explicit", None)
    base_knobs.update(overrides)
    motion = sets.from_dict({"code": "x", "motion": base_knobs}).motion
    base = body.get("base") or None
    takes = max(1, min(int(body.get("takes") or 1), 8))
    force = bool(body.get("force"))
    seed = body.get("seed")
    seeds = [seed] if takes == 1 else [random.randrange(1, 2 ** 31) for _ in range(takes)]

    def run(job):
        info = S.wan_info()
        if not info["ready"]:
            raise MintError(f"animate cannot run: {info['hint']}")
        server = S.comfy()
        server.require()
        cards = S.cards()
        job.step(0, len(names) * takes)
        made = []
        for i, name in enumerate(names):
            card = cards.find(name, st.card({"name": name}).printing)
            for t, sd in enumerate(seeds):
                v, did = animate.animate(server, S.art, card, st, motion=motion, force=force, seed=sd, base=base)
                take = f"  (take {t + 1}, seed {sd})" if takes > 1 else ""
                job.say(f"{'animated' if did else 'cached'} {name} -> {v.label}-{v.hash}{take}")
                made.append(v.hash)
                job.made(set=st.code, name=name, kind=v.kind, key=v.hash, label=v.label, path=str(v.path))
                job.step(i * takes + t + 1)
        return {"variants": made}
    title = f"animate {len(names)} card(s)" + (f" x {takes} takes" if takes > 1 else "")
    src = f"the {base} image" if base and base != "crop" else "the crop" if base else "each card's styled art"
    what = (f"a {motion.length}-frame clip of {len(names)} card(s) of {st.code} through Wan 2.2 ({motion.remix} mode, "
            f"{motion.loop} loop) from {src}, {takes} take(s) each; about a minute a clip")
    params = {"set": st.code, "names": names, "motion": overrides, "base": base, "takes": takes, "what": what,
              "dest": str(S.art.dir)}
    return S.jobs.submit("animate", title, params, run)


def submit_describe(S, st, names, body):
    """A describe job: a vision model reads each card's base image and its text and writes its
    subject line into the set file (cards that have one are kept unless `force`); with `generate`,
    each card's `new` scene follows in the set's style (or `template`), the one-off mode over
    whatever the style and the entry say, so the variant lands beside the others."""
    force, generate, template = bool(body.get("force")), bool(body.get("generate")), body.get("template")
    info = S.describer_info()
    if not info["ready"]:
        raise HTTPException(400, f"the {info['kind']} describer is not set up: {info['hint']}")
    sty = st.style
    if generate:
        if template:
            sty, _ = style.load(S.ws, template)
        elif sty is None:
            raise HTTPException(400, f"{st.code} has no style block; pick a template to generate as")
    up = bool(body.get("upscale", True))
    per = 2 if generate else 1  # steps per card

    def run(job):
        describer = S.describer()
        server = None
        if generate:
            server = S.comfy()
            server.require()
        cards = S.cards()
        job.step(0, len(names) * per)
        written, made = [], []
        for i, name in enumerate(names):
            entry = st.card({"name": name})
            card = cards.find(name, entry.printing)
            if entry.subject and not force:
                job.say(f"kept {name}: {entry.subject}")
            else:
                d = describe.describe_card(describer, S.art, card, st, entry)
                with S.lock:  # the set file may have moved on since the job was queued: re-read, write one key
                    cur = sets.load(st.path)
                    if name in cur.cards:
                        keep = {k: v for k, v in dataclasses.asdict(cur.cards[name]).items() if v is not None}
                        keep["subject"] = d["subject"]
                        cur.cards[name] = sets.from_dict({"code": "x", "cards": {name: keep}}).cards[name]
                        sets.save(cur.path, cur)
                        st.cards[name] = cur.cards[name]
                job.say(f"described {name}: {d['subject']}")
                written.append(name)
                job.made(set=st.code, name=name, kind="subject", label=d["subject"])
            job.step(i * per + 1)
            if generate:
                v, did = restyle.restyle(server, S.art, card, st, style=sty, upscale=up, remix="new")
                job.say(f"{'new scene' if did else 'cached'} {name} -> {v.label}-{v.hash}")
                made.append(v.hash)
                job.made(set=st.code, name=name, kind=v.kind, key=v.hash, label=v.label, path=str(v.path))
                job.step(i * per + 2)
        return {"subjects": written, "variants": made}
    title = (f"new cards: {len(names)} card(s) as {sty.name}" if generate else f"describe {len(names)} card(s)") + \
            (", rewriting subjects" if force else "")
    what = (f"{info['kind']} ({info['model']}) reads each card's base image and text and writes its subject line into "
            f"{st.code}'s file" + (" (cards with one are kept)" if not force else "") +
            (f"; then a new scene from it in the look {sty.name}, whatever mode the style or the card says" if generate else ""))
    params = {"set": st.code, "names": names, "force": force, "generate": generate, "template": template,
              "label": sty.name if sty else None, "what": what, "dest": str(st.path)}
    return S.jobs.submit("describe", title, params, run)


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
