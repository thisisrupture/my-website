"""
Sameness Index — the browser.

Two jobs, one Chromium.

**Reading.** Most of the web answers a plain HTTP request with the words on the
page. A large share of pharma brand sites do not: they assemble their copy in
the browser and serve a shell to anything that will not run JavaScript. A shell
parses perfectly and says nothing, which does not look like a failed read — it
looks like a brand with very little to say. So a page that comes back blocked or
empty is opened here instead, and read as a visitor would read it.

**Showing.** The report's whole claim to credibility is that every number is one
click from the evidence that produced it. A link is a weak version of that: the
site may have changed, the gate may eat the text fragment, the browser may not
honour it. A picture of the sentence, highlighted on the competitor's own page,
on a stated date, is the strong version. While the page is open anyway, it is
nearly free to take one.

One browser, shared by every run. Not one per run: Chromium needs the better
part of a gigabyte to render a page reliably and the service has two, so a
browser per concurrent run would exhaust the box before the second finished.
Pages come from a bounded pool and a run that wants one waits. Each page gets
its own context, so one site's consent state never leaks into the next site's
read.

Everything fails soft. No Chromium, a failed launch, a page that hangs — the
answer is None and the caller keeps whatever plain HTTP gave it. A tool that
will not run without a browser is worse than one that reads a few sites badly.

On getting in. Permission is asked before anything here runs: robots.txt is
consulted by the caller and honoured without exception. What this file deals
with is capability — the fact that a site which publishes a page to the public
web, and invites crawlers in its own robots.txt, will still turn away a client
that does not look like a browser. So the browser looks like a browser: the
automation flags a page can read are removed, and the front door is opened by
clicking the button a visitor would click. Nothing here logs in, defeats a
CAPTCHA, or touches a page a site has asked us not to read.

Switches, all environment:
    SAMENESS_BROWSER=off        never render; HTTP only
    SAMENESS_BROWSER_PAGES=2    pages open at once, across all runs
"""

import asyncio
import os
import re

try:
    from playwright.async_api import async_playwright
except Exception:                       # not installed — HTTP only, and say so
    async_playwright = None

ENABLED = os.environ.get("SAMENESS_BROWSER", "on").strip().lower() not in (
    "0", "off", "no", "false", ""
)
MAX_PAGES = int(os.environ.get("SAMENESS_BROWSER_PAGES", "2"))

VIEWPORT = {"width": 1366, "height": 900}

# Chromium in a container. --no-sandbox because there is no user namespace to
# sandbox into; --disable-dev-shm-usage because /dev/shm is 64MB by default and
# Chromium will fill it and die. AutomationControlled is the flag that puts
# "HeadlessChrome" in the UA and navigator.webdriver in the page.
LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--mute-audio",
    "--no-first-run",
    "--hide-scrollbars",
]

