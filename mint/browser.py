"""One headless Chromium, shared by everything that renders.

    with Browser(dpi=1200) as b:
        sizes = b.render(html, "card.png")

The page is 272x372 CSS px (1 px = 1/100 in, the card plus bleed) and the
device scale factor turns DPI into pixels: 1200 DPI is 3264x4464.
"""
import os
import tempfile

# the template is 100 CSS px per inch; the card is 2.5x3.5in plus 0.11in bleed
PAGE = {"width": 272, "height": 372}


class Browser:
    def __init__(self, dpi=1200):
        self.dpi = dpi
        self._pw = self._browser = self._ctx = self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        # full Chromium in new-headless mode: no separate headless-shell download
        self._browser = self._pw.chromium.launch(channel="chromium")
        self._ctx = self._browser.new_context(viewport=PAGE, device_scale_factor=self.dpi / 100)
        self.page = self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def render(self, html, out, fit=True):
        """Screenshot html to out. Returns the shrink-to-fit result {"text": px, "name": px, "type": px}, or None."""
        # Chromium needs a file:// page for the file:// art and font references to resolve
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(html)
        try:
            # fonts are fetched lazily once layout asks for them, so wait for the
            # network to go quiet, then for the font set to settle, *then* fit text
            self.page.goto("file://" + f.name, wait_until="networkidle")
            self.page.evaluate("document.fonts.ready")
            sizes = None
            if fit:
                fs, ns, ts = self.page.evaluate("fit()")
                sizes = {"text": round(fs, 2), "name": round(ns, 2), "type": round(ts, 2)}
            self.page.screenshot(path=str(out), clip={"x": 0, "y": 0, **PAGE})
            return sizes
        finally:
            os.unlink(f.name)

    def pdf(self, html_path, out, width, height):
        """Print a file:// document to a PDF at exactly the given page size (CSS lengths, e.g. "8.5in")."""
        page = self._browser.new_page()
        try:
            page.goto("file://" + os.path.abspath(html_path), wait_until="networkidle")
            page.pdf(path=str(out), width=width, height=height, print_background=True, prefer_css_page_size=True)
        finally:
            page.close()
