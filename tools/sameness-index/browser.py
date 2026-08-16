"""
Sameness Index — the browser of last resort.

The crawler reads pages over HTTP, because that is fast, cheap, and enough for
most of the web. It is not enough for a large share of pharma brand sites,
which assemble their copy in the browser and serve a shell to anything that
will not run JavaScript. A shell parses perfectly and says nothing, which is
the worst kind of failure: it does not look like a failed read, it looks like a
brand with very little to say. Roughly half the sites that fail, fail this way.

So there is a real browser here — used as an exception, never as the rule. A
page reaches it only when the plain fetch came back blocked, or came back with
too few words in it to be a brand page. Most pages never touch it, and a run
against well-behaved sites costs exactly what it did before.

One browser, shared by every run. Not one per run: Chromium needs the better
part of a gigabyte to render a page reliably and the service has two, so a
browser per concurrent run would exhaust the box before the second run
finished. Pages are taken from a bounded pool and a run that wants one waits.
Each render gets its own context, so one site's cookies and consent state never
leak into the next site's read.

Everything here fails soft. If Chromium is not installed, if the launch fails,
if a page hangs — the answer is None and the crawler carries on with what plain
HTTP gave it. A tool that will not run without a browser is worse than one that
reads a few sites badly.

Switches, all environment:
    SAMENESS_BROWSER=off        never render; HTTP only
    SAMENESS_BROWSER_PAGES=2    pages open at once, across all runs
"""

import asyncio
import os

try:
    from playwright.async_api import async_playwright
except Exception:                       # not installed — HTTP only, and say so
    async_playwright = None

ENABLED = os.environ.get("SAMENESS_BROWSER", "on").strip().lower() not in (
    "0", "off", "no", "false", ""
)
MAX_PAGES = int(os.environ.get("SAMENESS_BROWSER_PAGES", "2"))

# Chromium in a container. --no-sandbox because there is no user namespace to
# sandbox into; --disable-dev-shm-usage because /dev/shm is 64MB by default and
# Chromium will happily fill it and die.
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--mute-audio",
    "--no-first-run",
    "--hide-scrollbars",
]

# Not fetched. Video and audio are never the messaging, and web fonts are a
# download to draw glyphs nobody is going to look at. Images and stylesheets
# are left alone: the image inventory reads what the page loads, and the next
# piece of work screenshots these pages as evidence, which needs them drawn.
BLOCKED_RESOURCES = {"media", "font"}


class Rendered:
    """What a render produces. Shaped like the crawler's other responses."""

    __slots__ = ("url", "status", "html")

    def __init__(self, url, status, html):
        self.url, self.status, self.html = url, status, html


class Renderer:
    """One shared Chromium, started on first use and never before.

    Starting it at import would pay a second and a gigabyte on every deploy,
    including the deploys where nobody runs anything. Starting it on the first
    page that needs it costs that once, on a run that was already going to be
    slow.
    """

    def __init__(self, pages=MAX_PAGES):
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(max(1, pages))
        self.pages = max(1, pages)
        self.renders = 0          # pages successfully rendered, this process
        self.failures = 0
        self.why = ""             # why it is unavailable, in words

    # -- lifecycle ---------------------------------------------------------

    async def _ensure(self):
        """A live browser, or None. Safe to call from anywhere, any number of
        times, concurrently."""
        if not ENABLED:
            self.why = "switched off"
            return None
        if async_playwright is None:
            self.why = "playwright is not installed"
            return None
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._lock:
            # Another caller may have won the race while we waited.
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            await self._teardown()
            try:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True, args=LAUNCH_ARGS,
                )
                self.why = ""
                return self._browser
            except Exception as e:
                # Almost always a missing Chromium binary. Say which, once, in
                # the health endpoint rather than in every failed page.
                self.why = f"{type(e).__name__}: {e}"[:200]
                await self._teardown()
                return None

    async def _teardown(self):
        for obj, stop in ((self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    await getattr(obj, stop)()
                except Exception:
                    pass
        self._browser = None
        self._pw = None

    async def close(self):
        async with self._lock:
            await self._teardown()

    # -- the one thing it does ---------------------------------------------

    async def render(self, url, timeout=30, user_agent=None, locale="en-GB"):
        """The page as a browser sees it, or None.

        None is not an error to report to anyone. It means the crawler keeps
        whatever plain HTTP gave it, which is what it would have had anyway.
        """
        browser = await self._ensure()
        if browser is None:
            return None
        async with self._slots:
            context = None
            try:
                context = await browser.new_context(
                    user_agent=user_agent,
                    locale=locale,
                    viewport={"width": 1366, "height": 2200},
                    ignore_https_errors=True,
                )
                context.set_default_timeout(timeout * 1000)
                await context.route("**/*", _skip_the_heavy_things)
                page = await context.new_page()
                resp = await page.goto(
                    url, wait_until="domcontentloaded", timeout=timeout * 1000,
                )
                # The copy arrives after the document does — that is the whole
                # reason for being here. Wait for the network to settle, but
                # never for long: an analytics beacon on a timer can keep a
                # page "busy" indefinitely, and by then the words are there.
                try:
                    await page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                html = await page.content()
                self.renders += 1
                return Rendered(page.url or url,
                                resp.status if resp is not None else 200,
                                html)
            except Exception:
                self.failures += 1
                return None
            finally:
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass

    # -- for /api/health ---------------------------------------------------

    def status(self):
        return {
            "enabled": ENABLED and async_playwright is not None,
            "running": self._browser is not None and self._browser.is_connected(),
            "pages": self.pages,
            "rendered": self.renders,
            "failed": self.failures,
            "why": self.why,
        }


async def _skip_the_heavy_things(route):
    try:
        if route.request.resource_type in BLOCKED_RESOURCES:
            await route.abort()
        else:
            await route.continue_()
    except Exception:
        pass


# The one shared instance. Import this, not the class.
renderer = Renderer()
