"""
Sameness Index — analysis server.

Serves the front end and runs the pipeline: read each brand's public site,
strip the mandated layer, separate the molecule-determined layer, build the
opportunity space (observed + exogenous), code every brand against every
position with verbatim evidence, tier availability, code the hero imagery,
compute the metrics deterministically, and write the findings.

A run takes two to five minutes, which is longer than a browser will hold a
request open and longer than most hosts allow one to last. So POST /api/run
returns a run id immediately and the work continues in the background, writing
its narration and its result to the store. The page polls GET /api/run/{id}
for the narration as it appears, and the finished result stays at /r/{id} for
anyone with the link.

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=sk-ant-...
    export DATABASE_URL=postgresql://...     # optional locally; see DEPLOY.md
    uvicorn server:app --reload
Then open http://127.0.0.1:8000

The methodology is methodology.md. The metrics are score.py, ported unchanged.
"""

import asyncio
import base64
import json
import math
import os
import random
import re
from collections import Counter
from contextlib import asynccontextmanager
from itertools import combinations
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

import drugs
from store import Store

MODEL = os.environ.get("SAMENESS_MODEL", "claude-sonnet-5")
MAX_PAGES_PER_BRAND = 6
MAX_CHARS_PER_BRAND = 28000
HERE = os.path.dirname(os.path.abspath(__file__))

# Cost control. Every run crawls real sites and makes a dozen model calls, and
# a public URL is a public URL. Both are deliberately generous for a human and
# useless for a script.
MAX_RUNS_PER_IP_PER_DAY = int(os.environ.get("SAMENESS_RUNS_PER_IP", "5"))
MAX_CONCURRENT_RUNS = int(os.environ.get("SAMENESS_MAX_CONCURRENT", "3"))
MAX_BRANDS_PER_RUN = 7
# Below this many elective fragments a brand has not really been read, whatever
# the page weighed. Set low: a thin brand site is a finding, an empty one is a
# wrong address.
MIN_ELECTIVES = 5
# Rupture palette. Mint is reserved as a highlight, not a brand accent —
# it lacks contrast against the paper at label sizes.
ACCENTS = ["#FF686B", "#1F5B4A", "#303030", "#727270", "#51D4B2", "#ABAAA8", "#D7D6D2"]
# Large pharma sites sit behind bot protection that rejects anything not
# shaped like a browser — Lilly's turned away a plainly-identified client while
# serving the same pages to a normal one. The request is otherwise unchanged:
# public pages only, read once, nothing behind a login, no attempt at volume.
# The tool still names itself and gives a contact address at the end of the
# string, so anyone reading their logs can see exactly what it is.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 "
      "SamenessIndex/0.2 (+https://thisisrupture.com; strategy research, reads public pages once)")

BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

@asynccontextmanager
async def lifespan(_app):
    await store.start()
    # Built in the background: the server must answer requests while roughly
    # thirty openFDA pages are fetched, not after.
    asyncio.create_task(_build_index_once())
    yield
    await store.stop()


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def any_error(_request, exc):
    """Whatever breaks, the client gets JSON.

    Starlette's default is an HTML error page. The front end asks for JSON,
    tries to parse the HTML, and reports "Unexpected token 'I'" — which tells
    the person nothing and tells us nothing either. This says what happened.
    """
    import traceback
    traceback.print_exc()          # the detail goes to the Render log
    return JSONResponse(
        {"error": f"Something failed on our side: {type(exc).__name__}. "
                  "It has been logged. Try again, or get in touch if it keeps happening."},
        status_code=500,
    )

_client = None


def get_client():
    """Built on first use, not at import. A missing key should fail the run with
    a sentence the user can act on, not stop the server from starting."""
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. The index needs it to read and code the sites. "
                "Set it in your shell and restart the server."
            )
        _client = AsyncAnthropic()
    return _client

# ---------------------------------------------------------------------------
# Methodology fragments embedded in every prompt, so the rules applied are the
# rules shown to the user. Keep these in sync with methodology.md.
# ---------------------------------------------------------------------------

LAYER_RULES = """
Every element of copy belongs to exactly one layer.

LAYER 1 — MANDATED. Exists because a regulator requires it: safety information,
boxed warnings, contraindications, adverse reaction lists, the indication
statement, prescribing information links, adverse event reporting numbers,
copay terms and conditions, privacy and cookie notices, "actor portrayal" and
"individual results may vary" disclaimers. STRIP ENTIRELY. Nobody chose a word
of it and its volume varies by molecule, not by marketing.

LAYER 2 — MOLECULE-DETERMINED. Technically elective but constrained by what
the molecule is, what the label permits, and what the trials measured:
mechanism of action and target class, approved population and age floor,
dosing frequency and duration, trial names and design, endpoint results,
comparator data, product form, guideline recognition. RETAIN SEPARATELY.
Convergence here is chemistry, not strategy.

LAYER 3 — ELECTIVE. Everything remaining: how the disease is named and
characterised, how the unmet need is framed, who the patient is understood to
be, what the category's failure is taken to be, what relief is framed as,
emotional register, metaphor and motif, tone, hierarchy and what is placed
first. THIS IS WHAT GETS SCORED.

BOUNDARY RULES, applied identically to every brand:
- A factual property of the molecule class is layer 2; the consequence framing
  of that property is layer 3. ("Steroid-free" is 2; "steroid-free, so you can
  use it where steroids scare you" is 3.)
- Label-determined dosing is layer 2; a claimed benefit built on it is layer 3.
  ("Once daily" is 2; "simple once-daily treatment" is 3 — "simple" is a claim.)
- An age floor is layer 2; the decision to dramatise it is layer 3.
- Endpoint percentages are layer 2; which endpoint is placed first is layer 3.
- A mechanism explanation is layer 2; a mechanism analogy or metaphor is layer 3.
AMBIGUITY DEFAULT: where an element could sit in either layer, assign layer 2.
This biases toward under-reporting convergence, which is the conservative
direction.
"""

TIER_RULES = """
Every messaging territory carries an availability rating, with reasoning written
for a brand lead in plain commercial English. "Messaging territory" is the one
piece of established industry vocabulary in use — beyond it, avoid spatial
metaphor. Write "use this territory", not "stand on this ground" or "own this
space":
- open: requires no new clinical evidence. A decision about how the disease is
  described, who the communications address, or where they appear.
- frame_only: the patient need can be described in disease education, because
  published evidence supports describing it. Saying the product improves it
  would need a trial endpoint that does not exist.
- constrained: legally available, but needs supporting evidence and careful
  wording, and risks being read as a comparative or disparaging claim about
  competitors. Expect close review.
- closed: cannot be used without clinical data nobody has generated, or would
  require taking a position on a clinical question the field has not settled.
"""

GENERIC_BOUNDARY_RULES = [
    {"element": "Factual property of the molecule class", "layer": 2, "rule": "Chemistry, not strategy. Universal or near-universal in the category."},
    {"element": "Consequence framing of that property", "layer": 3, "rule": "What the fact is said to mean for the patient is elective."},
    {"element": "Label-determined dosing", "layer": 2, "rule": "The regulator wrote it."},
    {"element": "A benefit claimed on the back of the dosing (“simple”, “easy”)", "layer": 3, "rule": "The adjective is a claim, not a fact."},
    {"element": "Approved population and age floor", "layer": 2, "rule": "Trial and label determined."},
    {"element": "Imagery dramatising the age floor", "layer": 3, "rule": "The decision to cast it is elective."},
    {"element": "Endpoint percentages", "layer": 2, "rule": "Trial output."},
    {"element": "Which endpoint is placed first", "layer": 3, "rule": "Hierarchy is a positioning decision."},
    {"element": "Clinical photography", "layer": 2, "rule": "Trial asset."},
    {"element": "Lifestyle photography", "layer": 3, "rule": "Commissioned."},
    {"element": "Mechanism of action explanation", "layer": 2, "rule": "Pharmacology."},
    {"element": "Mechanism analogy or metaphor", "layer": 3, "rule": "Explanatory framing is elective."},
]

VISUAL_TIER_RULES = """
Every visual territory carries an availability rating, on the same four-point
scale as the messaging territories, read for art direction rather than copy:
- open: a casting, setting or treatment decision. Needs no new evidence and no
  new claim — somebody simply has to choose it.
- frame_only: the situation can be depicted as part of the disease, because
  published evidence supports describing it. Depicting it as something the
  product resolves would need an endpoint that does not exist.
- constrained: usable, but the image itself carries an implied claim — showing
  severity, showing a result, showing an age group, showing a body site — and
  needs supporting evidence and careful treatment. Expect close review.
- closed: cannot be depicted without clinical data nobody has generated, or
  would depict something the label does not permit.
"""

PROVENANCE_LABELS = {
    "C": "observed in category",
    "X": "patient burden literature",
    "H": "clinical barrier literature",
}

# The reader never sees the internal tier word. These are the labels on the page.
TIER_READER_LABELS = {
    "open": "Explore now",
    "frame_only": "Raise, not claim",
    "constrained": "Needs substantiation",
    "closed": "Not viable",
}

# ---------------------------------------------------------------------------
# The convergence score.
#
# For one brand: of the territories it uses, the share that at least one rival
# also uses. For the category: the mean of those, across the brands analysed.
# The same calculation is applied to messaging and to imagery, and the headline
# score is the mean of the two.
#
# It is deliberately per-brand-then-averaged rather than a single category-wide
# ratio. A category-wide ratio is dominated by whichever brand says the most;
# this gives each brand equal weight, which is how a brand lead reads their own
# position. The category ratio is still on the page — it survives as
# `crowding_rate` in the working.
# ---------------------------------------------------------------------------

BANDS = [
    {"to": 40, "name": "Distinct", "cls": "good",
     "note": "Brands are saying different things. There is still advantage available inside the current frame."},
    {"to": 60, "name": "Converging", "cls": "mid",
     "note": "The category is drifting together. Differentiation still exists, but it thins with every cycle."},
    {"to": 80, "name": "Converged", "cls": "bad",
     "note": "Most of what each brand says, a rival also says. Messaging no longer separates the field."},
    {"to": 101, "name": "Indistinguishable", "cls": "bad",
     "note": "The category speaks with one voice. Share of voice is the only lever left inside this frame."},
]


def r0(x):
    """Round half up, to a whole number.

    Python's round() breaks ties to even and JavaScript's Math.round() rounds
    half up, so a score landing on .5 came out one point lower on the server
    than the page recalculated it — the same figure disagreeing with itself.
    Every score on this page goes through here, and the front end uses
    Math.round, which now means the same thing.
    """
    return int(math.floor(float(x) + 0.5))


def band_for(score):
    for b in BANDS:
        if score < b["to"]:
            return {k: v for k, v in b.items() if k != "to"}
    return {k: v for k, v in BANDS[-1].items() if k != "to"}


def convergence(positions, brands):
    """Per-brand convergence over one inventory, and the mean across brands.

    `positions` must already carry `claimers`. A brand that uses nothing scores
    zero and is still counted — having nothing to say is not distinctiveness.
    """
    per, empty = [], []
    for b in brands:
        used = [p for p in positions if b in p["claimers"]]
        if not used:
            # Scoring this brand zero would read as perfect distinctiveness and
            # drag the category score down with it. A brand that uses nothing
            # was not read; it is not distinctive.
            empty.append(b)
            continue
        shared = [p for p in used if len(p["claimers"]) > 1]
        per.append({
            "brand": b,
            "used": len(used),
            "shared": len(shared),
            "alone": len(used) - len(shared),
            "pct": r0(len(shared) / len(used) * 100),
            "shared_ids": [p["id"] for p in shared],
            "alone_ids": [p["id"] for p in used if len(p["claimers"]) == 1],
        })
    mean = r0(sum(p["pct"] for p in per) / len(per)) if per else 0
    return {"per": per, "mean": mean, "not_scored": empty}


# ---------------------------------------------------------------------------
# Crawling
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Fetching, and asking permission first
#
# Two separate questions, and they are easy to confuse.
#
# May we read this? Answered by robots.txt, which is where a site states in
# machine-readable form what it wants crawlers to do. It is honoured here
# without exception: a path a site has asked us not to read is not read, and a
# site that disallows us entirely is reported as such rather than worked around.
#
# Can we read this? A different matter. Large pharma sites sit behind
# protection that fingerprints the TLS handshake, so a Python client is turned
# away no matter what its headers say — including on sites whose own robots.txt
# explicitly invites crawlers and publishes a sitemap. Where permission has been
# given, the connection is made to look like the browser it would have to be to
# read the same page by hand.
#
# Permission first, capability second. Never the other way round.
# ---------------------------------------------------------------------------

try:
    from curl_cffi.requests import AsyncSession as _ImpersonatingSession
except Exception:
    _ImpersonatingSession = None

IMPERSONATE = os.environ.get("SAMENESS_IMPERSONATE", "chrome")