# What a page can check to see whether it is being read by a person. None of it
# is a secret and none of it is a defence — it is a handful of properties that
# a real Chrome has and an automated one, by default, does not. Setting them is
# the difference between being served the page and being served a wall, on sites
# whose robots.txt explicitly invites us.
STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'plugins',
  {get: () => [{name: 'PDF Viewer'}, {name: 'Chrome PDF Viewer'}, {name: 'Native Client'}]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en']});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
try {
  const q = navigator.permissions.query.bind(navigator.permissions);
  navigator.permissions.query = p =>
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission, onchange: null})
      : q(p);
} catch (e) {}
"""

# Never fetched. Video and audio are never the messaging, and a web font is a
# download to draw glyphs. Images and stylesheets are left alone: the report
# photographs these pages, and a screenshot of a page with no CSS is evidence
# of nothing.
BLOCKED_RESOURCES = {"media", "font"}

# The mark drawn around the sentence being photographed. Rupture coral, at the
# weight of a highlighter rather than a border, so the picture reads as the
# competitor's page with one sentence pointed at — not as a Rupture graphic.
HIGHLIGHT_CSS = """
.rupture-mark {
  background: rgba(254, 24, 73, 0.16) !important;
  box-shadow: 0 0 0 2px rgba(254, 24, 73, 0.85) !important;
  border-radius: 2px !important;
}
"""

# Finding a sentence on a page and drawing round it.
#
# Returns how the match was made, because the report says so: "the sentence" is
# a stronger claim than "the paragraph it sits in", and the reader is told which
# they are looking at.
MARK_JS = """
(sentence) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const target = norm(sentence).toLowerCase();
  if (target.length < 12) return null;

  const style = document.createElement('style');
  style.textContent = %CSS%;
  document.head.appendChild(style);

  // The smallest element whose text contains the sentence. Smallest, because
  // <body> contains it too and photographing the body is photographing nothing.
  const blocks = document.querySelectorAll(
    'p,li,h1,h2,h3,h4,h5,span,div,td,blockquote,figcaption,dd,a,strong');
  let block = null;
  for (const el of blocks) {
    if (norm(el.textContent).toLowerCase().includes(target)) {
      if (!block || (el.textContent || '').length < (block.textContent || '').length) block = el;
    }
  }
  if (!block) return null;

  // Inside it, the exact run of text — so the mark sits on the sentence rather
  // than on everything around it. A sentence split across elements by a <br>
  // or a <strong> will not be found this way, and falls back to the block.
  let how = 'block';
  const walk = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walk.nextNode())) {
    const raw = node.nodeValue || '';
    const i = norm(raw).toLowerCase().indexOf(target);
    if (i < 0) continue;
    // Map the position in the whitespace-collapsed string back to the raw one.
    let seen = -1, start = -1, end = -1, ws = true;
    for (let j = 0; j < raw.length; j++) {
      const isws = /\\s/.test(raw[j]);
      if (isws && ws) continue;
      seen += 1;
      if (seen === i) start = j;
      if (seen === i + target.length - 1) { end = j + 1; break; }
      ws = isws;
    }
    if (start < 0) continue;
    if (end < 0) end = raw.length;
    try {
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, end);
      const mark = document.createElement('mark');
      mark.className = 'rupture-mark';
      range.surroundContents(mark);
      how = 'sentence';
      block = mark;
    } catch (e) { /* a range crossing elements cannot be wrapped */ }
    break;
  }
  if (how === 'block') block.classList.add('rupture-mark');

  block.scrollIntoView({block: 'center', inline: 'nearest'});
  const r = block.getBoundingClientRect();
  return {how: how, top: r.top, height: r.height, left: r.left, width: r.width};
}
""".replace("%CSS%", "`" + HIGHLIGHT_CSS + "`")


class Rendered:
    """What one visit produces. Shaped like the crawler's other responses."""

    __slots__ = ("url", "status", "html", "gates", "hero", "shots")

    def __init__(self, url, status, html, gates=0, hero=None, shots=None):
        self.url, self.status, self.html = url, status, html
        self.gates = gates          # front doors clicked through
        self.hero = hero            # bytes | None
        self.shots = shots or {}    # quote index -> {"png": bytes, "how": str}


