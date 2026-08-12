# The Sameness Index

A brand team enters their own brand and their competitors. The tool reads each brand's public website, removes the regulatory content and everything the molecule and its label determine, and compares what is left — the messaging and positioning each brand chose.

It answers one question: how differentiated is this category's messaging, and which positions are still available.

## A note on language

The report is written for a brand or marketing lead. It uses the standard vocabulary of commercial communications — messaging, positioning, claims, audience, message hierarchy, substantiation, art direction — and avoids spatial metaphor ("ground", "space", "territory", "standing on") and internal method vocabulary ("layer 2", "elective", "occupancy"). Those terms still exist in the code as variable names, and in `methodology.md` as the specification, but they do not reach the reader. The prompt in `server.py` enforces the same rule on live runs, so generated findings match the worked example's register.

## Running it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn server:app --reload
```

Then open http://127.0.0.1:8000.

To put it online, see `DEPLOY.md`.

## How a run works

A run takes two to five minutes — longer than a browser will hold a request
open, and longer than most hosts allow one to last. So the request that starts
a run does not wait for it.

`POST /api/run` validates the brands, writes a row, starts the analysis in the
background and returns an id straight away. The analysis writes each line of
its narration down as it happens, and its result when it has one.
`GET /api/run/{id}?since=n` returns everything said since line `n`, and the
result once there is one. The page asks every two seconds.

Two things follow from that, and both matter more than the plumbing.

**A run survives the browser.** Reload the page, lose the connection, close the
laptop — the work carries on and the page picks the narration back up.

**Every result has an address.** The id goes into the URL the moment the run
starts, so `/r/<id>` is a permanent, shareable link to the result, with no login
to view. That is the distribution mechanism: a brand lead pastes it into a
Teams channel and it spreads inside the account without anyone's help.

Runs are stored in Postgres when `DATABASE_URL` is set, and in memory when it
is not — so local development needs no database, at the cost of permalinks
lasting only until the server restarts.

Because each run costs real money in crawling and model calls, the service caps
runs at five per IP address per day and three at a time. Both are environment
variables.

The worked example needs no key, no server and no network. Double-click `index.html` and click the worked-example link at the bottom of the input screen — the data is embedded in the page.

Running the index against live sites does need the server above, because the browser cannot crawl other people's domains itself.

If you regenerate the worked example, re-embed it:

```bash
python3 generate_worked_example.py && python3 embed_example.py
```

## What is here

| File | What it does |
|---|---|
| `index.html` | The whole front end. Three screens, no dashboard, no build step. |
| `server.py` | The analysis engine, the job endpoints and the static host. Crawls, strips, separates, codes, tiers, scores, writes the findings. |
| `store.py` | Run persistence. Postgres when `DATABASE_URL` is set, memory when it is not. |
| `migrations/0001_runs.sql` | The `runs` table, as applied to the Rupture Tools Supabase project. |
| `test_jobs.py` | Checks the job infrastructure with the analysis stubbed out. No network, no model calls. |
| `render.yaml`, `DEPLOY.md` | Hosting. |
| `methodology.md` | The three layers and the boundary rules. The specification. |
| `sources.md` | The external sources behind the exogenous concept layer. |
| `concepts.py`, `corpus.py`, `score.py` | The original prototype, and the worked example's coded corpus. |
| `generate_worked_example.py` | Builds `worked_example.json` from the prototype, adding availability ratings, reader-facing position names, descriptions, findings and the copy-versus-imagery comparison. |
| `embed_example.py` | Embeds the worked example into `index.html` so it opens without a server. |
| `worked_example.json` | US non-steroidal topical atopic dermatitis, captured 12 August 2026. |

## The pipeline

1. **Read** — fetches the landing page plus up to five same-domain pages, prioritising the ones that carry positioning.
2. **Strip the mandated layer** — safety text, indication statements, disclaimers, copay terms. Not scored. This matters more than it sounds: a brand carrying a class boxed warning has ten times the mandated text of one that does not, and would otherwise score as wildly differentiated on the basis of FDA labelling.
3. **Separate the molecule-determined layer** — mechanism, age floor, dosing, trial data, product form. Retained, reported as context, excluded from the score. Convergence here is chemistry, not strategy.
4. **Build the opportunity space** — positions observed in the category, *plus* positions established from the patient burden and clinical barrier literature independently of what these brands say. The second source is not optional: a concept list derived only from the corpus has a claimant for every position by construction, so empty ground could never appear. That was a real failure in the prototype.
5. **Code** — every brand against every position, at concept level. Wording is irrelevant; the positioning move is the unit. Lexical and embedding similarity were tried and failed — at four brands with short hero copy, word-overlap cannot see that "reimagine relief", "the touch of calm skin" and "safe on skin" are the same move. Every code carries the verbatim fragment that triggered it.
6. **Tier** — every position gets open / frame only / constrained / closed, with its reasoning shown. A strategist's read requiring MLR review, not legal advice.
7. **Score the heroes** — commissioned imagery only, on plain-English dimensions. Clinical photography, mechanism diagrams and pack shots are excluded.
8. **Compute** — occupancy, crowding, open-and-empty, per-brand ownership. Deterministic Python, ported from `score.py`. The model never computes a number.

## The validity check

Before trusting a new category, run a two-brand control. If a two-brand category returns comparable convergence, the molecule-layer stripping has failed and the tool is measuring therapy-area vocabulary rather than strategic choice.

Run against the worked example, the gate passes clearly:

| Set | Occupancy | Crowding |
|---|---|---|
| All four brands | 55% | **73%** |
| Zoryve + Vtama | 50% | 40% |
| Zoryve + Eucrisa | 45% | 33% |
| Opzelura + Eucrisa | 38% | 27% |

Two-brand crowding runs at 27–40% against the four-brand 73%. The convergence is coming from the number of brands agreeing, not from shared category vocabulary.

## Design notes

Editorial, not SaaS — a document with interactive parts. Serif for reading, sans for data. One accent per brand. The map is the only chart, deliberately. Everything beyond the core read sits under a single collapsed **Show the full working**.

Nothing in the tool asserts anything the user cannot immediately verify. Every number is one click from the sentence on a competitor's website that produced it. A score can be argued with. A rival's own homepage copy cannot.

## Out of scope, on purpose

No accounts, no billing, no saved projects, no export, no comparison over time, no PDF. A run is stored so it has an address and can be passed around; that is not the same as a project the user owns and returns to. If a client wants to run it repeatedly, that is an engagement, not a subscription. Add nothing until the core read is trusted.

## Known limits of the live path

- Sites that render entirely in JavaScript will return too little text and the run will stop with a message saying so, rather than scoring a shell.
- The crawl reads up to six pages per brand. Deep sites are sampled, not exhausted.
- Hero images are taken from the landing page's `og:image` and first image tags. Where none is retrievable for at least two brands, the visual layer is reported as not captured rather than guessed.
- Layer separation and concept coding are model-assisted judgements against the published rules. They carry their evidence so they can be argued with — which is the point.