class Fetcher:
    """One interface over two clients, with robots.txt consulted once per host.

    curl_cffi presents a real browser's TLS fingerprint; httpx is the fallback
    when it is not installed. Responses are normalised to the few attributes
    the crawler needs.
    """

    def __init__(self, http):
        self.http = http
        self.session = _ImpersonatingSession() if _ImpersonatingSession else None
        self.robots = {}

    async def close(self):
        if self.session is not None:
            try:
                await self.session.close()
            except Exception:
                pass

    async def get(self, url, timeout=25):
        if self.session is not None:
            try:
                r = await self.session.get(
                    url, impersonate=IMPERSONATE, timeout=timeout,
                    allow_redirects=True, headers={"Accept-Language": BROWSER_HEADERS["Accept-Language"]},
                )
                return SimpleResponse(str(r.url), r.status_code, r.headers, r.text)
            except Exception:
                pass  # fall through to httpx rather than fail the page
        r = await self.http.get(url, headers=BROWSER_HEADERS, follow_redirects=True, timeout=timeout)
        return SimpleResponse(str(r.url), r.status_code, r.headers, r.text)

    async def allowed(self, url):
        """What robots.txt says. A site with no robots.txt, or one we cannot
        fetch, is treated as permitting — that is what the standard says, and
        assuming refusal would silently exclude most of the web."""
        p = urlparse(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in self.robots:
            rp = RobotFileParser()
            try:
                r = await self.get(f"{host}/robots.txt", timeout=12)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                rp.parse([])
            self.robots[host] = rp
        return self.robots[host].can_fetch("*", url)


class SimpleResponse:
    __slots__ = ("url", "status_code", "headers", "text")

    def __init__(self, url, status_code, headers, text):
        self.url, self.status_code, self.text = url, status_code, text
        self.headers = {k.lower(): v for k, v in dict(headers).items()}


PRIORITY_HINTS = [
    "about", "why", "how", "what-is", "efficacy", "results", "safety",
    "patients", "hcp", "dosing", "getting-started", "science", "support",
    "savings", "cost", "access", "caregiver", "resources",
]


# ---------------------------------------------------------------------------
# Getting past the front door.
#
# Almost every pharma brand site puts something between the visitor and the
# content: a region selector, an "are you a US healthcare professional?" gate,
# or a consent wall. A crawler that does not handle these reads two hundred
# words of legal text and reports it as the brand's messaging — which is worse
# than failing, because it looks like a result. It is also what silently
# destroys the highlight links, since a text fragment does not survive the
# redirect a gate performs.
# ---------------------------------------------------------------------------

GATE_PHRASES = [
    "healthcare professional", "health care professional", "hcp only",
    "are you a", "select your country", "choose your country", "select your region",
    "choose your location", "intended for residents", "intended for us residents",
    "intended only for", "this site is intended", "leaving this site",
    "by entering this site", "confirm you are", "please select",
    "cookie", "cookies", "privacy preferences", "consent",
    "age verification", "you must be",
]

# Text on the control that gets you through. Ordered: the most specific wins,
# because "continue" appears on cookie banners as well as region gates.
GATE_ACCEPT = [
    "i am a us healthcare professional", "us healthcare professional",
    "healthcare professional", "hcp", "i am a healthcare professional",
    "united states", "usa", "u.s.", "united kingdom",
    "i am a patient", "patient or caregiver", "patient",
    "i agree", "i accept", "accept all", "accept all cookies", "accept cookies",
    "agree and continue", "accept and continue", "continue", "enter site",
    "enter", "proceed", "yes", "confirm",
]

GATE_TEXT_CEILING = 2200   # a real brand page carries far more than this


def looks_like_a_gate(text, soup):
    """A short page whose words are all about permission rather than product."""
    if len(text) > GATE_TEXT_CEILING:
        return False
    low = text.lower()
    hits = sum(1 for p in GATE_PHRASES if p in low)
    if hits >= 2:
        return True
    # A page that is almost nothing but buttons is a gate whatever it says.
    controls = len(soup.find_all(["button", "a"]))
    return hits >= 1 and len(text) < 900 and controls <= 40


def gate_exit(soup, landed):
    """The most likely way through, or None.

    Only same-site destinations are followed. A gate offering "leave this site"
    is offering the one link we must not take.
    """
    root = urlparse(landed).netloc.replace("www.", "")
    best, best_rank = None, len(GATE_ACCEPT)
    for el in soup.find_all(["a", "button"]):
        label = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip().lower()
        if not label or len(label) > 60:
            continue
        for rank, phrase in enumerate(GATE_ACCEPT):
            if label == phrase or (len(phrase) > 6 and phrase in label):
                if rank >= best_rank:
                    break
                href = el.get("href") or el.get("data-href") or ""
                if not href or href.startswith(("#", "javascript:", "mailto:")):
                    break
                target = urljoin(landed, href)
                p = urlparse(target)
                if not p.scheme.startswith("http"):
                    break
                if p.netloc.replace("www.", "") != root:
                    break          # "leaving this site" is not the way in
                best, best_rank = target, rank
                break
    return best


# Client-rendered sites ship an empty shell and the copy in a JSON blob. Reading
# it is not clever, but it recovers whole sites that would otherwise read as a
# navigation bar, and it costs nothing.
JSON_BLOB_IDS = ("__NEXT_DATA__", "__NUXT_DATA__", "__APOLLO_STATE__")


def _is_prose(t):
    """Sentence-shaped, rather than a class name, a key or a path.

    A regex anchored at the start rejected anything opening with a short word —
    "A once-daily treatment..." failed on its first character. Counting words
    and letters is duller and does not have that class of mistake in it.
    """
    words = t.split()
    if len(words) < 6:
        return False
    letters = sum(c.isalpha() or c.isspace() for c in t)
    return letters / len(t) > 0.75 and " " in t.strip()


def _harvest_strings(node, out, depth=0):
    if depth > 12 or len(out) > 600:
        return
    if isinstance(node, str):
        t = node.strip()
        # Prose, not a class name, a URL, or a chunk of markup.
        if 40 <= len(t) <= 600 and not t.startswith(("http", "/", "{", "<")) \
           and "<" not in t and _is_prose(t):
            out.append(re.sub(r"\s+", " ", t))
    elif isinstance(node, list):
        for v in node:
            _harvest_strings(v, out, depth + 1)
    elif isinstance(node, dict):
        for k, v in node.items():
            if k.lower() in ("css", "style", "styles", "classname", "src", "href", "url", "id"):
                continue
            _harvest_strings(v, out, depth + 1)


def embedded_prose(soup):
    """Sentences carried in the page's JSON rather than its HTML."""
    out = []
    for tag in soup.find_all("script"):
        raw = tag.string or tag.get_text() or ""
        tid = tag.get("id") or ""
        typ = (tag.get("type") or "").lower()
        blob = None
        if tid in JSON_BLOB_IDS or typ in ("application/json", "application/ld+json"):
            blob = raw.strip()
        elif "__NUXT__" in raw or "__INITIAL_STATE__" in raw:
            m = re.search(r"=\s*(\{.*\})\s*;?\s*$", raw.strip(), re.S)
            blob = m.group(1) if m else None
        if not blob:
            continue
        try:
            _harvest_strings(json.loads(blob), out)
        except Exception:
            continue
    # Order preserved, duplicates dropped.
    seen, keep = set(), []
    for t in out:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            keep.append(t)
    return keep[:400]


def visible_text(soup):
    for t in soup(["script", "style", "noscript", "iframe", "svg"]):
        t.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    seen, out = set(), []
    for ln in lines:
        if len(ln) < 2:
            continue
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Finding the photography.
#
# The naive read — every <img src> on the front page — collects almost nothing
# useful on a modern site. Images are lazy-loaded, so `src` holds a placeholder
# and the real file is in srcset or a data- attribute; heroes are often CSS
# backgrounds; and the front page is frequently the least photographic page on
# the site. So: read every page, read every place an image can hide, and judge
# what came back by its dimensions rather than its file size.
# ---------------------------------------------------------------------------

# Words that appear in the address of something that is not art direction.
NOT_PHOTOGRAPHY = re.compile(
    r"(logo|icon|sprite|favicon|pixel|spacer|placeholder|badge|banner-ad|"
    r"arrow|chevron|bullet|divider|pattern|texture|avatar|thumb(nail)?|"
    r"isi\b|pi\b|pdf|share|social|facebook|twitter|linkedin|instagram)", re.I)

MIN_IMAGE_WIDTH = 420      # below this it is furniture, whatever it depicts
MIN_IMAGE_BYTES = 6_000    # a cheap pre-filter; the dimension test does the work
MAX_IMAGES_PER_BRAND = 4


def _from_srcset(value, base):
    """The largest candidate in a srcset, as an absolute address."""
    best, best_w = None, -1
    for part in value.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        w = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            try:
                w = int(bits[1][:-1])
            except ValueError:
                w = 0
        if w >= best_w:
            best, best_w = url, w
    return urljoin(base, best) if best else None


def image_candidates(soup, base):
    """Every address on this page that might be a commissioned photograph,
    roughly in the order a reader would meet them."""
    found = []

    def add(u):
        if not u or u.startswith("data:"):
            return
        u = urljoin(base, u.strip())
        if not u.lower().startswith("http"):
            return
        if not re.search(r"\.(jpe?g|png|webp|avif)(\?|$)", u, re.I):
            return
        if NOT_PHOTOGRAPHY.search(urlparse(u).path):
            return
        found.append(u)

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        add(og["content"])

    for pic in soup.find_all("picture"):
        for src in pic.find_all("source"):
            if src.get("srcset"):
                add(_from_srcset(src["srcset"], base))

    for img in soup.find_all("img"):
        # srcset first: `src` on a lazy-loaded image is usually a placeholder.
        if img.get("srcset"):
            add(_from_srcset(img["srcset"], base))
        for attr in ("data-src", "data-lazy-src", "data-original", "data-srcset", "data-image", "src"):
            v = img.get(attr)
            if not v:
                continue
            add(_from_srcset(v, base) if "srcset" in attr else v)

    # Heroes are frequently a CSS background rather than an element.
    for el in soup.find_all(style=True):
        for m in re.finditer(r"url\(['\"]?([^'\")]+)", el["style"]):
            add(m.group(1))
    for tag in soup.find_all("style"):
        for m in re.finditer(r"url\(['\"]?([^'\")]+)", tag.get_text() or ""):
            add(m.group(1))

    seen, out = set(), []
    for u in found:
        k = u.split("?")[0]
        if k not in seen:
            seen.add(k)
            out.append(u)
    return out


def image_size(data):
    """(width, height) from the file's own header, or None.

    Size in bytes is a poor proxy for whether something is a photograph — a
    well-compressed WebP hero can be smaller than a PNG logo. The dimensions
    are in the first few dozen bytes of every format that matters, so read
    those instead of guessing.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:3] == b"\xff\xd8\xff":                       # JPEG
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return w, h
                seg = int.from_bytes(data[i + 2:i + 4], "big")
                if seg <= 0:
                    return None
                i += 2 + seg
            return None
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            fmt = data[12:16]
            if fmt == b"VP8 ":
                return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                        int.from_bytes(data[28:30], "little") & 0x3FFF)
            if fmt == b"VP8L":
                b0 = int.from_bytes(data[21:25], "little")
                return (b0 & 0x3FFF) + 1, ((b0 >> 14) & 0x3FFF) + 1
            if fmt == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1,
                        int.from_bytes(data[27:30], "little") + 1)
    except Exception:
        return None
    return None


async def crawl_brand(fetcher, brand):
    """Fetch the given URL plus a handful of same-site pages, within whatever
    robots.txt permits. Returns (pages_text, image_candidates, pages_fetched,
    reason, notes) where reason explains an empty result and notes records what
    was in the way.
    """
    start = brand["url"]
    if not start.startswith("http"):
        start = "https://" + start
    root = urlparse(start).netloc.replace("www.", "")
    queue, seen, texts, images = [start], set(), [], []
    notes = {"gates": 0, "json_pages": 0, "thin_pages": 0}

    async def read(url):
        """One page, past whatever is in front of it. Returns (soup, landed) or
        (None, None)."""
        if not await fetcher.allowed(url):
            return None, None, "robots"
        r = await fetcher.get(url)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            return None, None, "not-html"
        soup = BeautifulSoup(r.text, "html.parser")
        landed = str(getattr(r, "url", url)) or url

        # A gate is not a page. Walk through it — once — and take what is
        # behind it instead. Two hops covers region-then-audience, which is the
        # common pharma arrangement.
        for _ in range(2):
            body = visible_text(soup)
            if not looks_like_a_gate(body, soup):
                break
            nxt = gate_exit(soup, landed)
            if not nxt or nxt in seen:
                break
            notes["gates"] += 1
            seen.add(nxt)
            if not await fetcher.allowed(nxt):
                break
            r2 = await fetcher.get(nxt)
            if r2.status_code != 200 or "text/html" not in r2.headers.get("content-type", ""):
                break
            soup = BeautifulSoup(r2.text, "html.parser")
            landed = str(getattr(r2, "url", nxt)) or nxt
        return soup, landed, ""

    while queue and len(texts) < MAX_PAGES_PER_BRAND and len(seen) < MAX_PAGES_PER_BRAND * 3:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            soup, landed, why = await read(url)
        except Exception:
            continue
        if soup is None:
            if url == start and why == "robots":
                return "", [], 0, "robots", notes
            continue

        # Brand URLs redirect constantly — www.trulicity.com lands on
        # trulicity.lilly.com. Everything downstream has to work from where the
        # request actually ended up: relative links resolve against it, the
        # same-site test compares against it, and the quote links the reader
        # follows have to point at the page that really served the wording.
        if url == start:
            host = urlparse(landed).netloc.replace("www.", "")
            if host:
                root = host

        body = visible_text(soup)
        # A shell with the copy in a JSON blob reads as a navigation bar until
        # the blob is opened.
        if len(body) < 1500:
            extra = embedded_prose(soup)
            if extra:
                notes["json_pages"] += 1
                body = body + "\n" + "\n".join(extra)
        if len(body) < 300:
            notes["thin_pages"] += 1

        # Images from every page, not only the first — the front page is often
        # the least photographic one on the site.
        images.extend(image_candidates(soup, landed))

        seen.add(landed)
        texts.append(f"[PAGE {landed}]\n" + body[:12000])

        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(landed, a["href"]).split("#")[0]
            p = urlparse(href)
            if p.netloc.replace("www.", "") != root or not p.scheme.startswith("http"):
                continue
            if re.search(r"\.(pdf|jpg|png|zip|mp4)$", p.path, re.I):
                continue
            score = sum(1 for h in PRIORITY_HINTS if h in href.lower())
            links.append((score, href))
        links.sort(key=lambda x: -x[0])
        for _, href in links:
            if href not in seen and href not in queue:
                queue.append(href)

    corpus = "\n\n".join(texts)[:MAX_CHARS_PER_BRAND]
    # Ordered, de-duplicated, and capped — every candidate costs a request.
    seen_i, cands = set(), []
    for u in images:
        k = u.split("?")[0]
        if k not in seen_i:
            seen_i.add(k)
            cands.append(u)
    # Pages actually read, not addresses tried — a redirect puts two addresses
    # in `seen` for one page, and the reader is told this number.
    return corpus, cands[:40], len(texts), "", notes


# ---------------------------------------------------------------------------
# Tracing a quote back to the page it came from
#
# The crawl stores each brand's pages in one string, separated by [PAGE url]
# markers, and the layer separation returns fragments without saying which page
# each came from. Recovering that is a plain string search — no model call, no
# judgement, and either the wording is on the page or it is not.
#
# The link uses a text fragment (#:~:text=...), which tells the browser to jump
# to that wording and highlight it. Chrome, Edge and Safari honour it; Firefox
# ignores the fragment and simply opens the page. Either way the reader lands
# somewhere useful, which is the point — every number one click from the
# sentence that produced it, now literally.
# ---------------------------------------------------------------------------

PAGE_MARKER = re.compile(r"\[PAGE (\S+?)\]\n")
FRAGMENT_MAX = 110


def split_pages(corpus):
    """[(url, text), ...] from a crawled corpus."""
    parts = PAGE_MARKER.split(corpus)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


# Words that carry no meaning for this comparison. Deliberately short — a long
# stoplist starts throwing away the words that distinguish one claim from
# another ("not", "only", "first").
_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "was", "were", "has", "have", "had", "its", "their", "our", "can", "will",
    "may", "been", "into", "than", "who", "when", "which", "while", "them",
    "they", "she", "him", "her", "his", "about", "also", "some", "such",
}


def _content_words(t):
    return {w for w in re.findall(r"[a-z0-9']+", t.lower()) if len(w) > 2 and w not in _STOP}


def _similarity(a, b):
    """How close two pieces of writing are in meaning, roughly.

    Character similarity alone rates "designed around how people live" and
    "designed around the way people live" lower than it should, because the
    difference is one word in the middle. Blending it with the overlap of
    content words rates the pair on what they are actually saying, which is the
    question being asked. Both halves are cheap and deterministic — no model
    call, so a link never costs anything to place.
    """
    from difflib import SequenceMatcher
    ratio = SequenceMatcher(None, a, b).ratio()
    wa, wb = _content_words(a), _content_words(b)
    overlap = len(wa & wb) / len(wa | wb) if (wa | wb) else 0.0
    return 0.5 * ratio + 0.5 * overlap


def best_line_match(quote, text):
    """The wording on the page closest to a quote that has been tidied.

    The coding step is asked for an exact copy and mostly obliges, but it will
    sometimes smooth punctuation or join two nearby phrases. Requiring a
    character-perfect match drops the link on roughly a third of quotes.

    What comes back is the PAGE'S OWN WORDING, not the quote — which is the
    whole point. A highlight built from the model's paraphrase matches nothing
    and fails silently; one built from the page's characters lands on the
    sentence the reader came to see, even though the quote was tidied.

    Returns (candidate, score, spans_lines). A candidate stitched from more
    than one line crosses a block boundary on the page, which matters when the
    fragment is built.
    """
    q = _norm(quote)
    lines = [ln for ln in text.split("\n") if len(ln.strip()) > 8]
    best, best_score, best_span = None, 0.0, 1
    for i, line in enumerate(lines):
        # Compare against this line, and against it joined with the next one or
        # two — a stitched quote spans consecutive lines on the page.
        for span in (1, 2, 3):
            if i + span > len(lines):
                break
            candidate = " ".join(lines[i:i + span])
            c = _norm(candidate)
            if abs(len(c) - len(q)) > max(60, len(q)):
                continue
            score = _similarity(q, c)
            # A single line is contiguous on the page and highlights reliably,
            # so it wins ties against a stitched one.
            if score > best_score + (0.02 if span > 1 else 0):
                best, best_score, best_span = candidate.strip(), score, span
    return (best, best_score, best_span > 1) if best_score >= 0.62 else (None, best_score, False)


def locate_quote(quote, pages):
    """Find the page carrying this wording, and the exact text as the page has
    it. Returns (url, exact_text) or (None, None).

    Matching is done on normalised whitespace and case, then mapped back to the
    page's own characters — a fragment link only works if it matches the page
    exactly, so the quote as the model returned it cannot be trusted for that.
    """
    q = _norm(quote)
    if len(q) < 12:
        return None, None, None
    # Longest first: a full sentence lands precisely; a short opening still
    # lands on the right paragraph.
    attempts = [q, q[:80], q[:48]]
    for page_url, text in pages:
        flat, index = [], []
        for i, ch in enumerate(text):
            c = " " if ch.isspace() else ch.lower()
            if c == " " and flat and flat[-1] == " ":
                continue
            flat.append(c)
            index.append(i)
        flat = "".join(flat)
        for attempt in attempts:
            if len(attempt) < 12:
                continue
            at = flat.find(attempt)
            if at < 0:
                continue
            start = index[at]
            end = index[min(at + len(attempt), len(index) - 1)] + 1
            # Whitespace is collapsed before the fragment goes into the link.
            # The browser matches against rendered text, where a run of spaces
            # or a line break in the source is one space — a fragment carrying
            # the raw spacing matches nothing and the highlight silently fails.
            exact = re.sub(r"\s+", " ", text[start:end]).strip()
            if len(exact) > FRAGMENT_MAX:
                exact = exact[:FRAGMENT_MAX].rsplit(" ", 1)[0]
            return page_url, exact, "exact"

    # Nothing matched character for character. Fall back to the closest real
    # wording on each page, taking the best across all of them.
    best_url, best_text, best_score, best_split = None, None, 0.0, False
    for page_url, text in pages:
        candidate, score, spans_lines = best_line_match(quote, text)
        if candidate and score > best_score:
            best_url, best_text, best_score, best_split = page_url, candidate, score, spans_lines
    if best_url:
        frag = re.sub(r"\s+", " ", best_text).strip()
        if len(frag) > FRAGMENT_MAX:
            frag = frag[:FRAGMENT_MAX].rsplit(" ", 1)[0]
        # "near", not "exact": this is the page's own wording, so it highlights,
        # but it is the closest sentence rather than the quote character for
        # character, and the reader is told which they are looking at.
        return best_url, frag, "near"
    return None, None, None


def quote_link(url, exact):
    """A link that opens the page with the wording highlighted.

    Chrome, Edge and Safari honour `#:~:text=`; Firefox ignores it and opens the
    page. For anything longer than a few words the `start,end` form is used —
    the browser locates the opening words and the closing words and highlights
    between them, which tolerates a stray character in the middle that would
    make a single long exact string fail. Anything after a redirect loses the
    fragment entirely, which is why the crawler now steps through gates rather
    than linking to them.
    """
    from urllib.parse import quote as urlquote
    enc = lambda t: urlquote(t, safe="")
    words = exact.split()
    if len(words) >= 8:
        head = " ".join(words[:5])
        tail = " ".join(words[-5:])
        return f"{url}#:~:text={enc(head)},{enc(tail)}"
    return f"{url}#:~:text={enc(exact)}"


# A logo, an icon and a tracking pixel are all images, and all worthless here.
# Nothing under this size is commissioned photography.
MIN_IMAGE_BYTES = 24_000
MAX_IMAGES_PER_BRAND = 4


async def fetch_images(http, urls, want=MAX_IMAGES_PER_BRAND):
    """Return [(url, media_type, base64), ...] for the first `want` candidates
    that are actually photographs.

    The test is the image's own width, read from its header, not its file size:
    a well-compressed WebP hero is routinely smaller than a PNG logo, so a byte
    threshold throws away the very thing it is meant to find.
    """
    out, seen, tried = [], set(), 0
    for u in urls:
        if len(out) >= want or tried >= 18:
            break
        base = u.split("?")[0]
        if base in seen:
            continue
        seen.add(base)
        tried += 1
        try:
            r = await http.get(u, headers=BROWSER_HEADERS, follow_redirects=True, timeout=25)
            mt = r.headers.get("content-type", "").split(";")[0].strip()
            if r.status_code != 200 or mt not in ("image/jpeg", "image/png", "image/webp"):
                continue
            if not (MIN_IMAGE_BYTES < len(r.content) < 4_500_000):
                continue
            size = image_size(r.content)
            if size and size[0] < MIN_IMAGE_WIDTH:
                continue
            out.append((u, mt, base64.standard_b64encode(r.content).decode()))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

# A run makes roughly a dozen model calls over several minutes. Any one of them
# can land on a busy moment and come back 529 Overloaded, or 429 rate limited —
# transient, no fault of the request. Losing the whole run to that means losing
# the crawl and every call already paid for, so these are waited out rather than
# surfaced. The waits are long because an overloaded API stays overloaded for
# tens of seconds, not milliseconds.
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504, 529}
RETRY_WAITS = [4, 10, 25, 45, 60]


async def call_model(**kwargs):
    """Always streamed.

    The territory list can legitimately run to tens of thousands of tokens, and
    the SDK refuses an ordinary request whose ceiling implies more than ten
    minutes of generation. Streaming also means a long answer arrives steadily
    rather than sitting on one connection waiting to time out. Nothing here
    consumes the stream incrementally — the whole message is still assembled
    before it is parsed — so callers are unaffected.
    """
    last = None
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            async with get_client().messages.stream(**kwargs) as stream:
                return await stream.get_final_message()
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status not in RETRY_STATUSES or attempt == len(RETRY_WAITS):
                raise
            last = e
            wait = RETRY_WAITS[attempt] * (0.8 + random.random() * 0.4)
            await asyncio.sleep(wait)
    raise last


async def llm_json(prompt, max_tokens=4000, images=None, stage="this step"):
    """One model call returning JSON.

    A truncated answer is treated as a failed run, not repaired. A cut-off
    territory list would parse fine after trimming the last broken entry, and
    the run would carry on and produce numbers — quietly computed over a
    shorter list than the category actually has. Since the percentages are
    sensitive to list length, that is a wrong answer wearing the clothes of a
    right one. Better to stop and say so.
    """
    content = []
    if images:
        for mt, b64 in images:
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}})
    content.append({"type": "text", "text": prompt})
    try:
        msg = await call_model(
            model=MODEL, max_tokens=max_tokens,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in RETRY_STATUSES:
            raise RuntimeError(
                "The model service was busy and stayed busy while the index waited and tried again. "
                "Nothing is wrong with your brands or the sites. Run it again in a few minutes."
            ) from e
        if status in (401, 403):
            raise RuntimeError(
                "The model service refused the key. Check ANTHROPIC_API_KEY, and that the account has credit on it."
            ) from e
        raise
    if msg.stop_reason == "max_tokens":
        raise RuntimeError(
            f"The answer to {stage} was longer than the room allowed, so it arrived cut off "
            "and the run stopped rather than score a partial list. This category needs a "
            "higher limit — raise max_tokens for this stage."
        )
    raw = "".join(b.text for b in msg.content if b.type == "text").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    start = min([i for i in (raw.find("{"), raw.find("[")) if i >= 0], default=0)
    try:
        return json.loads(raw[start:])
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"The answer to {stage} did not come back as usable JSON ({e}). "
            "This is usually a one-off — running the index again normally clears it."
        ) from e


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------

async def stage_layers(brand, corpus):
    prompt = f"""You are separating a pharmaceutical brand website into layers before
strategic scoring. Apply these rules exactly and identically to every brand:
{LAYER_RULES}

Website text for the brand "{brand}":
---
{corpus}
---

Return ONLY JSON:
{{
  "category_guess": "<the therapy category this brand competes in, one line>",
  "mandated_word_estimate": <int, rough word count of layer 1 you stripped>,
  "molecule": ["<layer 2 fragment>", ...],   // 5-20 short verbatim-ish fragments
  "elective": ["<layer 3 fragment>", ...]    // every distinct elective move, verbatim where possible, 8-30 fragments
}}"""
    return await llm_json(prompt, max_tokens=8000, stage="separating the layers")


async def stage_space(category, brand_electives):
    brands_block = "\n\n".join(
        f"### {b}\n" + "\n".join(f"- {x}" for x in frags)
        for b, frags in brand_electives.items()
    )
    prompt = f"""You are building the OPPORTUNITY SPACE for a category-level positioning
audit. Category: {category}.

A concept is a POSITIONING MOVE that was available to every brand in the
category. Wording is irrelevant; the move is the unit. ("Reimagine relief",
"the touch of calm skin" and "safe on skin" can be the same move.)

Build the space from TWO sources:

1. OBSERVED IN CATEGORY (ids C01, C02, ...): every distinct positioning move
   any brand below actually takes in its elective copy. 14-22 concepts.
   Merge wording variants into one move. Molecule facts are NOT moves.

2. EVIDENCED BUT UNOBSERVED — this is NOT optional. A concept list derived
   only from the corpus has a claimant for every position by construction, so
   empty ground can never appear.
   - PATIENT BURDEN (ids X01...): 8-10 positions established from the
     documented burden-of-illness literature for this disease, independent of
     what these brands say. For each, name the kind of evidence (e.g. "sleep
     disturbance is consistently reported as the most burdensome symptom in
     the burden-of-illness literature").
   - CLINICAL BARRIERS (ids H01...): 8-10 positions from the treatment-barrier,
     adherence and guideline literature on the prescriber side. Congress
     symposium Q&A is the ideal source for these — the objections clinicians
     raise that brands fail to answer.
   Some X/H positions may in fact be taken by a brand below; that is fine —
   include them anyway with their literature provenance.

Availability tiering — every position, with reasoning shown to the user:
{TIER_RULES}

Elective-layer copy per brand:
{brands_block}

LENGTH — this is a list, not an essay, and the whole answer has to arrive in
one piece. Never more than 42 concepts in total. Keep every field short:
label at most 12 words, description one sentence of at most 25 words, source at
most 25 words, tier_reasoning at most 30 words. Do not restate the label inside
the description. Do not repeat a concept in different words.

Return ONLY JSON — a list:
[{{"id": "C01", "label": "<the move, one line>",
   "description": "<plain English, one sentence>",
   "source": "<for C: 'Observed in category.' For X/H: the specific literature basis>",
   "tier": "open|frame_only|constrained|closed",
   "tier_reasoning": "<1-2 sentences, specific to this category>"}}, ...]"""
    try:
        return await llm_json(prompt, max_tokens=32000, stage="building the territory list")
    except RuntimeError as e:
        # A category the prompt did not anticipate can make the model discursive
        # enough to run out of room. Ask once more, harder, before giving up on
        # a run that has already paid for the crawl and the layer separation.
        if "cut off" not in str(e):
            raise
        tighter = prompt + """

YOUR PREVIOUS ANSWER WAS TOO LONG AND ARRIVED CUT OFF. Produce the same
structure with at most 30 concepts, and keep every description to a single
short clause. Completeness of the JSON matters more than richness of the
wording."""
        return await llm_json(tighter, max_tokens=32000, stage="building the territory list")


async def stage_code(brand, frags, positions):
    plist = "\n".join(f'{p["id"]}: {p["label"]} — {p["description"]}' for p in positions)
    frag_block = "\n".join(f"- {x}" for x in frags)
    prompt = f"""Code one brand's elective-layer copy against a fixed list of positions.

A position is TAKEN only if the copy clearly makes that move. Do not infer from
molecule facts. If in doubt, do not code it — under-coding is the conservative
direction.

THE EVIDENCE STRING IS A COPY, NOT A SUMMARY. Reproduce one continuous run of
wording exactly as it appears below, character for character, including its
capitalisation and punctuation. Do not tidy it, do not shorten it to its sense,
do not join two phrases from different places, and never describe what the site
does instead of quoting it. Every quote is looked up on the brand's own page
afterwards so the reader can go and see it in place, and a quote that has been
smoothed cannot be found again. If no single continuous run of wording makes
the move on its own, the position is not taken — leave it out.

Positions:
{plist}

Elective copy for "{brand}":
{frag_block}

Return ONLY JSON: {{"<position id>": "<verbatim evidence from the copy>", ...}}
Only include positions that are clearly taken. An empty object is a valid answer."""
    return await llm_json(prompt, max_tokens=8000, stage="scoring a brand against the territories")


async def stage_visual_read(brand, images):
    """Read one brand's commissioned imagery into art-direction observations.

    This is the visual counterpart of stage_layers: it produces the elective
    material that the visual opportunity space is then built from. It does not
    score anything and does not see the territory list, because the list does
    not exist yet.
    """
    n = len(images)
    prompt = f"""You are reading the art direction on one pharmaceutical brand's website:
"{brand}". {n} image{'s' if n != 1 else ''} follow{'' if n != 1 else 's'}, numbered from 1 in the order shown.

COMMISSIONED IMAGERY ONLY. Clinical photography of the disease, mechanism-of-action
diagrams, pack shots, screenshots, charts and logos were determined by the product
rather than chosen by an art director. Ignore them entirely. If none of the images
is commissioned photography or illustration, return {{"excluded": true, "reason": "<why>"}}.

For each commissioned image, write down the decisions somebody made. One
observation per decision, each a short plain-English sentence naming what is
actually in the picture — who is in frame and roughly how old they read, what
they are doing, where they are, the light and palette, what is touching what,
whether the disease is visible, whether a device or a clinician appears, the
register the picture is reaching for. Describe only what you can see. Do not
interpret the brand's strategy and do not use marketing adjectives.

Return ONLY JSON:
{{"elements": [{{"image": <1-based number of the image>, "note": "<one observation>"}}, ...],
  "summary": "<2-3 sentences on this brand's art direction overall>"}}

Between 6 and 14 observations in total across all the images."""
    return await llm_json(prompt, max_tokens=3000, images=[(mt, b64) for _u, mt, b64 in images],
                          stage="reading the imagery")


async def stage_visual_space(category, brand_visuals):
    """Build the visual opportunity space for this category, on the fly.

    Same shape as stage_space and for the same reason: an inventory derived only
    from what the brands show has a user for every territory by construction, so
    unclaimed visual territory can never appear. The literature-established half
    is what makes "nobody depicts this" a finding rather than an absence.
    """
    block = "\n\n".join(
        f"### {b}\n" + "\n".join(f"- {x}" for x in obs)
        for b, obs in brand_visuals.items()
    )
    prompt = f"""You are building the VISUAL OPPORTUNITY SPACE for a category-level
positioning audit. Category: {category}.

A VISUAL TERRITORY is an art direction decision that was available to every
brand in the category — a casting decision, a setting, a moment, a treatment, a
graphic register. The decision is the unit, not the execution. ("A woman at a
kitchen window in morning light" and "a man in a sunlit hallway" are the same
territory: a single adult alone in domestic light.)

Build the space from TWO sources:

1. OBSERVED IN CATEGORY (ids V01, V02, ...): every distinct art direction
   decision any brand below actually makes. 8-14 territories. Merge executions
   of the same decision into one territory.

2. EVIDENCED BUT UNDEPICTED — this is NOT optional, and it is the point of the
   exercise. An inventory built only from these sites has a user for every
   territory by construction.
   - PATIENT BURDEN (ids X01...): 5-8 visual territories established from the
     documented burden-of-illness and lived-experience literature for this
     disease — the people, moments, settings and body sites patients describe
     as mattering — identified independently of what these brands show. For
     each, name the kind of evidence.
   - REPRESENTATION AND CLINICAL BARRIERS (ids H01...): 4-7 visual territories
     established from the literature on who the disease actually affects and
     where it is missed or under-recognised — age, skin tone, sex, body site,
     comorbidity, setting of care. Again, name the evidence.
   Some X/H territories may in fact be depicted by a brand below; include them
   anyway, with their literature provenance.

Availability tiering — every territory, with reasoning written for a brand lead
in plain commercial English:
{VISUAL_TIER_RULES}

VOCABULARY. The unit is a "visual territory". Avoid spatial metaphor beyond the
word territory itself — never "ground", "space", "white space", "own", "stand
on". Never "disruption", "transformation" or "innovation". Write about casting,
setting, art direction, treatment, register.

Art direction observed, by brand:
{block}

LENGTH — a list, not an essay, and the whole answer has to arrive in one piece.
Never more than 26 territories in total. Label at most 10 words, description one
sentence of at most 22 words, source at most 22 words, tier_reasoning at most 28
words. Do not restate the label inside the description.

Return ONLY JSON — a list:
[{{"id": "V01", "label": "<the decision, one line>",
   "description": "<plain English, one sentence>",
   "source": "<for V: 'Observed in category.' For X/H: the specific literature basis>",
   "tier": "open|frame_only|constrained|closed",
   "tier_reasoning": "<1-2 sentences, specific to this category>"}}, ...]"""
    return await llm_json(prompt, max_tokens=16000, stage="building the visual territory list")


async def stage_visual_code(brand, observations, positions):
    """Code one brand's art direction against the visual territory list.

    Deliberately reads the written observations rather than the images again:
    the same material the list was built from, so a brand cannot be coded on
    something no reader can check, and the run does not pay for every image a
    second time.
    """
    plist = "\n".join(f'{p["id"]}: {p["label"]} — {p["description"]}' for p in positions)
    obs = "\n".join(f"- [image {o.get('image', 1)}] {o.get('note', '')}" for o in observations)
    prompt = f"""Code one brand's art direction against a fixed list of visual territories.

A territory is USED only if the observations below clearly show that decision
having been made. Do not infer it from the category, from the product, or from
what a brand like this usually does. If in doubt, leave it out — under-coding is
the conservative direction.

THE EVIDENCE IS A DESCRIPTION OF WHAT IS IN THE PICTURE, taken from the
observations below and not invented. Reproduce the observation that shows the
decision, and say which image it came from. Coding a picture involves more
judgement than quoting a sentence does, which is exactly why the reader is shown
the image and the observation together and can disagree with the call.

Visual territories:
{plist}

Art direction observed for "{brand}":
{obs}

Return ONLY JSON: {{"<territory id>": {{"evidence": "<the observation>", "image": <image number>}}, ...}}
Only include territories clearly used. An empty object is a valid answer."""
    return await llm_json(prompt, max_tokens=6000, stage="scoring a brand's art direction")


async def stage_find(brand, category_hint):
    """Propose the category, the competing brands, and candidate addresses.

    Everything here is a proposal. A model asked for a URL will produce
    something plausible whether or not it exists, so nothing this returns is
    shown to anyone until the server has fetched it and seen a real page come
    back. That is why the prompt asks for several guesses per brand rather than
    one confident answer — breadth is useful when the verification step is
    doing the deciding.
    """
    hint = f"\nThe user says the category is: {category_hint}" if category_hint else ""
    prompt = f"""A brand manager has named one pharmaceutical brand: "{brand}".{hint}

Identify the category it competes in, and the brands it competes against.

Rules:
- The category is one line, as a commercial team would say it: the indication,
  the population and the market. For example "type 2 diabetes, adults, US".
- List 3 to 6 competitors: brands a marketing team at "{brand}" would name in
  the room. Same indication and same market. Do not list the same company's
  other products unless they genuinely compete for the same prescription.
- Include the named brand itself as the first entry.
- For each brand give candidate website addresses: the direct-to-patient site
  and the healthcare professional site where you believe both exist. Guess the
  conventional patterns as well as any address you recall — every address is
  checked before it is shown to anyone, so a wrong guess costs nothing and a
  missing one costs a brand. Give 2 to 4 candidates per brand.
- Only real, marketed, branded products. No pipeline compounds, no generics.

Return ONLY JSON:
{{"category": "<one line>",
  "brands": [{{"name": "<brand>", "company": "<company>",
               "candidates": ["https://...", "https://..."]}}]}}"""
    return await llm_json(prompt, max_tokens=3000, stage="finding the category and competitors")


async def stage_shortlist(prof, peers, category):
    """Narrow a real competitive set to the brands a marketing team would name.

    The list going in is from openFDA, so nothing here is being recalled — the
    model is asked which of these actually compete for the same prescription,
    which is judgement it is good at. It returns names, and anything it returns
    that was not on the list is thrown away by the caller. It cannot add.
    """
    listing = "\n".join(
        f'- {p["brand"]} ({p.get("generic", "")}, {p.get("company", "")})' for p in peers)
    prompt = f"""A brand manager at "{prof['brand']}" ({prof.get('generic', '')}) is naming
the competitors they benchmark against. Category: {category or 'not stated'}.

Every brand below shares {prof['brand']}'s established pharmacologic class, so
all of them are real and currently marketed. Choose the 4 to 6 that a marketing
team at {prof['brand']} would actually name in the room.

Prefer brands that:
- treat the same population for the same indication, not a niche sub-use
- are actively promoted rather than legacy products past their patent
- would appear on a share-of-voice chart in that category

Exclude:
- the same company's other presentations of the same molecule
- products whose only overlap is the class, in a different disease

Brands in the class:
{listing}

Return ONLY JSON: {{"brands": ["<name exactly as written above>", ...]}}"""
    out = await llm_json(prompt, max_tokens=1200, stage="choosing the competitive set")
    return [str(b) for b in (out.get("brands") or []) if b]


async def stage_findings(category, metrics, positions, brands, cross_check,
                         conv=None, visual_positions=None):
    pos_lines = "\n".join(
        f'{p["id"]} [{p["tier"]}] ({p["n"]} of {len(brands)}: {", ".join(p["claimers"]) or "nobody"}) {p["label"]}'
        for p in positions
    )
    visual_positions = visual_positions or []
    vis_lines = "\n".join(
        f'visual:{p["id"]} [{p["tier"]}] ({p["n"]} of {len(brands)}: {", ".join(p["claimers"]) or "nobody"}) {p["label"]}'
        for p in visual_positions
    ) or "imagery could not be read on enough brands this run"
    conv_block = json.dumps(conv) if conv else "not computed"
    cc = json.dumps(cross_check) if cross_check else "not captured"
    prompt = f"""You are writing the result screen of a strategic audit called the
Sameness Index. Category: {category}. Brands: {", ".join(brands)} — the first
is the user's own brand.

Voice: a smart, experienced strategist talking to an equal. Plain English,
short declarative sentences, no hype, sentence case.

VOCABULARY — this matters. The reader is a brand or marketing lead. Use the
standard vocabulary of commercial communications: messaging, positioning,
claims, audience, message hierarchy, differentiation, disease education,
substantiation, art direction. Say exactly what you mean.

The unit of analysis is a MESSAGING TERRITORY. Call it that, or "territory".
Do not call it a "position", a "concept", a "move" or a "slot". "Messaging
territory" is the only spatial term permitted; do not extend the metaphor into
"ground", "space", "white space", "land", "occupy" or "stand on".

Do NOT use spatial or territorial metaphor. Specifically, do not write that a
brand "stands on", "occupies", "holds" or "owns ground", do not refer to
"space", "ground", "territory" or "white space" as a stand-in for positioning,
and do not write "daylight". Say "uses this position", "makes this claim",
"no brand uses this position", "positions nobody has taken".

Do not write pithy or aphoristic lines. Every sentence should be explicit
enough that a reader who has never seen this tool understands it without
inference. Never use the words "disruption", "transformation" or "innovation".

There are two inventories, built the same way and scored the same way: MESSAGING
TERRITORIES and VISUAL TERRITORIES. A visual territory is an art direction
decision — casting, setting, moment, treatment. Write about it in art direction
language, and say what is actually in the pictures.

Convergence (computed, do not recompute): {conv_block}
The convergence score is, for each brand, the share of its territories that at
least one rival also uses, averaged across the brands. Higher means the brands
sound and look more alike.

Metrics (computed, do not recompute): {json.dumps(metrics)}
Messaging territories:
{pos_lines}
Visual territories:
{vis_lines}
Verbal/visual cross-check: {cc}

Return ONLY JSON:
{{
 "headline": "<LEAD WITH THE SCORE AND THE BAND, then the counts, then what
   nobody uses. Keep it plain and keep the arithmetic adding up. Three or four
   short sentences, no subordinate clauses, no phrase the reader has to decode.
   Write 'explore' rather than 'take' or 'own' — some territories will not suit
   a given brand and the tool does not know which. Follow this pattern exactly,
   substituting the real numbers: 'This category scores 64 for convergence —
   converged. Of 41 messaging territories, 7 are used by more than one brand, 15
   by only one, and 19 by neither. 18 of those unused territories come from
   published evidence on what patients and clinicians say is missing, rather
   than from anything these brands publish. The art direction scores 78, with 5
   of 14 visual territories depicted by nobody.' With two brands, write 'both
   brands' instead of 'more than one brand'. Leave out the imagery sentence if
   the imagery was not read.>",
 "findings": [  // 3 to 5, each one sentence or two, each with evidence refs.
                // At least one should be about the art direction where visual
                // territories were read.
   {{"text": "<the finding>", "refs": ["<messaging territory id>" or "visual:<visual territory id>", ...]}}
 ],
 "brand_comments": {{"<brand>": "<one sentence on how its messaging and its art direction compare>", ...}}
}}"""
    return await llm_json(prompt, max_tokens=6000, stage="writing the findings")


# ---------------------------------------------------------------------------
# Metrics — ported from score.py, unchanged logic
# ---------------------------------------------------------------------------

def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else 0.0


def compute(positions, coding, brands):
    space = [p["id"] for p in positions]
    c = Counter()
    for b in brands:
        c.update(coding[b].keys())

    occupied = [k for k in space if c[k] > 0]
    contested = [k for k in occupied if c[k] > 1]
    crowded = [k for k in occupied if c[k] > len(brands) / 2]
    sole = [k for k in occupied if c[k] == 1]
    empty = [k for k in space if c[k] == 0]
    tiers = {p["id"]: p["tier"] for p in positions}
    open_empty = [k for k in empty if tiers.get(k) == "open"]

    pw = {f"{a} / {b}": round(jaccard(coding[a], coding[b]), 3)
          for a, b in combinations(brands, 2)}

    brand_position = {}
    for b in brands:
        own = set(coding[b])
        unique = {x for x in own if c[x] == 1}
        crowded_set = set(crowded)
        brand_position[b] = {
            "claimed": len(own),
            "space_used": round(len(own) / len(space), 3) if space else 0,
            "uniquely_owned": sorted(unique),
            "n_unique": len(unique),
            "ownership": round(len(unique) / len(own), 3) if own else 0.0,
            "crowding": round(len(own & crowded_set) / len(crowded_set), 3) if crowded_set else 0.0,
        }

    metrics = {
        "space_size": len(space),
        "occupied": len(occupied),
        "empty": len(empty),
        "occupancy_rate": round(len(occupied) / len(space), 3) if space else 0,
        "crowded": len(crowded),
        "contested": len(contested),
        "sole_held": len(sole),
        "crowding_rate": round(len(contested) / len(occupied), 3) if occupied else 0.0,
        "open_empty": len(open_empty),
        "empty_ids": empty,
        "open_empty_ids": open_empty,
        "crowded_ids": crowded,
        "mean_pairwise": round(sum(pw.values()) / len(pw), 3) if pw else 0.0,
        "pairwise": pw,
        "empty_by_tier": dict(Counter(tiers[k] for k in empty)),
    }
    return metrics, brand_position, c


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def ev(obj):
    """One event from the pipeline. Progress lines are narration, and are
    written down as they happen; an error or a result ends the run."""
    return obj


async def pipeline(brands_in, category_given=""):
    brands = [b["name"].strip() for b in brands_in]
    yourn = brands[0]
    category_given = (category_given or "").strip()

    async with httpx.AsyncClient() as http:
      fetcher = Fetcher(http)
      try:

        # 1 — read the sites
        #
        # A site that cannot be read is a fact about that site, not a reason to
        # throw away the whole run. Large pharma sites sit behind bot protection
        # that inspects the TLS handshake, and no combination of headers gets
        # past it. So an unreadable competitor is dropped, named on the page,
        # and the rest of the category is still analysed. Two exceptions: the
        # user's own brand is the frame for the entire report, and fewer than
        # two brands is not a comparison.
        corpora, image_cands, unreadable = {}, {}, []
        for b in brands_in:
            host = urlparse(b["url"] if b["url"].startswith("http") else "https://" + b["url"]).netloc or b["url"]
            yield ev({"type": "progress", "text": f"Reading {host} — the public website, as a patient or prescriber would find it."})
            corpus, images, n_pages, why, notes = await crawl_brand(fetcher, b)
            if why == "robots":
                # Not a failure. The site has asked crawlers not to read it,
                # and that is the end of the matter — there is no version of
                # this tool that overrides it.
                if b["name"] == yourn:
                    yield ev({"type": "error", "text": (
                        f"{b['name']}'s site asks automated readers not to read it, in its robots.txt. "
                        "The index honours that, and the report is built around your own brand, so there is "
                        "nothing to run. If this is your brand and you want it analysed, your web team can "
                        "permit it."
                    )})
                    return
                unreadable.append({"name": b["name"], "url": b["url"], "reason": "asked not to be read"})
                yield ev({"type": "progress", "text": (
                    f"{b['name']}'s site asks automated readers not to read it, in its robots.txt. "
                    "Leaving it out; the report will say so."
                )})
                continue

            if len(corpus) < 400:
                if b["name"] == yourn:
                    yield ev({"type": "error", "text": (
                        f"Could not read enough of {b['name']}'s site ({b['url']}). The report is built around your own "
                        "brand, so there is nothing to compare against without it. The site may block automated readers "
                        "or render entirely in JavaScript. Try the patient site if you entered the HCP one, or the other "
                        "way round."
                    )})
                    return
                unreadable.append({"name": b["name"], "url": b["url"]})
                yield ev({"type": "progress", "text": (
                    f"{b['name']}'s site could not be read — it blocks automated readers or renders entirely in "
                    "JavaScript. Continuing without it; the report will say so."
                )})
                continue
            corpora[b["name"]] = corpus
            image_cands[b["name"]] = images
            extra = []
            if notes.get("gates"):
                extra.append(f"{notes['gates']} gate{'s' if notes['gates'] != 1 else ''} stepped through")
            if notes.get("json_pages"):
                extra.append(f"{notes['json_pages']} page{'s' if notes['json_pages'] != 1 else ''} whose copy is built in the browser, read from the page data")
            yield ev({"type": "progress", "text": (
                f"{b['name']}: {n_pages} page{'s' if n_pages != 1 else ''} read"
                + (" — " + ", ".join(extra) if extra else "")
                + f". {len(images)} image{'s' if len(images) != 1 else ''} to look at."
            )})

        brands = [b for b in brands if b in corpora]
        brands_in = [b for b in brands_in if b["name"] in corpora]
        if len(brands) < 2:
            yield ev({"type": "error", "text": (
                "Only one brand's site could be read, and one brand is not a comparison. "
                + ("Could not read: " + ", ".join(u["name"] for u in unreadable) + ". " if unreadable else "")
                + "Try different addresses, or a category whose sites are less heavily protected."
            )})
            return

        # 2 — strip the mandatories, separate the molecule layer
        yield ev({"type": "progress", "text": "Removing regulatory content — safety information, indication statements, prescribing information, disclaimers. None of it was a marketing decision, so none of it is scored."})
        electives, molecules, category_votes = {}, {}, []
        for b in brands:
            yield ev({"type": "progress", "text": f"Separating label-determined content from marketing decisions: {b}."})
            layers = await stage_layers(b, corpora[b])
            electives[b] = layers.get("elective", [])
            molecules[b] = layers.get("molecule", [])
            if layers.get("category_guess"):
                category_votes.append(layers["category_guess"])
            stripped = layers.get("mandated_word_estimate")
            if stripped:
                yield ev({"type": "progress", "text": f"{b}: roughly {stripped:,} words of regulatory text removed; {len(electives[b])} messaging decisions retained for scoring."})

        # A page can be fetched, be full of text, and still contain no brand
        # messaging — a region selector, a corporate holding page, an
        # interstitial. The crawl gate only asks whether there were words.
        #
        # Left alone this is the worst failure the tool has, because it does not
        # look like one. A brand that contributed nothing shares nothing, and
        # sharing nothing scores as perfect distinctiveness, so a half-read
        # category publishes a confident low number and a headline saying the
        # brands are saying different things. A brand nobody could read must
        # leave the figures, exactly as an unreachable site does.
        thin = [b for b in brands if len(electives.get(b, [])) < MIN_ELECTIVES]
        for b in thin:
            if b == yourn:
                yield ev({"type": "error", "text": (
                    f"{b}'s site was reached, but no brand messaging could be separated out of it — the page "
                    "read as a region selector, a corporate page or an interstitial rather than the brand's own "
                    "site. The report is built around your own brand, so there is nothing to run. Try the "
                    "address of the brand site itself, or the patient site if you entered the HCP one."
                )})
                return
            unreadable.append({
                "name": b,
                "url": next((x["url"] for x in brands_in if x["name"] == b), ""),
                "reason": "no brand messaging on the page",
                "note": (f"{b}'s site was reached, but no brand messaging could be separated out of it — what "
                         "came back read as a region selector, a corporate page or an interstitial rather than "
                         "the brand's own site. It is left out of every figure here."),
            })
            yield ev({"type": "progress", "text": (
                f"{b}: the page was reached but carries no brand messaging — it reads as a corporate or "
                "interstitial page rather than the brand's site. Leaving it out; the report will say so."
            )})
        if thin:
            brands = [b for b in brands if b not in thin]
            brands_in = [x for x in brands_in if x["name"] in brands]
            for b in thin:
                electives.pop(b, None)
                molecules.pop(b, None)
                corpora.pop(b, None)
                image_cands.pop(b, None)
            if len(brands) < 2:
                yield ev({"type": "error", "text": (
                    "Only one brand's site carried any messaging to analyse, and one brand is not a comparison. "
                    + "Reached but empty: " + ", ".join(u["name"] for u in unreadable if u.get("reason") == "no brand messaging on the page") + ". "
                    + "Those addresses are probably corporate or regional pages rather than the brand sites. "
                      "Try the brand's own address and run it again."
                )})
                return
        # The whole territory list is built from this one phrase, so it decides
        # what every brand is measured against. Taking the first brand's guess
        # and discarding the rest silently is how a set spanning two
        # presentations or two indications gets scored against a list that only
        # describes one of them. If the user said what the category is, that
        # wins; otherwise say out loud what was settled on, and say so when the
        # brands did not agree.
        if category_given:
            category = category_given
            yield ev({"type": "progress", "text": f"Reading this as one category: {category}."})
        else:
            category = category_votes[0] if category_votes else "this category"
            distinct = list(dict.fromkeys(v.strip() for v in category_votes if v.strip()))
            yield ev({"type": "progress", "text": f"Reading this as one category: {category}."})
            if len(distinct) > 1:
                yield ev({"type": "progress", "text": (
                    "The brands do not describe the category identically — also read as: "
                    + "; ".join(distinct[1:])
                    + ". Every brand is scored against the first. If that is the wrong frame for this set, "
                      "set the category yourself on the input screen and run it again."
                )})

        # 3 — build the opportunity space
        yield ev({"type": "progress", "text": "Building the list of positions available to this category — including positions nobody uses, drawn from the published literature on patient burden and prescribing barriers rather than from the brands themselves."})
        raw_space = await stage_space(category, electives)
        positions = []
        for p in raw_space:
            pid = str(p.get("id", "")).strip()
            if not pid or pid[0] not in "CXH":
                continue
            positions.append({
                "id": pid,
                "label": p.get("label", "").strip(),
                "description": p.get("description", "").strip(),
                "provenance": PROVENANCE_LABELS.get(pid[0], "observed in category"),
                "source": p.get("source", ""),
                "tier": p.get("tier", "open"),
                "tier_reasoning": p.get("tier_reasoning", ""),
            })
        n_exo = sum(1 for p in positions if p["id"][0] in "XH")
        yield ev({"type": "progress", "text": f"{len(positions)} positions available — {len(positions) - n_exo} observed in the category's current messaging, {n_exo} established from published literature independently of what these brands say."})

        # 4 — code every brand against every position
        coding = {}
        for b in brands:
            yield ev({"type": "progress", "text": f"Scoring {b} against all {len(positions)} positions, using its messaging only."})
            codes = await stage_code(b, electives[b], positions)
            valid = {p["id"] for p in positions}
            coding[b] = {k: str(v) for k, v in codes.items() if k in valid and v}

        # Where each quote lives, so the reader can go and see it in place.
        pages_by_brand = {b: split_pages(corpora[b]) for b in brands}
        highlighted = near = page_only = lost = 0

        for p in positions:
            p["claimers"] = [b for b in brands if p["id"] in coding[b]]
            p["n"] = len(p["claimers"])
            p["receipts"] = {b: coding[b][p["id"]] for b in p["claimers"]}
            links, match = {}, {}
            for b in p["claimers"]:
                url, frag, how = locate_quote(coding[b][p["id"]], pages_by_brand[b])
                if url and frag:
                    links[b] = quote_link(url, frag)
                    match[b] = how          # "exact" or "near"
                    if how == "exact":
                        highlighted += 1
                    else:
                        near += 1
                elif url:
                    links[b] = url
                    match[b] = "page"
                    page_only += 1
                else:
                    lost += 1
            if links:
                p["receipt_links"] = links
                p["receipt_match"] = match

        total = highlighted + near + page_only + lost
        if total:
            bits = [f"{highlighted} of {total} quotes link to the exact wording, highlighted on the page"]
            if near:
                bits.append(f"{near} highlight the closest sentence on the page, where the quote had been tidied")
            if page_only:
                bits.append(f"{page_only} open the right page without a highlight")
            if lost:
                bits.append(f"{lost} could not be found again")
            yield ev({"type": "progress", "text": "; ".join(bits) + "."})

        # 5 — the visual layer
        #
        # Built the same way the messaging layer is: read the material, build
        # the inventory for this category from what is observed plus what the
        # literature evidences, then code every brand against the whole list.
        # An inventory fixed in advance could not say which visual territory
        # this category leaves empty, and that is the finding worth having.
        yield ev({"type": "progress", "text": "Reading the art direction — commissioned photography only. Clinical images, mechanism diagrams and pack shots are excluded, because they were not art direction decisions."})
        visual_obs, visual_summaries, image_urls = {}, {}, {}
        for b in brands:
            imgs = await fetch_images(http, image_cands.get(b, []))
            if not imgs:
                continue
            image_urls[b] = [u for u, _mt, _b64 in imgs]
            try:
                v = await stage_visual_read(b, imgs)
            except Exception:
                continue
            if v.get("excluded"):
                continue
            obs = [o for o in (v.get("elements") or []) if o.get("note")]
            if not obs:
                continue
            visual_obs[b] = obs
            visual_summaries[b] = v.get("summary", "")
            yield ev({"type": "progress", "text": f"{b}: {len(imgs)} commissioned image{'s' if len(imgs) != 1 else ''} read, {len(obs)} art direction decisions noted."})

        # What was seen, brand by brand, kept regardless of whether there is
        # enough of it to compare. Reading a brand's art direction and then
        # discarding it because no rival could be read wastes the reading and
        # tells the reader nothing — describing one brand's photography is
        # worth having even when scoring it against nobody is not.
        visual_read = []
        for b, obs in visual_obs.items():
            urls = image_urls.get(b, [])
            visual_read.append({
                "brand": b,
                "summary": visual_summaries.get(b, ""),
                "images": urls,
                "observations": [
                    {"note": o.get("note", ""),
                     "image": (urls[o["image"] - 1]
                               if isinstance(o.get("image"), int) and 1 <= o["image"] <= len(urls)
                               else None)}
                    for o in obs if o.get("note")
                ],
            })

        visual_positions, visual_coding = [], {}
        if len(visual_obs) == 1:
            only = next(iter(visual_obs))
            yield ev({"type": "progress", "text": (
                f"Only {only}'s art direction could be read, and one brand is not a comparison — so the "
                "imagery is described rather than scored, and it is left out of the convergence figure."
            )})
        if len(visual_obs) >= 2:
            yield ev({"type": "progress", "text": "Building the list of visual territories available to this category — including territories nobody depicts, drawn from the literature on who this disease affects and what patients describe, rather than from the brands themselves."})
            try:
                raw_visual = await stage_visual_space(
                    category, {b: [o["note"] for o in obs] for b, obs in visual_obs.items()})
            except Exception:
                raw_visual = []
            for p in raw_visual or []:
                pid = str(p.get("id", "")).strip()
                if not pid or pid[0] not in "VXH":
                    continue
                # The visual list is asked for X and H ids so the model applies
                # the same provenance discipline it does to the messaging list,
                # but those ids already exist in the messaging inventory. Every
                # visual territory is therefore namespaced with a leading V, so
                # an id identifies one territory on the whole page and a finding
                # can never link to the wrong one.
                prov = ("observed in category" if pid[0] == "V"
                        else PROVENANCE_LABELS.get(pid[0], "observed in category"))
                if pid[0] != "V":
                    pid = "V" + pid
                visual_positions.append({
                    "id": pid,
                    "label": p.get("label", "").strip(),
                    "description": p.get("description", "").strip(),
                    "provenance": prov,
                    "source": p.get("source", ""),
                    "tier": p.get("tier", "open"),
                    "tier_reasoning": p.get("tier_reasoning", ""),
                    "visual": True,
                })

        if visual_positions:
            valid_v = {p["id"] for p in visual_positions}
            for b in visual_obs:
                yield ev({"type": "progress", "text": f"Scoring {b}'s art direction against all {len(visual_positions)} visual territories."})
                try:
                    codes = await stage_visual_code(b, visual_obs[b], visual_positions)
                except Exception:
                    codes = {}
                clean = {}
                for k, v in (codes or {}).items():
                    if k not in valid_v:
                        continue
                    if isinstance(v, dict) and v.get("evidence"):
                        clean[k] = {"evidence": str(v["evidence"]),
                                    "image": int(v.get("image") or 1)}
                    elif isinstance(v, str) and v.strip():
                        clean[k] = {"evidence": v.strip(), "image": 1}
                visual_coding[b] = clean

            for p in visual_positions:
                p["claimers"] = [b for b in brands if p["id"] in visual_coding.get(b, {})]
                p["n"] = len(p["claimers"])
                p["receipts"] = {b: visual_coding[b][p["id"]]["evidence"] for b in p["claimers"]}
                links = {}
                for b in p["claimers"]:
                    i = visual_coding[b][p["id"]]["image"]
                    urls = image_urls.get(b, [])
                    if 1 <= i <= len(urls):
                        links[b] = urls[i - 1]
                if links:
                    p["receipt_links"] = links
            visual_positions.sort(key=lambda p: (-p["n"], p["id"]))

        # Brands whose imagery could not be read are outside the imagery figures
        # entirely rather than counted as depicting nothing.
        visual_brands = [b for b in brands if b in visual_coding]

        # 6 — the arithmetic
        yield ev({"type": "progress", "text": "Calculating — how much of the available positioning is in use, how much of it is shared, and which positions each brand holds alone."})
        metrics, brand_position, counts = compute(positions, coding, brands)

        # Distance from the category centre — majority behaviour on each
        # territory anyone uses. See generate_worked_example.py for the rationale.
        occupied_ids = [p["id"] for p in positions if p["n"] > 0]
        centre = []
        for b in brands:
            if not occupied_ids:
                continue
            departures = [
                pid for pid in occupied_ids
                if (pid in coding[b]) != (counts[pid] > len(brands) / 2)
            ]
            centre.append({
                "brand": b,
                "distance": round(len(departures) / len(occupied_ids), 3),
                "departures": len(departures),
                "of": len(occupied_ids),
                "departure_ids": departures,
            })
        centre.sort(key=lambda r: -r["distance"])

        # The headline. Messaging and imagery are scored by the same
        # calculation over their own inventories, and the category score is the
        # mean of the two. Where the imagery could not be read, the score is the
        # messaging score alone and the page says so rather than quietly
        # averaging a number that does not exist.
        conv_msg = convergence(positions, brands)
        if len(conv_msg["per"]) < 2:
            # Everything upstream passed and the coding still came back empty for
            # all but one brand. Publishing a score off one brand would be worse
            # than saying so.
            yield ev({"type": "error", "text": (
                "Only one brand ended up with any messaging territories coded against it, and one brand is not "
                "a comparison. This usually means an address points at a corporate or regional page rather than "
                "the brand's own site. Check the addresses and run it again."
            )})
            return
        conv_img = convergence(visual_positions, visual_brands) if visual_positions and len(visual_brands) >= 2 else None
        overall = r0((conv_msg["mean"] + conv_img["mean"]) / 2) if conv_img else conv_msg["mean"]
        conv = {
            "overall": overall,
            "band": band_for(overall),
            "messaging": conv_msg,
            "imagery": conv_img,
            "imagery_brands": visual_brands,
            "imagery_absent": None if conv_img else (
                "No commissioned photography could be retrieved from these sites — the images on the pages read "
                "were clinical, diagrams, pack shots or too small to be art direction."
                if not visual_obs else
                f"Only {next(iter(visual_obs))}'s art direction could be read, so there is nothing to compare it "
                "against. It is described in the working."
                if len(visual_obs) == 1 else
                f"Art direction was readable on {len(visual_obs)} of {len(brands)} brands, which is not enough to "
                "compare. What was seen is described in the working."
            ),
            "basis": (
                "For each brand, the share of its territories that at least one rival also uses. The category "
                "score is the mean across the brands analysed, calculated the same way for messaging and for "
                "imagery, and the headline is the mean of the two."
                if conv_img else
                "For each brand, the share of its messaging territories that at least one rival also uses, "
                "averaged across the brands analysed. The imagery could not be read on enough brands this run, "
                "so the score covers messaging only."
            ),
            "bands_note": "Under 40 distinct, 40 to 59 converging, 60 to 79 converged, 80 and above indistinguishable. Scores compare within a category over time, not between categories of different size.",
        }

        # Two-axis plot: mean dissimilarity to the other brands, the same
        # calculation applied to messaging and to imagery — now over two
        # inventories of territories rather than one inventory and one fixed
        # list of dimensions, so both axes mean the same thing.
        plot = []
        for b in brands:
            peers = [o for o in brands if o != b]
            msg = 1 - (sum(jaccard(coding[b], coding[o]) for o in peers) / len(peers)) if peers else 0.0
            img = None
            if b in visual_coding:
                vpeers = [o for o in visual_brands if o != b]
                if vpeers:
                    img = 1 - sum(jaccard(visual_coding[b], visual_coding[o]) for o in vpeers) / len(vpeers)
            plot.append({"brand": b, "messaging": round(msg, 3),
                         "imagery": round(img, 3) if img is not None else None})

        plotted = [p for p in plot if p["imagery"] is not None]
        plot_meta = {
            "messaging_mean": round(sum(p["messaging"] for p in plot) / len(plot), 3) if plot else None,
            "imagery_mean": round(sum(p["imagery"] for p in plotted) / len(plotted), 3) if plotted else None,
            "imagery_territories": len(visual_positions),
            "caveat": (
                "Both axes measure how unlike the other brands each brand is — the same calculation, applied to "
                "the messaging territories and to the visual territories. The view is zoomed to the brands "
                "plotted, so read position relative to the crosshair rather than as an absolute score. "
                + (f"There are {len(visual_positions)} visual territories against {len(positions)} messaging ones, "
                   "so the vertical axis moves in coarser steps than the horizontal."
                   if visual_positions else "")
            ),
        }

        imagery_pairs = []
        for a, b in combinations(visual_brands, 2):
            same = sorted(set(visual_coding[a]) & set(visual_coding[b]))
            labels = {p["id"]: p["label"] for p in visual_positions}
            union = set(visual_coding[a]) | set(visual_coding[b])
            imagery_pairs.append({
                "pair": [a, b],
                "match": round(len(same) / len(union), 3) if union else 0.0,
                "shared": [labels.get(k, k) for k in same],
            })
        imagery_pairs.sort(key=lambda r: -r["match"])

        prov_notes = {
            "observed in category": ("Read off the brand websites",
                "Territories at least one brand actually uses. Every one has a user by definition — that is what identifying them from the sites means."),
            "patient burden literature": ("Established from patient burden literature",
                "Territories evidenced in the burden-of-illness literature, identified independently of anything these brands say."),
            "clinical barrier literature": ("Established from clinical barrier literature",
                "Territories evidenced in the prescribing, adherence and guideline literature, identified independently of anything these brands say."),
        }
        provenance_breakdown = []
        for key, (label, note) in prov_notes.items():
            sel = [p for p in positions if p["provenance"] == key]
            if sel:
                provenance_breakdown.append({
                    "key": key, "label": label, "note": note,
                    "total": len(sel),
                    "unused": sum(1 for p in sel if p["n"] == 0),
                })

        visual_prov_notes = {
            "observed in category": ("Read off the brand websites",
                "Visual territories at least one brand actually uses. Every one has a user by definition — that is what identifying them from the imagery means."),
            "patient burden literature": ("Established from patient burden literature",
                "Visual territories evidenced in the burden-of-illness and lived-experience literature, identified independently of anything these brands show."),
            "clinical barrier literature": ("Established from representation and barrier literature",
                "Visual territories evidenced in the literature on who this disease affects and where it is under-recognised, identified independently of anything these brands show."),
        }
        visual_provenance = []
        for key, (label, note) in visual_prov_notes.items():
            sel = [p for p in visual_positions if p["provenance"] == key]
            if sel:
                visual_provenance.append({
                    "key": key, "label": label, "note": note,
                    "total": len(sel),
                    "unused": sum(1 for p in sel if p["n"] == 0),
                })

        # Where each brand's art direction sits against the category's majority
        # behaviour, calculated exactly as the messaging centre is.
        v_occupied = [p["id"] for p in visual_positions if p["n"] > 0]
        cross_check = []
        for b in visual_brands:
            vdist = 0.0
            if v_occupied:
                v_counts = Counter()
                for x in visual_brands:
                    v_counts.update(visual_coding[x].keys())
                departures = [pid for pid in v_occupied
                              if (pid in visual_coding[b]) != (v_counts[pid] > len(visual_brands) / 2)]
                vdist = round(len(departures) / len(v_occupied), 3)
            v_used = len(visual_coding[b])
            v_alone = sum(1 for pid in visual_coding[b]
                          if len([x for x in visual_brands if pid in visual_coding[x]]) == 1)
            cross_check.append({
                "brand": b,
                "verbal_ownership": brand_position[b]["ownership"],
                "visual_ownership": round(v_alone / v_used, 3) if v_used else 0.0,
                "visual_distance": vdist,
                "hero_notes": visual_summaries.get(b, ""),
            })

        # 7 — the findings
        yield ev({"type": "progress", "text": "Writing the findings — each one linked to the wording on a brand's website that produced it."})
        occ, crw = metrics["occupancy_rate"], metrics["crowding_rate"]
        n_b = len(brands)
        lit_empty = [k for k in metrics["empty_ids"] if k[0] in "XH"]
        universal = [p["id"] for p in positions if p["n"] == n_b]
        # Plain, and the numbers add up: shared + sole-held + unused = the whole
        # list. The reader should not have to hold anything in their head.
        both = "both brands" if n_b == 2 else "more than one brand"
        # The headline leads with the score, because that is the number that
        # gets forwarded. The counts behind it follow immediately, and they add
        # up: shared + sole-held + unused is the whole list. The reader should
        # not have to hold anything in their head.
        v_unused = sum(1 for p in visual_positions if p["n"] == 0)
        fallback_headline = (
            f"This category scores {conv['overall']} for convergence — {conv['band']['name'].lower()}. "
            f"Of {metrics['space_size']} messaging territories, {metrics['contested']} are used by {both}, "
            f"{metrics['sole_held']} by only one, and {metrics['empty']} by neither. "
            f"{len(lit_empty)} of those unused territories come from published evidence on what patients and "
            f"clinicians say is missing, rather than from anything these brands publish."
            + (f" The art direction scores {conv_img['mean']}, with {v_unused} of "
               f"{len(visual_positions)} visual territories depicted by nobody."
               if conv_img else "")
        )
        standfirst = (
            "Shared territory is the expensive part. Where several brands make the same argument, none of them "
            "owns it, and the audience is given no basis on which to tell them apart. "
            f"Of the {len(lit_empty)} territories nobody explores, {metrics['open_empty']} need no new clinical "
            "evidence to work with — no additional trial, no new endpoint, nothing further to substantiate. They "
            "are decisions about how the disease is described, who the communications address, and where they "
            "appear, all inside the existing label. They are unexplored because nobody chose them, not because "
            "nobody could."
        )
        try:
            summary = await stage_findings(category, metrics, positions, brands, cross_check,
                                           conv, visual_positions)
        except Exception:
            summary = {}
        # The headline is written by the model and the score is computed, so the
        # two can disagree — and the headline is the part that gets forwarded.
        # If the written one does not carry the number printed beside it, the
        # plain computed sentence is used instead.
        written = (summary.get("headline") or "").strip()
        if written and re.search(rf"\b{conv['overall']}\b", written):
            headline = written
        else:
            headline = fallback_headline
            if written:
                yield ev({"type": "progress", "text": (
                    "The written headline did not carry the computed score, so the plain computed one is used."
                )})
        valid_refs = {p["id"] for p in positions} | {f"visual:{p['id']}" for p in visual_positions}
        findings = []
        for f in summary.get("findings", []) or []:
            refs = [r for r in f.get("refs", []) if r in valid_refs]
            if f.get("text"):
                findings.append({"text": f["text"], "refs": refs})
        if not findings:
            findings = [{"text": "The run completed but the findings pass failed; the map and the tables below are still the computed result.", "refs": []}]
        comments = summary.get("brand_comments", {}) or {}
        for row in cross_check:
            row["comment"] = comments.get(row["brand"], "")

        from datetime import date
        result = {
            "meta": {
                "tool": "Sameness Index",
                "version": "0.2",
                "category": category,
                "market": "as served to this reader",
                "captured": date.today().strftime("%-d %B %Y"),
                "audience_note": "Public websites only, as served at capture.",
                "brands": [
                    {"name": b["name"], "url": b["url"], "accent": ACCENTS[i % len(ACCENTS)]}
                    for i, b in enumerate(brands_in)
                ],
                "unreadable": unreadable,
            },
            "headline": headline,
            "standfirst": standfirst,
            "convergence": conv,
            "tier_labels": TIER_READER_LABELS,
            "metrics": metrics,
            "positions": positions,
            "visual_positions": visual_positions,
            "brand_position": brand_position,
            "centre": centre,
            "plot": plot,
            "plot_meta": plot_meta,
            "imagery_pairs": imagery_pairs,
            "provenance_breakdown": provenance_breakdown,
            "visual_provenance": visual_provenance,
            "visual": {
                "brands": visual_brands,
                "read": visual_read,
                "compared": bool(visual_positions),
                "notes": visual_summaries,
                "images": image_urls,
                "territories": len(visual_positions),
                "unclaimed": v_unused,
                "exclusions": "Only commissioned photography is scored here. Clinical images, diagrams of how the drug works and pack shots are excluded, because they were determined by the product rather than chosen by art direction. The visual territories are built for this category the same way the messaging territories are — from what these brands show, plus what the literature evidences and nobody shows."
                + ("" if visual_positions else (
                    f" Only {len(visual_read)} brand's art direction could be read this run"
                    if len(visual_read) == 1 else
                    " The art direction could not be read on enough brands this run")
                   + ", and art direction cannot be compared against nobody — so what was seen is described below rather than scored, and the convergence figure covers messaging only."),
            },
            "cross_check": cross_check,
            "findings": findings,
            "boundary_rules": GENERIC_BOUNDARY_RULES,
            "limitations": ([
                "Asked for, but could not be read: " + ", ".join(f"{u['name']} ({u['url']})" for u in unreadable)
                + ". Those sites turn away automated readers or build their pages in the browser, so nothing from them "
                "is in these numbers. They are competing in this category whether or not this analysis could see them, "
                "and a territory counted here as used by nobody may well be used by one of them."
            ] if unreadable else []) + [
                "The percentages depend on how many territories were identified. Those read off the websites have a user by definition, and those established from the literature are largely unused, also close to by definition. A longer literature list lowers the usage figure without anything changing in the market. Treat the percentages as a description of this list, not as a property of the category; the count of named, evidenced, unused territories does not move when the list length does, which is why it leads.",
                "Deciding what was determined by the label and what was a marketing decision is a judgement. The rules are published on this page, applied identically to every brand, and open to challenge. Different reasonable rules would change the numbers.",
                "Websites only. Congress activity, sales aids, field and MSL messaging, paid media and social are not included. This measures the public messaging each brand publishes, not its full commercial message.",
                "Every site's robots.txt was read before anything else, and honoured. Pages a brand asks automated readers to leave alone were not read, and a brand that declines entirely is named above rather than worked around. Each page was requested once, as a person following the same links would.",
                f"{len(brands)} brands were analysed. The comparison is meaningful but sensitive to any one brand being unusual."
                + (" With fewer than four brands, treat the shared-position figure as indicative only." if len(brands) < 4 else ""),
                "A single capture, taken once. This is a snapshot, not a trend.",
                "Deciding which territories a brand uses is a judgement made against the published rules, assisted by a language model. Every decision carries the exact wording from the site that produced it, so any of them can be checked and disagreed with.",
                "Coding a picture involves more judgement than quoting a sentence does. Each brand's commissioned imagery is read into written observations first, the visual territories are built from those observations, and every visual territory opens the image and the observation it was coded from — so any call can be checked and disagreed with. Only the images reachable from the pages read are included; a brand's wider campaign is not.",
                "Availability ratings are a strategic assessment, not a regulatory one. Every position requires medical, legal and regulatory review before use.",
                "Before trusting the result in a new category, run two brands on their own as a control. If two brands alone produce a similar level of shared positioning, the separation of label-determined content has not worked, and the tool is measuring the shared vocabulary of the therapy area rather than the choices brands made.",
            ],
        }
        yield ev({"type": "result", "data": result})
      finally:
        await fetcher.close()


# ---------------------------------------------------------------------------
# Jobs
#
# The pipeline is a generator of events. Running it in the background means
# consuming that generator somewhere other than a request handler and writing
# each event down as it arrives, so the page can pick the narration up wherever
# it happens to be looking — including after a reload, or on a different
# machine entirely.
# ---------------------------------------------------------------------------

store = Store()
_running = set()
# asyncio holds only a weak reference to a running task, so a task nobody keeps
# can be collected mid-run. Holding them here is what stops a run vanishing
# silently halfway through.
_tasks = set()


async def execute_run(run_id, brands, category=""):
    """Consume the pipeline, recording everything it says and produces."""
    _running.add(run_id)
    try:
        async for event in pipeline(brands, category):
            if event.get("type") == "result":
                await store.finish(run_id, event["data"])
                return
            if event.get("type") == "error":
                await store.fail(run_id, event["text"])
                return
            await store.append_progress(run_id, event)
        await store.fail(run_id, "The run ended without producing a result.")
    except asyncio.CancelledError:
        await store.fail(run_id, "The run was cancelled before it finished.")
        raise
    except Exception as e:
        await store.fail(run_id, f"The run failed: {e}")
    finally:
        _running.discard(run_id)


def now_seconds():
    import time
    return time.time()


def client_ip(request):
    """Render, Fly and Cloudflare all put the real address in X-Forwarded-For
    and terminate TLS themselves, so request.client is the proxy."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


@app.post("/api/run")
async def start_run(request: Request):
    """Start a run and hand back its id. Returns in milliseconds; the work
    carries on without the request."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Could not read the request."}, status_code=400)

    brands = [b for b in (body.get("brands") or []) if b.get("name") and b.get("url")]
    category = (body.get("category") or "").strip()[:160]
    if len(brands) < 2:
        return JSONResponse(
            {"error": "Each brand needs a name and a URL, and the index needs your brand plus at least one competitor."},
            status_code=400,
        )
    if len(brands) > MAX_BRANDS_PER_RUN:
        return JSONResponse(
            {"error": f"The index reads up to {MAX_BRANDS_PER_RUN} brands in one run."},
            status_code=400,
        )

    if len(_running) >= MAX_CONCURRENT_RUNS:
        return JSONResponse(
            {"error": "The index is reading another category right now. Try again in a few minutes — a run takes two to five."},
            status_code=429,
        )

    ip = client_ip(request)
    if MAX_RUNS_PER_IP_PER_DAY and await store.runs_since(ip, 86400) >= MAX_RUNS_PER_IP_PER_DAY:
        return JSONResponse(
            {"error": f"That is {MAX_RUNS_PER_IP_PER_DAY} runs from this connection today, which is the limit. Each run reads live websites and costs real money. Get in touch if you need more."},
            status_code=429,
        )

    run_id = await store.create(
        [{"name": b["name"].strip(), "url": b["url"].strip()} for b in brands],
        client_ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    task = asyncio.create_task(execute_run(run_id, brands, category))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"id": run_id, "url": f"/r/{run_id}"}


@app.get("/api/run/{run_id}")
async def poll_run(run_id: str, since: int = 0):
    """Everything the run has said since line `since`, plus the result once
    there is one. Safe to call repeatedly and safe to call late."""
    run = await store.get(run_id, since=max(0, since))
    if run is None:
        return JSONResponse({"error": "No run with that link. It may have been from a previous version of the tool."}, status_code=404)
    return run


@app.get("/r/{run_id}")
async def permalink(run_id: str):
    """The shareable result. The page reads the id out of its own URL and asks
    for the stored run — so this is the same front end, with no login and
    nothing to set up."""
    return FileResponse(os.path.join(HERE, "index.html"))


# ---------------------------------------------------------------------------
# Finding the sites
#
# Pasting four competitor URLs is the hardest thing this tool asks of anyone,
# and it is asked before they have seen a single reason to bother. So: name one
# brand, and the tool proposes the category, the competitors and their
# addresses — every address fetched and confirmed before it is offered.
#
# The check that proves an address is real also reveals whether it can be read
# at all, which is worth as much as the convenience. Sites behind bot
# protection are shown as unavailable up front, instead of failing three
# minutes into a run that has already cost money.
# ---------------------------------------------------------------------------

MAX_FINDS_PER_IP_PER_DAY = int(os.environ.get("SAMENESS_FINDS_PER_IP", "40"))
MIN_READABLE_CHARS = 500
_finds = {}


def audience_of(url, title, text):
    """Patient site or professional site. Read from the address first, since
    brands are consistent about it, then from what the page says about itself."""
    blob = f"{url} {title}".lower()
    if re.search(r"\b(hcp|pro|professional|medlink|medinfo)\b|hcp\.|/hcp|pro\.", blob):
        return "hcp"
    if re.search(r"health care professional|healthcare professional|for us healthcare professionals|prescribing information for professionals", text[:4000].lower()):
        return "hcp"
    return "patient"


async def check_site(fetcher, url, sem):
    """Fetch one candidate. Returns None if there is nothing really there."""
    if not url.startswith("http"):
        url = "https://" + url
    async with sem:
        try:
            if not await fetcher.allowed(url):
                return {"url": url, "title": "", "readable": False, "chars": 0,
                        "status": 0, "audience": "patient", "reason": "asked not to be read"}
            r = await fetcher.get(url, timeout=20)
        except Exception:
            return None
        if "text/html" not in r.headers.get("content-type", ""):
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        title = (soup.title.string or "").strip() if soup.title else ""
        text = visible_text(soup)
        blocked = r.status_code in (401, 403, 405, 429) or r.status_code >= 500
        return {
            "url": str(r.url),
            "title": re.sub(r"\s+", " ", title)[:120],
            "readable": (not blocked) and r.status_code == 200 and len(text) >= MIN_READABLE_CHARS,
            "chars": len(text),
            "status": r.status_code,
            "audience": audience_of(str(r.url), title, text),
        }


@app.post("/api/find")
async def find_sites(request: Request):
    """Who this brand competes with, and where those brands live.

    The competitive set comes from openFDA — the brand's established
    pharmacologic class, and every other branded product in it. Those are
    facts on a label. The model is asked afterwards only to narrow a real list
    to the ones a marketing team would actually name in the room, which is
    judgement rather than recall, and it can only remove, never add.

    Addresses come from the directory first. A brand somebody has already run
    is instant; a new one is guessed and checked once, then remembered.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Could not read the request."}, status_code=400)

    brand = (body.get("brand") or "").strip()[:80]
    hint = (body.get("category") or "").strip()[:160]
    audience = "hcp" if (body.get("audience") or "").lower() == "hcp" else "patient"
    if len(brand) < 2:
        return JSONResponse({"error": "Enter the name of your brand."}, status_code=400)

    ip = client_ip(request)
    today = int(now_seconds() // 86400)
    key = (ip, today)
    if MAX_FINDS_PER_IP_PER_DAY and _finds.get(key, 0) >= MAX_FINDS_PER_IP_PER_DAY:
        return JSONResponse({"error": "That is a lot of lookups from this connection today. Try again tomorrow, or get in touch."}, status_code=429)
    _finds[key] = _finds.get(key, 0) + 1
    for k in list(_finds):
        if k[1] != today:
            del _finds[k]

    async with httpx.AsyncClient() as http:
        prof = await drugs.profile(http, brand)
        peers = await drugs.peers(http, prof) if prof else []
        source = "openFDA" if prof else "model"

        # openFDA is the FDA's register, so it knows US products. Outside that
        # — or on a misspelling — fall back to asking, and say which happened
        # rather than letting the reader assume the list was looked up.
        if not prof:
            try:
                proposed = await stage_find(brand, hint)
            except Exception as e:
                return JSONResponse({"error": f"Could not look that up. {e}"}, status_code=502)
            wanted = [{"name": (b.get("name") or "").strip(),
                       "company": (b.get("company") or "").strip(),
                       "candidates": (b.get("candidates") or [])[:4]}
                      for b in (proposed.get("brands") or []) if b.get("name")][:7]
            category = (proposed.get("category") or hint or "").strip()[:160]
            mismatch = ""
        else:
            label_says = await drugs.category_of(http, prof)
            category = hint or label_says or (
                f"{prof['generic']} and its class" if prof.get("generic") else "")
            # The therapy area frames the entire analysis — every territory is
            # built for it. Somebody who types an area that has nothing to do
            # with the drug they picked gets a report about a conversation
            # nobody is having, and would rather be told now.
            if hint and label_says and not drugs.area_matches(hint, label_says, prof):
                mismatch = (
                    f"{prof['brand']} is labelled for "
                    f"{drugs.short_indication(label_says)}, which does not look like "
                    f"\u201c{hint}\u201d. Every territory is built for the therapy area, "
                    "so check it before running \u2014 or clear it and the label decides."
                )
            else:
                mismatch = ""
            shortlist = peers
            if len(peers) > 5:
                # Narrowing a real list, not building one: anything the model
                # returns that is not already in `peers` is discarded.
                try:
                    keep = await stage_shortlist(prof, peers, category)
                    allowed = {p["brand"].lower() for p in peers}
                    chosen = [k for k in keep if k.lower() in allowed]
                    if chosen:
                        order = {k.lower(): i for i, k in enumerate(chosen)}
                        shortlist = sorted(
                            [p for p in peers if p["brand"].lower() in order],
                            key=lambda p: order[p["brand"].lower()])
                except Exception:
                    shortlist = peers[:6]
            wanted = [{"name": prof["brand"], "company": prof.get("company", ""), "candidates": []}]
            wanted += [{"name": p["brand"], "company": p.get("company", ""), "candidates": []}
                       for p in shortlist[:6]]

        # The directory answers for anything already seen. It only ever saves
        # work, so if it is unavailable the lookup carries on without it.
        try:
            known = await store.brand_sites([w["name"] for w in wanted])
        except Exception:
            known = {}
        sem = asyncio.Semaphore(8)
        fetcher = Fetcher(http)
        try:
            async def resolve(w):
                cached = known.get(w["name"].strip().lower()) or {}
                url = cached.get("hcp_url" if audience == "hcp" else "patient_url")
                ok = cached.get("hcp_ok" if audience == "hcp" else "patient_ok")
                if url and ok:
                    return w, [{"url": url, "title": w["name"], "readable": True,
                                "chars": 0, "status": 200, "audience": audience,
                                "from_directory": True}], True
                candidates = w["candidates"] or drugs.candidate_urls(w["name"], audience)
                found = await asyncio.gather(*[check_site(fetcher, u, sem) for u in candidates[:5]])
                return w, [s for s in found if s], False

            resolved = await asyncio.gather(*[resolve(w) for w in wanted])
        finally:
            await fetcher.close()

    out, learned = [], 0
    for w, results, from_directory in resolved:
        sites, seen_urls = [], set()
        for s in results:
            tidy = s["url"].rstrip("/")
            if tidy in seen_urls:
                continue
            seen_urls.add(tidy)
            sites.append(s)
        # Readable first, then the audience that was asked for.
        sites.sort(key=lambda s: (not s["readable"], s["audience"] != audience))
        best = next((s for s in sites if s["readable"]), None)
        if best and not from_directory:
            # Learned once, for everybody, for next time.
            meta = next((p for p in (peers or []) if p["brand"].lower() == w["name"].lower()), {})
            try:
                await store.remember_brand(
                    w["name"], display_name=w["name"],
                    generic_name=meta.get("generic") or (prof or {}).get("generic"),
                    company=w.get("company") or meta.get("company"),
                    pharm_class=((prof or {}).get("classes") or [None])[0],
                    **{("hcp_url" if audience == "hcp" else "patient_url"): best["url"],
                       ("hcp_ok" if audience == "hcp" else "patient_ok"): True})
                learned += 1
            except Exception:
                pass          # a directory write must never fail a lookup
        out.append({
            "name": w["name"][:60],
            "company": (w.get("company") or "")[:60],
            "sites": sites[:4],
            "any_readable": any(s["readable"] for s in sites),
            "from_directory": from_directory,
        })

    return {
        "category": category,
        "audience": audience,
        "source": source,
        "generic": (prof or {}).get("generic", ""),
        "pharm_class": ((prof or {}).get("classes") or [""])[0],
        "mismatch": mismatch,
        "known": sum(1 for _w, _r, d in resolved if d),
        "learned": learned,
        "brands": out,
    }


# ---------------------------------------------------------------------------
# The type-ahead.
#
# The index is ~30 openFDA requests, so it is built once in the background and
# held in memory. A cold instance answers from a shorter list until the full one
# arrives rather than making anybody wait for a network round trip between
# keystrokes.
# ---------------------------------------------------------------------------

_index = {"rows": [], "built_at": 0.0, "building": False}


async def _build_index_once():
    if _index["building"] or _index["rows"]:
        return
    _index["building"] = True
    try:
        async with httpx.AsyncClient() as http:
            rows = await drugs.build_index(http)
        if rows:
            _index["rows"] = rows
            _index["built_at"] = now_seconds()
    except Exception:
        pass                      # a failed index is a quiet degradation, not an outage
    finally:
        _index["building"] = False


@app.get("/api/suggest")
async def suggest(q: str = "", kind: str = "drug"):
    """What the person is probably typing. Never blocks on the network."""
    q = (q or "").strip()[:60]
    if kind == "area":
        return {"kind": "area", "results": [{"label": a} for a in drugs.search_areas(q)]}

    if not _index["rows"] and not _index["building"]:
        # First keystroke of the instance's life starts the build; this request
        # still answers, from nothing, and the next one will be complete.
        asyncio.create_task(_build_index_once())
    if len(q) < 2:
        return {"kind": "drug", "results": [], "ready": bool(_index["rows"])}

    hits = drugs.search_index(_index["rows"], q)
    return {
        "kind": "drug",
        "ready": bool(_index["rows"]),
        "results": [
            {"label": h["brand"], "generic": h.get("generic", ""),
             "company": h.get("company", ""), "cls": h.get("cls", "")}
            for h in hits
        ],
    }


@app.get("/api/health")
async def health():
    return {"ok": True, "persistent": store.persistent, "running": len(_running)}


# ---------------------------------------------------------------------------
# Static files — an allowlist, not a directory.
#
# Serving the folder would serve the folder: this file, with every coding
# prompt and layer rule in it, and methodology.md alongside it. The method is
# the thing worth having. It stays on this side of the wire, and only the two
# files the page actually needs are reachable.
#
# The boundary rules and the limitations are still shown to the reader — they
# travel inside the result, in the "full working", where they belong.
# ---------------------------------------------------------------------------

PUBLIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "worked_example.json": "application/json",
    "favicon.ico": "image/x-icon",
    # The brand's own cut of Fraunces — the 72pt Soft, with the rounded stem
    # terminals. Google Fonts serves the standard 72pt, which is a different
    # typeface at display size and the first thing that makes a page look
    # nearly-but-not-quite like the site. Bundled rather than linked to
    # thisisrupture.com, because a cross-origin font needs a CORS header the
    # site does not send.
    "fonts/Fraunces_72pt_Soft-Regular.ttf": "font/ttf",
    "fonts/Fraunces_72pt_Soft-Bold.ttf": "font/ttf",
    "fonts/Fraunces_72pt_Soft-Black.ttf": "font/ttf",
}


@app.get("/")
async def home():
    return FileResponse(os.path.join(HERE, "index.html"))


# `:path` so the bundled fonts under fonts/ can be reached. It is still an
# allowlist and nothing else: an address that is not a key of PUBLIC_FILES is a
# 404 before the filesystem is touched, so a path with .. in it cannot resolve
# to anything, and this route is declared last so it never shadows the API.
@app.get("/{filename:path}")
async def public_file(filename: str):
    media_type = PUBLIC_FILES.get(filename)
    if media_type is None:
        return JSONResponse({"error": "Not found."}, status_code=404)
    path = os.path.join(HERE, filename)
    if not os.path.isfile(path):
        return JSONResponse({"error": "Not found."}, status_code=404)
    headers = {"Cache-Control": "public, max-age=31536000, immutable"} if filename.startswith("fonts/") else None
    return FileResponse(path, media_type=media_type, headers=headers)