class Renderer:
    """One shared Chromium, started on first use and never before."""

    def __init__(self, pages=MAX_PAGES):
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(max(1, pages))
        self.pages = max(1, pages)
        self.renders = 0
        self.captures = 0
        self.failures = 0
        self.why = ""

    # -- lifecycle ---------------------------------------------------------

    async def _ensure(self):
        if not ENABLED:
            self.why = "switched off"
            return None
        if async_playwright is None:
            self.why = "playwright is not installed"
            return None
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._lock:
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

    # -- one visit ---------------------------------------------------------

    async def visit(self, url, *, timeout=35, user_agent=None, locale="en-GB",
                    accept_texts=(), gate_ceiling=2200, gate_hops=2,
                    quotes=(), want_hero=False):
        """Open a page, get past the front door, and come back with what was
        asked for: the HTML, optionally a hero image, optionally a photograph of
        each quoted sentence highlighted where it sits.

        One page load for all of it. Returns None on any failure, which is not
        an error to report to anyone — the caller keeps what it already had.
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
                    timezone_id="Europe/London",
                    viewport=VIEWPORT,
                    device_scale_factor=2,      # a legible screenshot
                    ignore_https_errors=True,
                )
                context.set_default_timeout(timeout * 1000)
                await context.add_init_script(STEALTH)
                await context.route("**/*", _skip_the_heavy_things)
                page = await context.new_page()

                resp = await page.goto(url, wait_until="domcontentloaded",
                                       timeout=timeout * 1000)
                await _settle(page)
                gates = await _through_the_front_door(
                    page, accept_texts, gate_ceiling, gate_hops)

                html = await page.content()
                hero = await _hero(page) if want_hero else None
                shots = {}
                for i, quote in enumerate(quotes or ()):
                    shot = await _photograph(page, quote)
                    if shot:
                        shots[i] = shot

                self.renders += 1
                if hero or shots:
                    self.captures += 1
                return Rendered(page.url or url,
                                resp.status if resp is not None else 200,
                                html, gates=gates, hero=hero, shots=shots)
            except Exception:
                self.failures += 1
                return None
            finally:
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass

    async def render(self, url, timeout=30, **kw):
        """Read only. The common case, and the one the crawler calls."""
        return await self.visit(url, timeout=timeout, **kw)

    # -- for /api/health ---------------------------------------------------

    def status(self):
        return {
            "enabled": ENABLED and async_playwright is not None,
            "running": self._browser is not None and self._browser.is_connected(),
            "pages": self.pages,
            "rendered": self.renders,
            "captured": self.captures,
            "failed": self.failures,
            "why": self.why,
        }


# ---------------------------------------------------------------------------
# The things done to a page once it is open
# ---------------------------------------------------------------------------

async def _settle(page):
    """Wait for the copy, but never for long. An analytics beacon on a timer can
    keep a page 'busy' indefinitely, and by then the words are there."""
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass


async def _through_the_front_door(page, accept_texts, ceiling, hops):
    """Click the button a visitor would click.

    Almost every pharma brand site puts something between the visitor and the
    content: a region selector, an "are you a US healthcare professional?"
    attestation, a consent wall. Following the link behind it was a guess that
    often took the wrong one; clicking it is what a person does, and it leaves
    the page on the address the words are actually served from — which is what
    keeps the evidence link and the screenshot pointing at the same place.
    """
    clicked = 0
    for _ in range(max(0, hops)):
        try:
            body = await page.inner_text("body", timeout=4000)
        except Exception:
            break
        if len(body or "") > ceiling:
            break                       # this is a page, not a door
        target = await _find_the_way_in(page, accept_texts)
        if target is None:
            break
        try:
            async with page.expect_navigation(wait_until="domcontentloaded",
                                              timeout=12000):
                await target.click(timeout=6000)
        except Exception:
            # A consent wall usually dismisses in place with no navigation.
            try:
                await target.click(timeout=4000)
            except Exception:
                break
        clicked += 1
        await _settle(page)
    return clicked


async def _find_the_way_in(page, accept_texts):
    """The most specific control that gets you through, or None.

    Ordered by the caller: "i am a us healthcare professional" is tried before
    "continue", because "continue" is also written on cookie banners.
    """
    for phrase in accept_texts:
        for sel in ("button", "a", "input[type=submit]", "[role=button]"):
            try:
                loc = page.locator(sel).filter(
                    has_text=re.compile(r"^\s*" + re.escape(phrase) + r"\s*$",
                                        re.I))
                if await loc.count():
                    el = loc.first
                    if await el.is_visible():
                        return el
            except Exception:
                continue
    # Nothing matched exactly; allow a control that contains the phrase.
    for phrase in accept_texts:
        try:
            loc = page.get_by_role("button", name=phrase, exact=False)
            if await loc.count() and await loc.first.is_visible():
                return loc.first
            loc = page.get_by_role("link", name=phrase, exact=False)
            if await loc.count() and await loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


async def _hero(page):
    """The top of the page as a visitor first sees it."""
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(400)      # let the images above the fold in
        return await page.screenshot(type="jpeg", quality=78, full_page=False)
    except Exception:
        return None


async def _photograph(page, quote):
    """The quoted sentence, highlighted where it sits, in a band of the page.

    A band rather than the sentence alone: a crop tight to the words could be
    anything, typed anywhere. Framed by the page around it, it is recognisably
    the competitor's own site.
    """
    try:
        found = await page.evaluate(MARK_JS, quote)
    except Exception:
        return None
    if not found:
        return None
    try:
        # Framing. A sentence near the top of the page is photographed from the
        # very top, so the site's own header comes with it — the brand's name and
        # the audience it is talking to are the two things that make the picture
        # self-evidently theirs. Further down the page, a band with the sentence
        # a little above centre.
        mark_top = float(found["top"])
        y = 0.0 if mark_top < 470 else max(0.0, mark_top - 200)
        height = min(float(VIEWPORT["height"]) - y,
                     max(300.0, (mark_top - y) + float(found["height"]) + 220))
        png = await page.screenshot(
            type="jpeg", quality=80,
            clip={"x": 0, "y": y, "width": VIEWPORT["width"], "height": height})
        return {"png": png, "how": found.get("how") or "block"}
    except Exception:
        return None
    finally:
        # Leave the page as it was found, so the next quote is not photographed
        # with the last one still lit up.
        try:
            await page.evaluate(
                "document.querySelectorAll('.rupture-mark')"
                ".forEach(m => m.classList.remove('rupture-mark'))")
        except Exception:
            pass


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
