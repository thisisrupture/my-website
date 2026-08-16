# Sameness Index — pick up here

Paste this whole file into a new chat. It is written to be read cold.

---

## What you are working on

The **Sameness Index**: a free, public lead-generation tool for Rupture. It reads
the public websites of competing branded prescription medicines, strips the
regulatory content and everything the label determines, and measures how much of
the remaining messaging the category shares. It names the messaging territories
in play, who uses each, and which nobody has taken.

The reader is a brand or marketing lead at a pharma company. The result is
something they may forward to their boss. Every number must be one click from
the evidence that produced it — that is the tool's entire claim to credibility.

**Live at** `https://rupture-tools.onrender.com`. Results are permanent at
`/r/<id>`.

## Where everything is

| Thing | Where |
|---|---|
| Code | `my-website/tools/sameness-index/` in the `thisisrupture/my-website` repo |
| Repo on disk | `~/Library/CloudStorage/GoogleDrive-.../My Drive/Rupture/Rupture Assets/my-website` |
| Hosting | Render service `rupture-tools`, blueprint is `render.yaml`, **Standard** instance (2GB) |
| Database | Supabase project **Rupture Tools**, ref `upflzhglbfkslwysopll`, eu-west-2 |
| Site design system | `my-website/public/styles/tokens.css`, `src/layouts/Base.astro`, `src/components/Header.astro` — read these before touching any styling |

Files that matter: `server.py` (the whole pipeline and API), `drugs.py` (openFDA),
`store.py` (persistence), `index.html` (the entire front end, one file, no build
step), `test_jobs.py`, `migrations/`, `generate_worked_example.py` +
`worked_example.json` + `embed_example.py` (the demo, embedded into index.html).

## The state of play

**Done and pushed:** the two-act report; the landing page rebuilt on the site's
design system; the convergence score; imagery as a second inventory of
territories; gate-busting crawl; image discovery; honest highlight links;
openFDA finder with a brand directory; type-ahead on brand and therapy area;
**a real browser for the sites that need one** (`browser.py`, the `Dockerfile`,
and the escalation rule `needs_browser()` in `server.py`).

**Outstanding for the user, not the assistant:**
- Run `migrations/0002_brand_sites.sql` in Supabase (SQL Editor, paste, run).
  Without it the finder works but re-discovers every address every run.
- Confirm the font route serves:
  `curl -s -o /dev/null -w "%{http_code} %{content_type}\n" https://rupture-tools.onrender.com/fonts/Fraunces_72pt_Soft-Black.ttf`
  Wanted: `200 font/ttf`.

**Agreed and not started — this is the next piece of work:**

1. **Screenshots as evidence.** While the page is open, capture the quoted
   sentence highlighted in place and the hero imagery. This kills three problems
   at once: no URL-hunting for lazy-loaded images, no text fragment that
   silently fails, no gate destroying the link. The report then *shows* the
   claim on a competitor's own site on a given date rather than linking to it.
   The user is keen on this specifically.
2. **A global daily run cap.** Offered and not yet built. `SAMENESS_RUNS_PER_IP`
   is bypassable and there is no global ceiling, so the Anthropic bill is
   currently unbounded. Render has **no spend limit feature** (confirmed with
   their staff), so the protection has to be in the app plus a cap in the
   Anthropic Console.

Also noted for later: a custom domain (`sameness.thisisrupture.com`) instead of
the Render subdomain; and the user's eventual production flow is *start the
report → live commentary with teasers → email capture → send the link and a
sales email*.

## Decisions already made — do not relitigate

- **Report structure is two acts.** Act one proves the sameness (score, three
  counts that are each a finding, the crowded map, one chart). Act two locates
  the daylight (five territories, big, with their evidence). Everything else is
  working, collapsed. Organised by the argument, not by the method.
- **One chart, not three.** Difference/overlap/standing-out were three pictures
  of one fact. Only the scatter survives on the page.
- **Five daylight territories, not twenty-five.** Nobody acts on twenty-five.
- **Imagery is one finding at the top, not a parallel inventory.** "You sound 88
  alike and look 69 alike" stays; the visual map lives in the working.
- **Design follows thisisrupture.com exactly.** Coral is `#FE1849` (the real
  token — `DESIGN-BRIEF.md` is out of date). Fraunces **72pt Soft** is bundled in
  `fonts/` and served through the `PUBLIC_FILES` allowlist; Google Fonts serves
  the standard 72pt, which is a visibly different face at display size.
- **Market coverage is US only for now.** openFDA is the FDA's register. A
  European-only brand gets no lookup and the tool says so rather than pretending.
