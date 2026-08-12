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
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from itertools import combinations
from urllib.parse import urljoin, urlparse

import httpx
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

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
# Rupture palette. Mint is reserved as a highlight, not a brand accent —
# it lacks contrast against the paper at label sizes.
ACCENTS = ["#FF686B", "#1F5B4A", "#303030", "#727270", "#51D4B2", "#ABAAA8", "#D7D6D2"]
UA = "SamenessIndex/0.2 (strategy research; reads public brand sites once)"

@asynccontextmanager
async def lifespan(_app):
    await store.start()
    yield
    await store.stop()


app = FastAPI(lifespan=lifespan)

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

VISUAL_DIMENSIONS = [
    ("human_configuration", "Who is in the picture"),
    ("touch", "Is anyone touching anyone"),
    ("disease_depiction", "Is the disease shown"),
    ("skin_tone_range", "Range of skin tones"),
    ("life_moment", "What is happening"),
    ("emotional_register", "How it is meant to feel"),
    ("abstraction_motif", "Graphic device used"),
    ("category_borrow", "What it looks like it is selling"),
]

PROVENANCE_LABELS = {
    "C": "observed in category",
    "X": "patient burden literature",
    "H": "clinical barrier literature",
}


# ---------------------------------------------------------------------------
# Crawling
# ---------------------------------------------------------------------------

PRIORITY_HINTS = [
    "about", "why", "how", "what-is", "efficacy", "results", "safety",
    "patients", "hcp", "dosing", "getting-started", "science", "support",
    "savings", "cost", "access", "caregiver", "resources",
]


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


async def crawl_brand(http, brand):
    """Fetch the given URL plus a handful of same-domain pages. Returns
    (pages_text, image_candidates, pages_fetched)."""
    start = brand["url"]
    if not start.startswith("http"):
        start = "https://" + start
    root = urlparse(start).netloc.replace("www.", "")
    queue, seen, texts, images = [start], set(), [], []

    while queue and len(seen) < MAX_PAGES_PER_BRAND:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            r = await http.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
        except Exception:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        if url == start:  # image candidates from the landing page only
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                images.append(urljoin(url, og["content"]))
            for img in soup.find_all("img", src=True)[:12]:
                src = urljoin(url, img["src"])
                if re.search(r"\.(jpe?g|png|webp)", src, re.I):
                    images.append(src)

        texts.append(f"[PAGE {url}]\n" + visible_text(soup)[:12000])

        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a["href"]).split("#")[0]
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
    return corpus, images, len(seen)


