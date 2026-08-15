# Starting prompt — Sameness Index, report design

Paste everything below into a new chat.

---

I want to work on the design and layout of one page: the report the Sameness
Index produces. Not the code, not the analysis, not the deployment. Just how
the result is arranged on screen and how it reads.

**Work in HTML artifacts in this chat.** Build the layouts as self-contained
HTML I can look at and react to. Do not touch the repository until I have
agreed a direction — no file edits, no commits, no deployment. When we have
something I like, we will move it into the real page as a separate job.

## What the tool is

The Sameness Index reads the public websites of competing branded prescription
medicines, strips out the regulatory content and everything the label
determines, and measures how much of the remaining messaging the category
shares. It names the messaging territories in play, who uses each one, and
which are used by nobody.

It is live at `rupture-tools.onrender.com`, running from
`my-website/tools/sameness-index/` in the `thisisrupture/my-website` repo.
The whole front end is one file, `index.html` — no framework, no build step.
Finished results live at `/r/<id>` permanently, and get shared.

It is a lead-generation tool for Rupture, a strategy consultancy. The reader is
a brand or marketing lead at a pharma company. The result is something they may
forward to their boss.

## What the report currently contains, in order

1. Category, market, capture date
2. A note naming any brand whose site could not be read, if there was one
3. The headline — three plain sentences of the finding
4. "What does this mean?" and "Copy the link to this result"
5. A **See the breakdown** button
6. The breakdown: territory map in the centre; four numbers and a
   convergence picture in a narrower column beside it
7. What the analysis found — 3 to 5 findings, each linking to its evidence
8. Where the unused territories come from — collapsed, lists every territory
   established from published literature with its evidence basis
9. Territories to explore — the unused ones, with an availability rating
10. "Show the full working" — collapsed: per-brand departures, provenance,
    every territory, brand-by-brand, pairwise similarity, imagery, copy versus
    imagery, how copy was separated, limitations

Clicking almost anything opens a right-hand drawer with the detail: a
territory's drawer shows the verbatim wording from each brand's site, with a
link that opens that page and highlights the sentence.

## What is settled and must not be undone

Each of these cost a round of iteration.

**Palette** — paper `#EFEEEA`, ink `#303030`, green `#1F5B4A`, mint `#51D4B2`,
coral `#FF686B`, label `#727270`, divider `#D7D6D2`, hairline `#ABAAA8`. Mint is
a highlight only; it fails contrast as an accent at label sizes.

**Type** — Fraunces (900 for headings), Epilogue (interface), JetBrains Mono
(labels and figures). Sentence case throughout.

**Register** — editorial, not SaaS. A document with interactive parts, not a
dashboard of widgets. No pull quotes, no motivational callouts, no card
shadows, no gradient fills beyond the one already in the convergence plot.

**Vocabulary** — the unit is a *messaging territory*. Standard commercial
communications language: messaging, positioning, claims, audience, message
hierarchy, substantiation, art direction. No spatial metaphor beyond
"territory" itself — never "ground", "space", "white space", "own", "stand on".
Never "disruption", "transformation" or "innovation". No internal method words
reach the reader: no "layer 2", "elective", "occupancy", "mandated".

**Every number is one click from its evidence.** Nothing appears that cannot be
traced to the wording on a brand's website that produced it. This is the tool's
entire claim to credibility. Do not add a figure that cannot be traced.

**Qualifiers live behind a click**, never in the body. The headline leads with
the sameness; the opportunity comes second.

## What is open

Everything about arrangement, hierarchy, density and pacing. Specifically worth
questioning:

- Whether summary-then-breakdown is the right split, and whether the button
  earns its place
- Whether the territory map deserves to be the centre, and whether its current
  grid of cells is the best form for it
- What the four numbers are for, and whether four is the right number
- Whether the findings should sit above or below the breakdown
- How the collapsed sections are signalled — two `<details>` blocks currently
  do a lot of quiet work and may be missed entirely
- What this looks like on a phone, which is where a forwarded link often opens
- What someone sees in the first three seconds, having been sent the link with
  no context

## Two shapes, not one

With two brands the report draws two overlapping circles, sized by how many
territories each brand uses, overlapping in proportion to what they share. With
three or more it draws a two-axis plot of messaging against imagery. Any layout
has to work for both.

## Real numbers to design against

From a real four-brand run:

- 41 territories in the category; 22 used by at least one brand; 19 by none
- 7 used by more than one brand — 32% of everything in use
- 6 unused territories need no new clinical evidence
- 20 of the 41 came from published literature rather than the brands' sites;
  18 of those 20 are used by nobody
- Headline: *"32% of the messaging in this category is shared. Of 41 messaging
  territories, 7 are used by both brands, 15 by only one, and 19 by neither.
  18 of those unused territories come from published evidence on what patients
  and clinicians say is missing, rather than from anything these brands
  publish."*

Findings read like: *"The two brands agree most on clinical differentiation:
disease severity framing, immune-mechanism education, the 'targets the source'
claim... This is where the category sounds identical."*

A territory looks like: id `C05`, label *"Targets the source" mechanism-based
differentiation*, availability *Needs substantiation*, used by 2 of 4, with a
verbatim quote per brand.

Availability ratings read: **Explore now / Raise, not claim / Needs
substantiation / Not viable**.

## How I want to work

Start by telling me what you think is wrong with the current arrangement before
you draw anything. Then show me two or three genuinely different directions as
HTML artifacts rather than one polished answer — I would rather choose between
approaches than react to a single proposal. Use the real numbers above so I am
judging something that looks like the actual report.

Be direct about trade-offs. If something I ask for would weaken the credibility
of the report or bury the evidence trail, say so before building it.