- **The model may narrow, never invent.** Competitors come from openFDA; the
  model shortlists them and anything it returns that was not on the list is
  discarded.

## Traps that have already cost time

- **`visible_text()` used to eat the page.** It decomposed the script tags out
  of the soup it was handed, so any caller that asked `embedded_prose()`
  afterwards — which is exactly the order the crawl asks in — got nothing.
  The rescue for a page whose copy sits in a JSON blob had never once fired in
  production; `json_pages` could only ever be zero. Fixed by making the read
  non-destructive. The general lesson: a function named for reading must not
  modify what it reads, and a counter that is always zero is a bug, not a
  quiet category.

- **This sandbox has no raw outbound network.** `curl` fails; `WebFetch` works
  through a proxy. You cannot run the crawler against real pharma sites. Build
  against fixtures, say so plainly, and treat the user's first live run as the
  test. Do not claim something works when you have only tested a fixture.
- **Python `round()` breaks ties to even; JavaScript `Math.round()` rounds half
  up.** A score landing on .5 disagreed with the page that recalculated it.
  Everything goes through `r0()` in `server.py` and `generate_worked_example.py`.
- **Visual territory ids are namespaced with a leading V** (`V01`, `VX01`,
  `VH01`). The model is asked for X/H ids for provenance discipline, but those
  collide with the messaging inventory and a finding then links to the wrong
  territory.
- **A brand that yields no messaging scores as perfectly distinctive.** A
  corporate or region page is full of words and carries no messaging; that brand
  shares nothing, and sharing nothing looks like distinctiveness. Run
  `nf3dh557r83h` published "0 — distinct" because of it. Guards: `MIN_ELECTIVES`,
  `convergence()` excluding empty brands, the run failing below two coded
  brands, and the headline being discarded if it does not contain the computed
  score. Symptom to watch for: a suspiciously low score banded "distinct".
- **A text fragment must be an exact substring of the rendered page.** The fix
  is not to refuse to highlight — it is to build the fragment from the *page's
  own wording* found by fuzzy match, never from the model's paraphrase.
- **Panels share edges.** A global `section { margin: 76px 0 }` opens gaps
  between report panels; both screens override it.
- **`.git/index.lock`** gets left behind by assistant git calls through the
  bridge. `rm -f .git/index.lock` before committing, every time.

## How to work

- The user commits and pushes; the assistant writes files into the repo via the
  device bridge and then hands over an exact `git add`/`commit`/`push` block.
  Never push.
- Render auto-deploys `main`. Cloudflare Pages builds the Astro site from the
  same repo and ignores this folder.
- Run `python3 -m pytest test_jobs.py -q` before handing anything over. 34 tests
  at time of writing; add one for every bug fixed — several exist specifically
  because a bug shipped once.
- Verify the front end by rendering it headless and *looking at the screenshot*,
  not by assuming. Playwright and Chromium are available in the sandbox.
- The user is direct and pushes back well. When he says a fix is not addressing
  the real problem, he has usually been right — check whether you are solving a
  symptom before defending the work.

## Voice

Sentence case. Editorial, not SaaS. The unit is a **messaging territory**. No
spatial metaphor beyond that word — never "ground", "space", "white space",
"own", "stand on". Never "disruption", "transformation" or "innovation". No
internal method words reach the reader: no "layer 2", "elective", "occupancy".
Qualifiers live behind a click; the headline leads with the sameness and the
opportunity comes second.

---

## The browser, in one paragraph

`browser.py` holds one shared Chromium, started on the first page that needs it
and never at import. Pages come from a bounded pool (`SAMENESS_BROWSER_PAGES`,
two) so the box is never holding more tabs than 2GB allows, and each render
gets its own context so one site's consent state never leaks into the next.
A page reaches it only when `needs_browser()` says so: the site would not talk
to us (403, 429, 5xx, no connection at all) or it talked and said nothing
(under `SAMENESS_BROWSER_THIN` readable characters, counted *after* the page
data has been looked in, so a JSON-blob site stays free). Everything fails
soft — no Chromium, a crash, a hung page all come back as `None` and the crawl
keeps whatever plain HTTP gave it. `SAMENESS_BROWSER=off` turns it off
entirely. `/api/health` reports whether it is there and why not.

**Not yet tested against a real site.** The sandbox has no outbound network, so
this is proved against fixtures and seven tests, and the first live run is the
test.

**Start by** reading `server.py`'s module docstring and `index.html`'s structure,
then say what you understand the state to be before changing anything.