async def fetch_hero_image(http, urls):
    """Return (media_type, base64) for the first retrievable candidate."""
    for u in urls[:5]:
        try:
            r = await http.get(u, headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
            mt = r.headers.get("content-type", "").split(";")[0].strip()
            if r.status_code == 200 and mt in ("image/jpeg", "image/png", "image/webp") and len(r.content) < 4_500_000:
                return mt, base64.standard_b64encode(r.content).decode()
        except Exception:
            continue
    return None, None


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

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
    msg = await get_client().messages.create(
        model=MODEL, max_tokens=max_tokens,
        messages=[{"role": "user", "content": content}],
    )
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

Return ONLY JSON — a list:
[{{"id": "C01", "label": "<the move, one line>",
   "description": "<plain English, one sentence>",
   "source": "<for C: 'Observed in category.' For X/H: the specific literature basis>",
   "tier": "open|frame_only|constrained|closed",
   "tier_reasoning": "<1-2 sentences, specific to this category>"}}, ...]"""
    return await llm_json(prompt, max_tokens=20000, stage="building the territory list")


async def stage_code(brand, frags, positions):
    plist = "\n".join(f'{p["id"]}: {p["label"]} — {p["description"]}' for p in positions)
    frag_block = "\n".join(f"- {x}" for x in frags)
    prompt = f"""Code one brand's elective-layer copy against a fixed list of positions.

A position is TAKEN only if the copy clearly makes that move. Be strict: the
evidence string must be the verbatim fragment (or near-verbatim) that triggers
the code, quoted from the copy below. Do not infer from molecule facts. If in
doubt, do not code it — under-coding is the conservative direction.

Positions:
{plist}

Elective copy for "{brand}":
{frag_block}

Return ONLY JSON: {{"<position id>": "<verbatim evidence from the copy>", ...}}
Only include positions that are clearly taken. An empty object is a valid answer."""
    return await llm_json(prompt, max_tokens=8000, stage="scoring a brand against the territories")


async def stage_visual(brand, mt, b64):
    dims = "\n".join(f"- {k}: {label}" for k, label in VISUAL_DIMENSIONS)
    prompt = f"""Code this brand hero image ({brand}) on plain-English dimensions.
Commissioned imagery only — if this is clinical photography, a mechanism
diagram or a pack shot, return {{"excluded": true, "reason": "<why>"}}.

Dimensions (pick ONE short value each, lower case):
- human_configuration: none / individual alone / caregiver-child dyad / family group / clinician-patient
- touch: absent / self-touch / interpersonal touch
- disease_depiction: clinical lesion / visible on lifestyle model / implied only / absent
- skin_tone_range: single / limited / broad
- life_moment: clinical / ordinary domestic / leisure / achievement / abstract
- emotional_register: relief / celebration / calm control / confidence / tenderness / neutral clinical
- abstraction_motif: none / natural / scientific / cosmetic / celestial
- category_borrow: pharma / beauty and skincare / wellness / consumer tech

Return ONLY JSON: {{"human_configuration": "...", ..., "child_present": true/false,
"notes": "<2-3 sentences describing what the image shows and how>"}}"""
    return await llm_json(prompt, max_tokens=2000, images=[(mt, b64)], stage="reading the hero image")


async def stage_findings(category, metrics, positions, brands, cross_check):
    pos_lines = "\n".join(
        f'{p["id"]} [{p["tier"]}] ({p["n"]} of {len(brands)}: {", ".join(p["claimers"]) or "nobody"}) {p["label"]}'
        for p in positions
    )
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

Metrics (computed, do not recompute): {json.dumps(metrics)}
Positions:
{pos_lines}
Verbal/visual cross-check: {cc}

Return ONLY JSON:
{{
 "headline": "<LEAD WITH THE SAMENESS — how much of what these brands say is
   said by more than one of them. Then, and only then, the unexplored territory.
   Do not leave 'no new clinical evidence' as an unexplained phrase, and write
   'explore' rather than 'take' or 'own' — some territories will not suit a
   given brand and the tool does not know which. Follow this pattern: '73% of
   what these four brands say, they say together. 16 of the 22 messaging
   territories in play are shared with a competitor, and 2 are used by every
   brand in the category. A further 18, each with published evidence behind it,
   are explored by nobody.'>",
 "findings": [  // 3 to 5, each one sentence or two, each with evidence refs
   {{"text": "<the finding>", "refs": ["<position id>" or "visual:<dimension key>", ...]}}
 ],
 "brand_comments": {{"<brand>": "<one sentence on its verbal vs visual posture>", ...}}
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


async def pipeline(brands_in):
    brands = [b["name"].strip() for b in brands_in]
    yourn = brands[0]

    async with httpx.AsyncClient() as http:

        # 1 — read the sites
        corpora, image_cands = {}, {}
        for b in brands_in:
            host = urlparse(b["url"] if b["url"].startswith("http") else "https://" + b["url"]).netloc or b["url"]
            yield ev({"type": "progress", "text": f"Reading {host} — the public website, as a patient or prescriber would find it."})
            corpus, images, n_pages = await crawl_brand(http, b)
            if len(corpus) < 400:
                yield ev({"type": "error", "text": f"Could not read enough of {b['name']}'s site ({b['url']}). It may block automated readers or render entirely in JavaScript."})
                return
            corpora[b["name"]] = corpus
            image_cands[b["name"]] = images
            yield ev({"type": "progress", "text": f"{b['name']}: {n_pages} page{'s' if n_pages != 1 else ''} read."})

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
        category = category_votes[0] if category_votes else "this category"

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

        for p in positions:
            p["claimers"] = [b for b in brands if p["id"] in coding[b]]
            p["n"] = len(p["claimers"])
            p["receipts"] = {b: coding[b][p["id"]] for b in p["claimers"]}

        # 5 — visual layer
        yield ev({"type": "progress", "text": "Coding the hero imagery — commissioned photography only. Clinical images, mechanism diagrams and pack shots are excluded, because they were not art direction decisions."})
        visual, notes = {}, {}
        for b in brands:
            mt, b64 = await fetch_hero_image(http, image_cands.get(b, []))
            if not b64:
                continue
            try:
                v = await stage_visual(b, mt, b64)
            except Exception:
                continue
            if v.get("excluded"):
                continue
            visual[b] = v
            notes[b] = v.get("notes", "")

        visual_rows, modal_profile = [], {}
        if len(visual) >= 2:
            for key, label in VISUAL_DIMENSIONS:
                vals = Counter(str(visual[b].get(key, "")) for b in visual)
                modal, n = vals.most_common(1)[0]
                modal_profile[key] = modal
                visual_rows.append({
                    "key": key, "label": label, "modal_value": modal,
                    "agreement": round(n / len(visual), 3),
                    "spread": dict(vals),
                    "per_brand": {b: visual[b].get(key, "—") for b in visual},
                })
            visual_rows.sort(key=lambda r: -r["agreement"])

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

        # Two-axis plot: mean dissimilarity to the other brands, same
        # calculation applied to messaging and to imagery.
        plot = []
        for b in brands:
            peers = [o for o in brands if o != b]
            msg = 1 - (sum(jaccard(coding[b], coding[o]) for o in peers) / len(peers)) if peers else 0.0
            img = None
            if b in visual:
                vpeers = [o for o in peers if o in visual]
                if vpeers:
                    img = 1 - sum(
                        sum(1 for k, _ in VISUAL_DIMENSIONS
                            if str(visual[b].get(k, "")) == str(visual[o].get(k, ""))) / len(VISUAL_DIMENSIONS)
                        for o in vpeers
                    ) / len(vpeers)
            plot.append({"brand": b, "messaging": round(msg, 3),
                         "imagery": round(img, 3) if img is not None else None})

        plotted = [p for p in plot if p["imagery"] is not None]
        n_dims = len(VISUAL_DIMENSIONS)
        dims_with_majority = sum(
            1 for k, _ in VISUAL_DIMENSIONS
            if visual and max(Counter(str(visual[b].get(k, "")) for b in visual).values()) > len(visual) / 2
        )
        plot_meta = {
            "messaging_mean": round(sum(p["messaging"] for p in plot) / len(plot), 3) if plot else None,
            "imagery_mean": round(sum(p["imagery"] for p in plotted) / len(plotted), 3) if plotted else None,
            "imagery_step": round(1 / n_dims, 3),
            "imagery_dimensions": n_dims,
            "imagery_dimensions_with_majority": dims_with_majority,
            "caveat": (
                "Both axes measure how unlike the other brands each brand is — the same calculation, "
                "applied to messaging and to imagery. The view is zoomed to the brands plotted, so read "
                "position relative to the crosshair rather than as an absolute score. Imagery moves in "
                f"steps of {round(100 / n_dims)} percentage points because there are only {n_dims} coded "
                "dimensions, so small vertical differences are coarse."
            ),
        }

        imagery_pairs = []
        for a, b in combinations([x for x in brands if x in visual], 2):
            same = [k for k, _ in VISUAL_DIMENSIONS
                    if str(visual[a].get(k, "")) == str(visual[b].get(k, ""))]
            imagery_pairs.append({
                "pair": [a, b],
                "match": round(len(same) / len(VISUAL_DIMENSIONS), 3),
                "shared": [lbl for k, lbl in VISUAL_DIMENSIONS if k in same],
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

        cross_check = []
        if modal_profile:
            for b in brands:
                if b not in visual:
                    continue
                vdist = sum(1 for k, _ in VISUAL_DIMENSIONS
                            if str(visual[b].get(k, "")) != modal_profile[k]) / len(VISUAL_DIMENSIONS)
                cross_check.append({
                    "brand": b,
                    "verbal_ownership": brand_position[b]["ownership"],
                    "visual_distance": round(vdist, 3),
                    "hero_notes": notes.get(b, ""),
                })

        # 7 — the findings
        yield ev({"type": "progress", "text": "Writing the findings — each one linked to the wording on a brand's website that produced it."})
        occ, crw = metrics["occupancy_rate"], metrics["crowding_rate"]
        n_b = len(brands)
        lit_empty = [k for k in metrics["empty_ids"] if k[0] in "XH"]
        universal = [p["id"] for p in positions if p["n"] == n_b]
        fallback_headline = (
            f"{crw:.0%} of what these {n_b} brands say, they say together. "
            f"{metrics['contested']} of the {metrics['occupied']} messaging territories in play are shared "
            f"with a competitor, and {len(universal)} are used by every brand in the category. "
            f"A further {len(lit_empty)}, each with published evidence behind it, are explored by nobody."
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
            summary = await stage_findings(category, metrics, positions, brands, cross_check)
        except Exception:
            summary = {}
        headline = summary.get("headline") or fallback_headline
        valid_refs = {p["id"] for p in positions} | {f"visual:{r['key']}" for r in visual_rows}
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
            },
            "headline": headline,
            "standfirst": standfirst,
            "metrics": metrics,
            "positions": positions,
            "brand_position": brand_position,
            "centre": centre,
            "plot": plot,
            "plot_meta": plot_meta,
            "imagery_pairs": imagery_pairs,
            "provenance_breakdown": provenance_breakdown,
            "visual": {
                "dimensions": visual_rows,
                "child_in_hero": sum(1 for b in visual if visual[b].get("child_present")),
                "notes": notes,
                "exclusions": "Only commissioned photography is scored here. Clinical images, diagrams of how the drug works and pack shots are excluded, because they were determined by the product rather than chosen by art direction. Each brand's lead image is coded on the dimensions below."
                + ("" if visual_rows else " Lead images could not be retrieved for enough brands on this run, so imagery is not reported."),
            },
            "cross_check": cross_check,
            "findings": findings,
            "boundary_rules": GENERIC_BOUNDARY_RULES,
            "limitations": [
                "The percentages depend on how many territories were identified. Those read off the websites have a user by definition, and those established from the literature are largely unused, also close to by definition. A longer literature list lowers the usage figure without anything changing in the market. Treat the percentages as a description of this list, not as a property of the category; the count of named, evidenced, unused territories does not move when the list length does, which is why it leads.",
                "Deciding what was determined by the label and what was a marketing decision is a judgement. The rules are published on this page, applied identically to every brand, and open to challenge. Different reasonable rules would change the numbers.",
                "Websites only. Congress activity, sales aids, field and MSL messaging, paid media and social are not included. This measures the public messaging each brand publishes, not its full commercial message.",
                f"{len(brands)} brands were analysed. The comparison is meaningful but sensitive to any one brand being unusual."
                + (" With fewer than four brands, treat the shared-position figure as indicative only." if len(brands) < 4 else ""),
                "A single capture, taken once. This is a snapshot, not a trend.",
                "Deciding which territories a brand uses is a judgement made against the published rules, assisted by a language model. Every decision carries the exact wording from the site that produced it, so any of them can be checked and disagreed with.",
                "Availability ratings are a strategic assessment, not a regulatory one. Every position requires medical, legal and regulatory review before use.",
                "Before trusting the result in a new category, run two brands on their own as a control. If two brands alone produce a similar level of shared positioning, the separation of label-determined content has not worked, and the tool is measuring the shared vocabulary of the therapy area rather than the choices brands made.",
            ],
        }
        yield ev({"type": "result", "data": result})


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


async def execute_run(run_id, brands):
    """Consume the pipeline, recording everything it says and produces."""
    _running.add(run_id)
    try:
        async for event in pipeline(brands):
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
    task = asyncio.create_task(execute_run(run_id, brands))
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
}


@app.get("/")
async def home():
    return FileResponse(os.path.join(HERE, "index.html"))


@app.get("/{filename}")
async def public_file(filename: str):
    media_type = PUBLIC_FILES.get(filename)
    path = os.path.join(HERE, filename)
    if media_type is None or not os.path.isfile(path):
        return JSONResponse({"error": "Not found."}, status_code=404)
    return FileResponse(path, media_type=media_type)
