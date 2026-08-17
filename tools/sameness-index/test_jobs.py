"""
Job infrastructure check. Replaces the pipeline with a stub, so this exercises
starting a run, polling it, storing the result, serving the permalink and
failing cleanly — without crawling anything or spending anything on the model.

    pip install pytest httpx
    python3 -m pytest test_jobs.py -q

Run it against Postgres too before deploying, by setting DATABASE_URL first.
The in-memory path and the Postgres path are the same interface, but only one
of them is what production uses.
"""

import asyncio
import json

import httpx
import pytest

import server

STUB_RESULT = {
    "meta": {"category": "a test category", "brands": [{"name": "A"}, {"name": "B"}]},
    "metrics": {"crowding_rate": 0.73, "occupancy_rate": 0.55, "space_size": 40,
                "contested": 16, "open_empty": 12},
    "headline": "73% of what these brands say, they say together.",
}


async def fake_pipeline(brands, category="", run_id=""):
    yield {"type": "progress", "text": "Reading the first site."}
    await asyncio.sleep(0.05)
    yield {"type": "progress", "text": "Reading the second site."}
    await asyncio.sleep(0.05)
    yield {"type": "result", "data": STUB_RESULT}


async def failing_pipeline(brands, category="", run_id=""):
    yield {"type": "progress", "text": "Reading the first site."}
    yield {"type": "error", "text": "Could not read enough of that site."}


async def exploding_pipeline(brands, category="", run_id=""):
    yield {"type": "progress", "text": "Starting."}
    raise RuntimeError("something unforeseen")


BRANDS = [{"name": "A", "url": "https://a.example"}, {"name": "B", "url": "https://b.example"}]


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(server, "store", server.Store(dsn=""))
    await server.store.start()
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def drain(c, run_id, tries=100):
    """Poll the way the page does, and return the final state."""
    seen = 0
    lines = []
    for _ in range(tries):
        r = await c.get(f"/api/run/{run_id}", params={"since": seen})
        s = r.json()
        lines += [p["text"] for p in s["progress"]]
        seen = s["progress_total"]
        if s["status"] != "running":
            s["all_progress"] = lines
            return s
        await asyncio.sleep(0.02)
    raise AssertionError("run never finished")


@pytest.mark.anyio
async def test_start_returns_immediately_and_completes(client, monkeypatch):
    monkeypatch.setattr(server, "pipeline", fake_pipeline)
    r = await client.post("/api/run", json={"brands": BRANDS})
    assert r.status_code == 200
    body = r.json()
    assert len(body["id"]) == 12
    assert body["url"] == f"/r/{body['id']}"

    state = await drain(client, body["id"])
    assert state["status"] == "complete"
    assert state["result"]["metrics"]["crowding_rate"] == 0.73
    # the narration arrives in order and is not repeated across polls
    assert state["all_progress"] == ["Reading the first site.", "Reading the second site."]


@pytest.mark.anyio
async def test_result_survives_and_is_replayable(client, monkeypatch):
    """A permalink opened later gets the whole run, not just what is new."""
    monkeypatch.setattr(server, "pipeline", fake_pipeline)
    run_id = (await client.post("/api/run", json={"brands": BRANDS})).json()["id"]
    await drain(client, run_id)

    again = (await client.get(f"/api/run/{run_id}")).json()
    assert again["status"] == "complete"
    assert again["progress_total"] == 2
    assert again["result"] == STUB_RESULT

    page = await client.get(f"/r/{run_id}")
    assert page.status_code == 200
    assert "screen-result" in page.text


@pytest.mark.anyio
async def test_pipeline_error_is_reported(client, monkeypatch):
    monkeypatch.setattr(server, "pipeline", failing_pipeline)
    run_id = (await client.post("/api/run", json={"brands": BRANDS})).json()["id"]
    state = await drain(client, run_id)
    assert state["status"] == "failed"
    assert "Could not read enough" in state["error"]


@pytest.mark.anyio
async def test_unexpected_exception_is_reported(client, monkeypatch):
    """A crash mid-run must leave a failed run, not a run that polls forever."""
    monkeypatch.setattr(server, "pipeline", exploding_pipeline)
    run_id = (await client.post("/api/run", json={"brands": BRANDS})).json()["id"]
    state = await drain(client, run_id)
    assert state["status"] == "failed"
    assert "something unforeseen" in state["error"]


@pytest.mark.anyio
async def test_unknown_run_is_404(client):
    r = await client.get("/api/run/zzzzzzzzzzzz")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_input_validation(client, monkeypatch):
    monkeypatch.setattr(server, "pipeline", fake_pipeline)
    r = await client.post("/api/run", json={"brands": [BRANDS[0]]})
    assert r.status_code == 400
    r = await client.post("/api/run", json={"brands": [{"name": "A", "url": ""}, BRANDS[1]]})
    assert r.status_code == 400
    r = await client.post("/api/run", json={"brands": BRANDS * 4})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_daily_cap_per_address(client, monkeypatch):
    monkeypatch.setattr(server, "pipeline", fake_pipeline)
    monkeypatch.setattr(server, "MAX_RUNS_PER_IP_PER_DAY", 2)
    head = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
    for _ in range(2):
        r = await client.post("/api/run", json={"brands": BRANDS}, headers=head)
        assert r.status_code == 200
        await drain(client, r.json()["id"])
    r = await client.post("/api/run", json={"brands": BRANDS}, headers=head)
    assert r.status_code == 429
    # a different address is unaffected
    r = await client.post("/api/run", json={"brands": BRANDS},
                          headers={"x-forwarded-for": "198.51.100.4"})
    assert r.status_code == 200


@pytest.mark.anyio
async def test_stale_run_is_failed_on_read(client, monkeypatch):
    """A deploy landing mid-run must not leave the page polling forever."""
    import store as store_mod
    monkeypatch.setattr(store_mod, "STALE_AFTER_SECONDS", 0)

    async def hanging_pipeline(brands, category="", run_id=""):
        yield {"type": "progress", "text": "Working."}
        await asyncio.sleep(60)

    monkeypatch.setattr(server, "pipeline", hanging_pipeline)
    run_id = (await client.post("/api/run", json={"brands": BRANDS})).json()["id"]
    await asyncio.sleep(0.05)
    state = (await client.get(f"/api/run/{run_id}")).json()
    assert state["status"] == "failed"
    assert "stopped before it finished" in state["error"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_category_is_passed_through(client, monkeypatch):
    """A category typed on the form must reach the pipeline. Without it, the
    territory list is built from one brand's guess and everything is measured
    against that."""
    seen = {}

    async def capture(brands, category="", run_id=""):
        seen["category"] = category
        yield {"type": "result", "data": STUB_RESULT}

    monkeypatch.setattr(server, "pipeline", capture)
    r = await client.post("/api/run", json={"brands": BRANDS, "category": "type 2 diabetes, adults, US"})
    await drain(client, r.json()["id"])
    assert seen["category"] == "type 2 diabetes, adults, US"

    await client.post("/api/run", json={"brands": BRANDS})
    await asyncio.sleep(0.05)
    assert seen["category"] == ""


class _NoHTTP:
    """The pipeline opens an httpx client; these tests stub crawling entirely,
    and the sandbox's proxy environment makes a real client fail to construct."""
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def close(self): return None


@pytest.mark.anyio
async def test_unreadable_competitor_does_not_kill_the_run(monkeypatch):
    """One site behind bot protection must not throw away the whole run —
    but the result has to say the brand is missing."""
    import server as s
    async def crawl(fetcher, brand, hint=None):
        if brand["name"] == "Blocked":
            return "", [], 0, "", {}              # nothing readable came back
        return "[PAGE https://x.test/]\n" + ("copy about the category. " * 60), [], 1, "", {}
    monkeypatch.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())
    monkeypatch.setattr(s, "crawl_brand", crawl)
    monkeypatch.setattr(s, "stage_layers", lambda b, c: _layers())
    monkeypatch.setattr(s, "stage_space", lambda cat, e: _space())
    monkeypatch.setattr(s, "stage_code", lambda b, f, p: _code())
    monkeypatch.setattr(s, "stage_findings", lambda *a: _findings())

    brands = [{"name": "Mine", "url": "https://a.test"},
              {"name": "Blocked", "url": "https://b.test"},
              {"name": "Other", "url": "https://c.test"}]
    result, notes = None, []
    async for e in s.pipeline(brands):
        if e["type"] == "result": result = e["data"]
        if e["type"] == "progress": notes.append(e["text"])
        if e["type"] == "error": raise AssertionError("run aborted: " + e["text"])

    assert result is not None, "run produced no result"
    assert [b["name"] for b in result["meta"]["brands"]] == ["Mine", "Other"]
    assert result["meta"]["unreadable"] == [{"name": "Blocked", "url": "https://b.test"}]
    assert any("could not be read" in n for n in notes)
    assert any("Blocked" in x for x in result["limitations"])


@pytest.mark.anyio
async def test_own_brand_unreadable_stops_the_run(monkeypatch):
    import server as s
    async def crawl(fetcher, brand, hint=None):
        return ("", [], 0, "", {}) if brand["name"] == "Mine" else ("[PAGE https://x/]\n" + "copy. " * 200, [], 1, "", {})
    monkeypatch.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())
    monkeypatch.setattr(s, "crawl_brand", crawl)
    errs = [e async for e in s.pipeline([{"name": "Mine", "url": "https://a.test"},
                                         {"name": "Other", "url": "https://c.test"}])
            if e["type"] == "error"]
    assert errs and "built around your own brand" in errs[0]["text"]


# Enough elective fragments to clear MIN_ELECTIVES — a brand below that
# threshold is treated as unread, which _thin_layers exercises separately.
async def _layers(): return {"category_guess": "test category", "mandated_word_estimate": 10,
                             "molecule": ["m"], "elective": ["an elective fragment"] + [f"fragment {i}" for i in range(6)]}
async def _thin_layers(): return {"category_guess": "test category", "mandated_word_estimate": 10,
                                  "molecule": ["m"], "elective": []}
async def _space(): return [{"id": "C01", "label": "L", "description": "D", "source": "Observed in category.",
                             "tier": "open", "tier_reasoning": "R"},
                            {"id": "X01", "label": "L2", "description": "D2", "source": "Burden literature.",
                             "tier": "open", "tier_reasoning": "R2"}]
async def _code(): return {"C01": "an elective fragment"}
async def _findings(): return {"headline": "", "findings": [], "brand_comments": {}}


@pytest.mark.anyio
async def test_find_only_offers_addresses_that_actually_answered(client, monkeypatch):
    """The model proposes; the server verifies. An address that does not
    respond, or responds with nothing, must never reach the user."""
    import server as s

    async def proposal(brand, hint):
        return {"category": "type 2 diabetes, adults, US", "brands": [
            {"name": "Ozempic", "company": "Novo Nordisk",
             "candidates": ["https://www.ozempic.com/", "https://invented.example/", "https://www.ozempicpro.com/"]},
            {"name": "Mounjaro", "company": "Eli Lilly", "candidates": ["https://mounjaro.lilly.com/"]},
        ]}

    async def check(http, url, sem):
        if "invented" in url:
            return None                                   # does not resolve
        if "mounjaro" in url:
            return {"url": url, "title": "", "readable": False, "chars": 0,
                    "status": 403, "audience": "patient"}  # bot-protected
        return {"url": url, "title": "Ozempic", "readable": True, "chars": 9000,
                "status": 200, "audience": "hcp" if "pro" in url else "patient"}

    monkeypatch.setattr(s, "stage_find", proposal)
    monkeypatch.setattr(s, "check_site", check)
    monkeypatch.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())

    r = await client.post("/api/find", json={"brand": "Ozempic"})
    body = r.json()
    assert body["category"] == "type 2 diabetes, adults, US"

    oz, mj = body["brands"]
    urls = [x["url"] for x in oz["sites"]]
    assert "https://invented.example/" not in urls, "an unverified address reached the user"
    assert oz["any_readable"] is True
    assert oz["sites"][0]["audience"] == "patient", "readable patient site should be offered first"
    assert mj["any_readable"] is False, "a bot-protected site must be flagged, not hidden"


@pytest.mark.anyio
async def test_find_needs_a_brand_name(client):
    assert (await client.post("/api/find", json={"brand": "x"})).status_code == 400


@pytest.mark.anyio
async def test_robots_is_honoured_and_named_as_such(monkeypatch):
    """A site that asks not to be read is left alone, and the report says that
    is why — not that the site was unreadable."""
    import server as s

    async def crawl(fetcher, brand, hint=None):
        if brand["name"] == "Private":
            return "", [], 0, "robots", {}
        return "[PAGE https://x.test/]\n" + ("copy about the category. " * 60), [], 1, "", {}

    monkeypatch.setattr(s, "crawl_brand", crawl)
    monkeypatch.setattr(s, "stage_layers", lambda b, c: _layers())
    monkeypatch.setattr(s, "stage_space", lambda cat, e: _space())
    monkeypatch.setattr(s, "stage_code", lambda b, f, p: _code())
    monkeypatch.setattr(s, "stage_findings", lambda *a: _findings())
    monkeypatch.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())
    monkeypatch.setattr(s, "Fetcher", lambda http: _NoHTTP())

    brands = [{"name": "Mine", "url": "https://a.test"},
              {"name": "Private", "url": "https://b.test"},
              {"name": "Other", "url": "https://c.test"}]
    result, notes = None, []
    async for e in s.pipeline(brands):
        if e["type"] == "result": result = e["data"]
        if e["type"] == "progress": notes.append(e["text"])

    assert result is not None
    assert result["meta"]["unreadable"] == [
        {"name": "Private", "url": "https://b.test", "reason": "asked not to be read"}]
    assert any("asks automated readers not to read it" in n for n in notes)


def test_robots_parsing_matches_the_real_lilly_files():
    """The two files that prompted this, verbatim. Both permit the pages the
    index reads; Mounjaro withholds only its drafts."""
    from urllib.robotparser import RobotFileParser

    mounjaro = RobotFileParser()
    mounjaro.parse("""User-agent: *
Disallow: /drafts/
Disallow: /eds/
Disallow: /es/drafts/
Disallow: /es/eds/

Sitemap: https://mounjaro.lilly.com/sitemap.xml""".splitlines())
    assert mounjaro.can_fetch("*", "https://mounjaro.lilly.com/")
    assert mounjaro.can_fetch("*", "https://mounjaro.lilly.com/how-to-take-mounjaro")
    assert not mounjaro.can_fetch("*", "https://mounjaro.lilly.com/drafts/x")

    trulicity = RobotFileParser()
    trulicity.parse("""User-agent: *
Disallow:

Sitemap: https://trulicity.lilly.com/sitemap.xml""".splitlines())
    assert trulicity.can_fetch("*", "https://trulicity.lilly.com/what-is-trulicity")

    silent = RobotFileParser()
    silent.parse([])                      # no robots.txt at all
    assert silent.can_fetch("*", "https://anything.example/page")

    closed = RobotFileParser()
    closed.parse(["User-agent: *", "Disallow: /"])
    assert not closed.can_fetch("*", "https://anything.example/page")


@pytest.mark.anyio
async def test_a_brand_with_no_messaging_leaves_the_figures(monkeypatch):
    """The failure that published a wrong number.

    A corporate or regional page can be fetched, be full of words, and carry no
    brand messaging at all. That brand then shares nothing with anybody, and
    sharing nothing scores as perfect distinctiveness — so a half-read category
    came back as "distinct" with a confident zero on the front of it. The brand
    has to leave the figures and be named, exactly as an unreachable site is.
    """
    import server as s

    async def crawl(fetcher, brand, hint=None):
        return "[PAGE https://x.test/]\n" + ("words on a page. " * 60), [], 1, "", {}

    async def layers(b, c):
        return await (_thin_layers() if b == "Empty" else _layers())

    monkeypatch.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())
    monkeypatch.setattr(s, "Fetcher", lambda http: _NoHTTP())
    monkeypatch.setattr(s, "crawl_brand", crawl)
    monkeypatch.setattr(s, "stage_layers", layers)
    monkeypatch.setattr(s, "stage_space", lambda cat, e: _space())
    monkeypatch.setattr(s, "stage_code", lambda b, f, p: _code())
    monkeypatch.setattr(s, "stage_findings", lambda *a: _findings())

    brands = [{"name": "Mine", "url": "https://a.test"},
              {"name": "Empty", "url": "https://b.test"},
              {"name": "Other", "url": "https://c.test"}]
    result, notes = None, []
    async for e in s.pipeline(brands):
        if e["type"] == "result": result = e["data"]
        if e["type"] == "progress": notes.append(e["text"])
        if e["type"] == "error": raise AssertionError("run aborted: " + e["text"])

    assert result is not None
    named = [u["name"] for u in result["meta"]["unreadable"]]
    assert named == ["Empty"], "the brand carrying no messaging must be named"
    assert any("carries no brand messaging" in n for n in notes)

    scored = [p["brand"] for p in result["convergence"]["messaging"]["per"]]
    assert "Empty" not in scored, "an unread brand must not be scored"
    assert set(scored) == {"Mine", "Other"}
    assert result["convergence"]["overall"] > 0, "two brands sharing a territory cannot score zero"


@pytest.mark.anyio
async def test_one_readable_brand_fails_the_run_rather_than_scoring_it(monkeypatch):
    """One brand is not a comparison, whatever the pages weighed."""
    import server as s

    async def crawl(fetcher, brand, hint=None):
        return "[PAGE https://x.test/]\n" + ("words on a page. " * 60), [], 1, "", {}

    async def layers(b, c):
        return await (_layers() if b == "Mine" else _thin_layers())

    monkeypatch.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())
    monkeypatch.setattr(s, "Fetcher", lambda http: _NoHTTP())
    monkeypatch.setattr(s, "crawl_brand", crawl)
    monkeypatch.setattr(s, "stage_layers", layers)
    monkeypatch.setattr(s, "stage_space", lambda cat, e: _space())
    monkeypatch.setattr(s, "stage_code", lambda b, f, p: _code())
    monkeypatch.setattr(s, "stage_findings", lambda *a: _findings())

    brands = [{"name": "Mine", "url": "https://a.test"},
              {"name": "Empty", "url": "https://b.test"}]
    result, error = None, None
    async for e in s.pipeline(brands):
        if e["type"] == "result": result = e["data"]
        if e["type"] == "error": error = e["text"]

    assert result is None, "a one-brand run must not publish a score"
    assert error and "one brand is not a comparison" in error


# ---------------------------------------------------------------------------
# Getting past the front door, finding the photography, and telling the truth
# about a highlight. All three failures observed in production on 15 Aug 2026.
# ---------------------------------------------------------------------------

GATE_HTML = """<html><body><h1>Are you a US healthcare professional?</h1>
<p>This site is intended for US healthcare professionals only. Please select.</p>
<a href="/hcp/home">I am a US healthcare professional</a>
<a href="https://elsewhere.example/">I am a patient — leave this site</a>
</body></html>"""


def test_a_gate_is_recognised_and_walked_through():
    """The Jardiance failure. A region or HCP gate is full of words and carries
    no messaging; read as a page it produces a brand with nothing to say, which
    then scores as perfectly distinctive."""
    import server as s
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(GATE_HTML, "html.parser")
    assert s.looks_like_a_gate(s.visible_text(soup), soup)
    # Same-site only: "leave this site" is the one link that must not be taken.
    assert s.gate_exit(soup, "https://brand.example/") == "https://brand.example/hcp/home"


def test_a_real_page_is_not_mistaken_for_a_gate():
    import server as s
    from bs4 import BeautifulSoup
    html = "<html><body>" + "<p>Real brand copy about the medicine and the patient. </p>" * 80 + "</body></html>"
    soup = BeautifulSoup(html, "html.parser")
    assert not s.looks_like_a_gate(s.visible_text(soup), soup)


def test_images_are_found_where_they_actually_hide():
    """A lazy-loaded site puts a placeholder in src and the real file in srcset
    or a data- attribute; heroes are often CSS backgrounds. Reading only
    img[src] collects placeholders and logos."""
    import server as s
    from bs4 import BeautifulSoup
    page = """<html><body>
    <meta property="og:image" content="/img/hero-og.jpg">
    <img src="data:image/gif;base64,R0lGOD" data-src="/img/lazy-hero.webp">
    <img src="/img/brand-logo.png">
    <picture><source srcset="/img/small.webp 400w, /img/big.webp 1600w"></picture>
    <div style="background-image:url('/img/background-hero.jpg')"></div>
    </body></html>"""
    found = s.image_candidates(BeautifulSoup(page, "html.parser"), "https://brand.example/x/")
    assert "https://brand.example/img/hero-og.jpg" in found
    assert "https://brand.example/img/lazy-hero.webp" in found, "a data-src image was missed"
    assert "https://brand.example/img/big.webp" in found, "srcset should yield the largest candidate"
    assert "https://brand.example/img/background-hero.jpg" in found, "a CSS background hero was missed"
    assert not any("logo" in u for u in found), "a logo is not art direction"


def test_photographs_are_judged_by_width_not_file_size():
    """A well-compressed WebP hero is smaller than a PNG logo, so a byte
    threshold discards the very thing it is meant to find."""
    import server as s
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + (1200).to_bytes(4, "big") + (800).to_bytes(4, "big")
    assert s.image_size(png) == (1200, 800)
    jpeg = (b"\xff\xd8\xff\xe0" + (16).to_bytes(2, "big") + b"J" * 14 +
            b"\xff\xc0" + (17).to_bytes(2, "big") + b"\x08" +
            (900).to_bytes(2, "big") + (1600).to_bytes(2, "big") + b"\x00" * 8)
    assert s.image_size(jpeg) == (1600, 900), "width and height are the other way round in JPEG"
    assert s.image_size(b"not an image at all") is None


def test_copy_built_in_the_browser_is_still_read():
    import server as s
    from bs4 import BeautifulSoup
    shell = """<html><body><nav>Home</nav>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"hero":"A once-daily treatment designed around the way people actually live with this condition.",
    "className":"hero--large","href":"https://x/y"}}
    </script></body></html>"""
    got = s.embedded_prose(BeautifulSoup(shell, "html.parser"))
    assert any("once-daily treatment" in t for t in got)
    assert not any("hero--large" in t for t in got), "class names are not copy"


def test_reading_a_page_does_not_destroy_it():
    """Shipped and dead: visible_text() decomposed the script tags out of the
    soup, so embedded_prose() called afterwards — which is the order the crawl
    calls them in — always found nothing. The rescue for a page built in the
    browser had never once fired in production."""
    import server as s
    from bs4 import BeautifulSoup
    shell = """<html><body><nav>Home</nav>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"hero":"A once-daily treatment designed around the way people actually live with this."}}
    </script></body></html>"""
    soup = BeautifulSoup(shell, "html.parser")
    s.visible_text(soup)
    assert any("once-daily" in t for t in s.embedded_prose(soup)), \
        "reading the page emptied it"
    assert s.visible_text(soup) == s.visible_text(soup), "twice must give the same answer"
    # And the words still are not the code.
    assert "props" not in s.visible_text(BeautifulSoup(shell, "html.parser"))


def test_a_long_quote_links_by_its_ends():
    """One long exact string fails on a single changed character. start,end
    finds the opening and closing words and highlights between them."""
    import server as s
    link = s.quote_link("https://x.example/p",
                        "Plaque psoriasis is driven by an overactive immune response, not by anything you did")
    assert "#:~:text=" in link and "," in link.split("#:~:text=")[1]
    short = s.quote_link("https://x.example/p", "targets the source")
    assert "," not in short.split("#:~:text=")[1], "a short quote needs no end anchor"


def test_a_tidied_quote_still_highlights_the_page_s_own_wording():
    """The correction to an over-correction.

    The browser cannot fuzzy-match — a fragment has to be an exact substring of
    the rendered page. But it never needed to: the closest match is found among
    the PAGE'S lines, so it is already the page's own characters and highlights
    perfectly. Building the fragment from the model's paraphrase was the bug;
    refusing to build one at all threw away working highlights.
    """
    import server as s
    page = ("Our treatment was designed around the way people actually live with this condition.\n"
            "It is given four times a year after the starting doses.")
    pages = [("https://x.example/p", page)]

    url, frag, how = s.locate_quote("It is given four times a year after the starting doses.", pages)
    assert how == "exact" and frag in page

    url, frag, how = s.locate_quote(
        "Our treatment is designed around how people live with this condition", pages)
    assert how == "near", "a tidied quote should still find its sentence"
    assert frag and frag in page, "the fragment must be the page's own wording, or it highlights nothing"
    assert "#:~:text=" in s.quote_link(url, frag)

    url, frag, how = s.locate_quote(
        "a support programme with a dedicated nurse team from your first dose", pages)
    assert how is None and frag is None, "wording that is simply not there must not be invented"


def test_meaning_beats_characters_when_matching():
    """Character similarity alone rates a one-word difference in the middle of a
    sentence too harshly. The blend with content-word overlap is what makes a
    tidied quote findable."""
    import server as s
    a = "designed around the way people actually live with this condition"
    b = "designed around how people live with this condition"
    c = "given four times a year after the starting doses"
    assert s._similarity(a, b) > s._similarity(a, c)
    assert s._similarity(a, b) >= 0.62, "a paraphrase this close must clear the bar"


def test_one_brand_s_imagery_is_described_rather_than_discarded():
    """Reading a brand's art direction and then throwing it away because no
    rival could be read wastes the reading and tells the reader nothing. One
    brand cannot be scored against nobody, but it can be described."""
    import server as s

    async def crawl(fetcher, brand, hint=None):
        return "[PAGE https://x.test/]\n" + ("copy about the category. " * 60), ["https://x.test/hero.jpg"], 1, "", {}

    async def images(http, urls, want=4):
        # Only the user's own brand yields anything a camera made.
        return [("https://x.test/hero.jpg", "image/jpeg", "AAAA")] if urls else []

    async def read(brand, imgs):
        return {"summary": f"{brand}: one adult alone in domestic light.",
                "elements": [{"image": 1, "note": "Single adult, waist-up, kitchen window light."},
                             {"image": 1, "note": "Short sleeves, forearm in frame."}]}

    seen = {"n": 0}

    async def images_once(http, urls, want=4):
        seen["n"] += 1
        return [("https://x.test/hero.jpg", "image/jpeg", "AAAA")] if seen["n"] == 1 else []

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(s.httpx, "AsyncClient", lambda *a, **k: _NoHTTP())
        monkey.setattr(s, "Fetcher", lambda http: _NoHTTP())
        monkey.setattr(s, "crawl_brand", crawl)
        monkey.setattr(s, "fetch_images", images_once)
        monkey.setattr(s, "stage_visual_read", read)
        monkey.setattr(s, "stage_layers", lambda b, c: _layers())
        monkey.setattr(s, "stage_space", lambda cat, e: _space())
        monkey.setattr(s, "stage_code", lambda b, f, p: _code())
        monkey.setattr(s, "stage_findings", lambda *a, **k: _findings())

        brands = [{"name": "Mine", "url": "https://a.test"}, {"name": "Other", "url": "https://c.test"}]
        result = None

        async def go():
            nonlocal result
            async for e in s.pipeline(brands):
                if e["type"] == "result":
                    result = e["data"]
                if e["type"] == "error":
                    raise AssertionError("run aborted: " + e["text"])

        import anyio
        anyio.run(go)
    finally:
        monkey.undo()

    assert result is not None
    v = result["visual"]
    assert v["compared"] is False, "one brand cannot be compared"
    assert result["convergence"]["imagery"] is None, "and must not reach the score"
    assert len(v["read"]) == 1, "but what was read has to survive"
    only = v["read"][0]
    assert only["summary"], "the reader gets a description"
    assert len(only["observations"]) == 2
    assert result["convergence"]["imagery_absent"] and "described" in result["convergence"]["imagery_absent"]


# ---------------------------------------------------------------------------
# The finder. Competitors are looked up, not recalled, and an address proved
# once is not guessed again.
# ---------------------------------------------------------------------------

_NDC_BRAND = {"results": [
    {"brand_name": "Ozempic", "generic_name": "Semaglutide", "labeler_name": "Novo Nordisk",
     "marketing_category": "NDA", "route": ["SUBCUTANEOUS"],
     "pharm_class": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]", "GLP-1 Agonists [MoA]"]}]}

_NDC_CLASS = {"results": [
    {"brand_name": "OZEMPIC 0.5 MG/DOSE", "generic_name": "Semaglutide", "labeler_name": "Novo Nordisk",
     "marketing_category": "NDA", "pharm_class": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"]},
    {"brand_name": "TRULICITY", "generic_name": "Dulaglutide", "labeler_name": "Eli Lilly",
     "marketing_category": "NDA", "pharm_class": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"]},
    {"brand_name": "TRULICITY", "generic_name": "Dulaglutide", "labeler_name": "Eli Lilly",
     "marketing_category": "NDA", "pharm_class": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"]},
    {"brand_name": "MOUNJARO PEN", "generic_name": "Tirzepatide", "labeler_name": "Eli Lilly",
     "marketing_category": "NDA", "pharm_class": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"]},
    {"brand_name": "SEMAGLUTIDE", "generic_name": "Semaglutide", "labeler_name": "A Generics Co",
     "marketing_category": "ANDA", "pharm_class": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"]},
]}


class _FDA:
    """Stands in for api.fda.gov, returning its documented shapes."""
    def __init__(self): self.calls = 0
    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        search = (params or {}).get("search", "")

        class R:
            status_code = 200
            def __init__(self, payload): self._p = payload
            def json(self): return self._p
        if "/ndc.json" in url and "pharm_class" in search:
            return R(_NDC_CLASS)
        if "/ndc.json" in url:
            return R(_NDC_BRAND)
        return R({"results": [{"indications_and_usage": [
            "OZEMPIC is indicated as an adjunct to diet and exercise to improve glycemic "
            "control in adults with type 2 diabetes mellitus."]}]})


@pytest.mark.anyio
async def test_competitors_come_from_the_register_not_from_recall():
    """A model asked for a fact it does not have produces something shaped like
    one — which is how a run ended up reading a corporate portal instead of a
    brand site. The class is a field on the record."""
    import drugs
    drugs._cache.data.clear()
    fda = _FDA()
    prof = await drugs.profile(fda, "Ozempic")
    assert prof["generic"] == "Semaglutide"
    assert prof["classes"] == ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"], "only EPC classes"

    got = await drugs.peers(fda, prof)
    names = [p["brand"] for p in got]
    assert "Trulicity" in names and "Mounjaro" in names
    assert names.count("Trulicity") == 1, "one entry per brand, not one per pack size"
    assert not any(n.lower() == "ozempic" for n in names), "a brand does not compete with itself"
    assert not any("Semaglutide" == n for n in names), "an ANDA generic is not competing on messaging"
    assert "Mounjaro" in names and "Mounjaro Pen" not in names, "dose form is not part of the brand"


@pytest.mark.anyio
async def test_the_register_is_asked_once_per_process():
    import drugs
    drugs._cache.data.clear()
    fda = _FDA()
    prof = await drugs.profile(fda, "Ozempic")
    first = fda.calls
    await drugs.profile(fda, "Ozempic")
    await drugs.profile(fda, "OZEMPIC ")
    assert fda.calls == first, "the same question must not be asked twice"


def test_an_address_is_guessed_in_a_sensible_order():
    import drugs
    patient = drugs.candidate_urls("Trulicity")
    hcp = drugs.candidate_urls("Trulicity", "hcp")
    assert patient[0] == "https://www.trulicity.com"
    assert hcp[0] == "https://www.trulicityhcp.com"
    assert all("trulicity" in u for u in patient + hcp)
    assert drugs.candidate_urls("") == []


@pytest.mark.anyio
async def test_a_human_correction_survives_the_crawler():
    """The point of the directory is that a wrong address can be fixed once and
    stay fixed."""
    from store import Store
    st = Store(dsn="")
    await st.remember_brand("Ozempic", patient_url="https://www.ozempic.com", patient_ok=True)
    await st.remember_brand("Ozempic", patient_url="https://correct.example",
                            patient_ok=True, confirmed_by="human")
    await st.remember_brand("Ozempic", patient_url="https://wrong.example", confirmed_by="crawler")
    row = (await st.brand_sites(["ozempic"]))["ozempic"]
    assert row["patient_url"] == "https://correct.example"
    assert row["confirmed_by"] == "human"


def test_the_type_ahead_finds_a_half_remembered_name():
    """Somebody typing a brand they half remember is the normal case."""
    import drugs
    idx = [
        {"brand": "Ozempic", "generic": "Semaglutide", "company": "Novo Nordisk", "cls": "GLP-1", "n": 40},
        {"brand": "Ozobax", "generic": "Baclofen", "company": "Metacel", "cls": "", "n": 3},
        {"brand": "Trulicity", "generic": "Dulaglutide", "company": "Eli Lilly", "cls": "GLP-1", "n": 30},
    ]
    assert [e["brand"] for e in drugs.search_index(idx, "ozempick")] == ["Ozempic"]
    assert [e["brand"] for e in drugs.search_index(idx, "trulicty")] == ["Trulicity"]
    # Two letters: the drug most people are taking, not the shortest name.
    assert drugs.search_index(idx, "oz")[0]["brand"] == "Ozempic"
    # The molecule and the company are ways in as well as the brand.
    assert "Ozempic" in [e["brand"] for e in drugs.search_index(idx, "semaglut")]
    assert "Trulicity" in [e["brand"] for e in drugs.search_index(idx, "lilly")]


def test_the_index_keeps_brands_and_drops_commodities():
    """Ranked by listing count openFDA offers Oxygen and Sodium Chloride. A
    promoted brand is one whose name is not merely its own molecule."""
    import drugs
    branded = {"brand_name": "Ozempic", "generic_name": "Semaglutide",
               "marketing_category": "NDA", "pharm_class": ["GLP-1 [EPC]"]}
    commodity = {"brand_name": "Oxygen", "generic_name": "Oxygen",
                 "marketing_category": "NDA", "pharm_class": ["x [EPC]"]}
    coat = {"brand_name": "Semaglutide Injection", "generic_name": "Semaglutide",
            "marketing_category": "NDA", "pharm_class": ["GLP-1 [EPC]"]}
    generic = {"brand_name": "Metformin", "generic_name": "Metformin HCl",
               "marketing_category": "ANDA", "pharm_class": ["x [EPC]"]}
    assert drugs._is_branded(branded)
    assert not drugs._is_branded(commodity)
    assert not drugs._is_branded(coat)
    assert not drugs._is_branded(generic)


def test_therapy_areas_answer_the_words_people_use():
    """A brand lead says eczema; the register says atopic dermatitis."""
    import drugs
    assert drugs.search_areas("eczema")[0] == "Atopic dermatitis"
    assert drugs.search_areas("t2d")[0] == "Type 2 diabetes"
    assert "Type 2 diabetes" in drugs.search_areas("diabetis"), "a typo must still land"
    assert drugs.search_areas("migrane")[0] == "Migraine"
    assert drugs.search_areas("") , "an empty box offers something to pick"


def test_the_therapy_area_offered_comes_from_the_brand_s_own_label():
    """The field used to open on a hand-written list in a fixed order, so
    whatever the brand, the first thing offered was type 2 diabetes. The brand
    has already been chosen by then and its label says what it treats."""
    import drugs
    ozempic = drugs.areas_for(
        "indicated as an adjunct to diet and exercise to improve glycemic "
        "control in adults with type 2 diabetes mellitus",
        {"classes": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"],
         "generic": "semaglutide"})
    assert ozempic[0]["label"] == "Type 2 diabetes"
    assert ozempic[0]["sure"], "the label names it outright"

    dupixent = drugs.areas_for(
        "indicated for the treatment of adult and pediatric patients aged 6 "
        "months and older with moderate-to-severe atopic dermatitis",
        {"classes": ["Interleukin-4 Receptor Antagonist [EPC]"], "generic": "dupilumab"})
    assert dupixent[0]["label"] == "Atopic dermatitis"

    # A label using the word people use, not the register's word.
    assert drugs.areas_for("indicated for the treatment of moderate to severe eczema "
                           "in adults")[0]["label"] == "Atopic dermatitis"

    # A breast cancer label must not surface every cancer in the list as though
    # they were all candidates.
    breast = drugs.areas_for("indicated for the treatment of adult patients with "
                             "HR-positive, HER2-negative advanced or metastatic breast cancer")
    assert breast[0]["label"] == "Breast cancer"
    assert not any(a["label"] in ("Lung cancer", "Prostate cancer", "Ovarian cancer")
                   for a in breast), "one cancer in the label is not every cancer"

    # Nothing to go on is answered with nothing, not with a guess.
    assert drugs.areas_for("") == []
    assert drugs.areas_for("indicated", None) == []


@pytest.mark.anyio
async def test_the_areas_endpoint_answers_from_the_register(client, monkeypatch):
    """Asked once, when a brand is chosen. A brand openFDA has never heard of —
    anything marketed only in Europe — is answered honestly rather than with a
    guess, and the field falls back to the starter list."""
    import server as s

    async def profile(http, brand):
        if brand.lower() != "ozempic":
            return None
        return {"brand": "Ozempic", "generic": "semaglutide",
                "classes": ["Glucagon-Like Peptide-1 Receptor Agonist [EPC]"]}

    async def category_of(http, prof):
        return ("indicated as an adjunct to diet and exercise to improve glycemic "
                "control in adults with type 2 diabetes mellitus")

    monkeypatch.setattr(s.drugs, "profile", profile)
    monkeypatch.setattr(s.drugs, "category_of", category_of)

    body = (await client.get("/api/areas?brand=Ozempic")).json()
    assert body["known"] is True
    assert body["areas"][0] == {"label": "Type 2 diabetes", "sure": True}

    body = (await client.get("/api/areas?brand=Wegovy%20Europe")).json()
    assert body["known"] is False and body["areas"] == []

    body = (await client.get("/api/areas")).json()
    assert body["areas"] == []


def test_a_label_is_never_clipped_mid_word():
    """"whose disease i" reads like a bug, because it is one."""
    import drugs
    long = ("indicated for the treatment of adult patients with moderate-to-severe "
            "atopic dermatitis whose disease is not adequately controlled with "
            "topical prescription therapies")
    got = drugs.short_indication(long)
    assert len(got) <= 111
    assert got.endswith("\u2026")
    assert not got[:-1].endswith(" ")
    assert " ".join(got[:-1].split()) in " ".join(long.split()), "the clip must be the label's own words"


def test_one_character_is_not_a_query():
    """Typing "a" prefix-matched the synonym "as" and put axial
    spondyloarthritis at the top of the list — which is how a field ends up
    suggesting the wrong thing to everybody who touches it."""
    import drugs
    assert drugs.search_areas("a") == drugs.search_areas(""), "one character offers the starter list"
    assert drugs.search_areas("as")[0] == "Axial spondyloarthritis", "typed in full it still works"
    assert drugs.search_areas("ms")[0] == "Multiple sclerosis"
    assert "Multiple sclerosis" not in drugs.search_areas("m")[:3]
    # And the useful matching is untouched.
    assert drugs.search_areas("ecz")[0] == "Atopic dermatitis"
    assert drugs.search_areas("diabetis")[0].startswith("Type")


def test_a_therapy_area_that_contradicts_the_drug_is_flagged():
    """Observed in production: Rozerem, an insomnia drug, entered with a therapy
    area of "Acne". Every territory is built for the therapy area, so the whole
    report would have been about a conversation nobody is having."""
    import drugs
    label = ("ROZEREM is indicated for the treatment of insomnia characterized by "
             "difficulty with sleep onset.")
    prof = {"classes": ["Melatonin Receptor Agonist [EPC]"], "generic": "ramelteon"}
    assert not drugs.area_matches("Acne", label, prof)
    assert drugs.area_matches("insomnia", label, prof)
    assert drugs.area_matches("sleep", label, prof)
    assert drugs.area_matches("", label, prof), "a blank area is not a contradiction"
    # Generous on purpose: a label says "moderate-to-severe plaque psoriasis"
    # where a brand lead types "psoriasis".
    assert drugs.area_matches("psoriasis", "indicated for moderate-to-severe plaque psoriasis in adults")
    assert drugs.area_matches("diabetes", "indicated to improve glycemic control in diabetic adults")
    assert drugs.short_indication(label) == "insomnia characterized by difficulty with sleep onset"


# ---------------------------------------------------------------------------
# The browser of last resort.
#
# Roughly half of the sites that failed in production failed because their copy
# is assembled in the browser: the fetch succeeds, the parse succeeds, and the
# brand appears to have nothing to say. These tests fix the rule for when a
# real browser is worth its gigabyte, and prove the crawl escalates only then.
# There is no Chromium here — the renderer is stubbed, deliberately, because
# what is being tested is the decision, not Playwright.
# ---------------------------------------------------------------------------

SHELL = """<html><body><nav>Home Safety Contact</nav>
<div id="root"></div><script src="/bundle.js"></script></body></html>"""

# Varied on purpose. visible_text drops a line it has already seen, so twelve
# identical paragraphs read as one and the page looks thin — which would make
# this fixture prove the opposite of what it is here to prove.
FULL = ("<html><body><h1>Living with it, on your terms</h1>"
        + "".join(
            f"<p>A once-daily treatment designed around the way people actually "
            f"live with this condition, rather than the way a clinic imagines "
            f"they do — point {i} of the argument this brand is making.</p>"
            for i in range(12))
        + "</body></html>")


class _StubFetcher:
    """Whatever the crawler asks for, plus a record of what it escalated."""

    def __init__(self, pages, rendered=None):
        self.pages = pages            # url -> (status, content-type, html)
        self.rendered = rendered or {}
        self.renders = []

    async def allowed(self, url):
        return True

    async def get(self, url, timeout=25):
        status, ctype, html = self.pages.get(url, (404, "text/html", ""))
        return server.SimpleResponse(url, status, {"content-type": ctype}, html)

    async def render(self, url, timeout=30):
        self.renders.append(url)
        html = self.rendered.get(url)
        if html is None:
            return None
        return server.SimpleResponse(url, 200, {"content-type": "text/html"}, html)


def test_the_rule_for_reaching_for_a_browser():
    """Two cases, and only two: the site would not talk to us, or it talked and
    said nothing. A 404 is neither — that address is wrong, and rendering it
    would spend a gigabyte confirming it."""
    import server as s
    assert s.needs_browser(403, "text/html", 40000), "bot protection is worth a browser"
    assert s.needs_browser(429, "text/html", 0)
    assert s.needs_browser(503, "text/html", 0)
    assert s.needs_browser(0, "", 0), "a connection that never happened"
    assert s.needs_browser(200, "text/html; charset=utf-8", 300), "a shell"
    assert not s.needs_browser(404, "text/html", 0), "a wrong address is not a shy one"
    assert not s.needs_browser(301, "text/html", 0)
    assert not s.needs_browser(200, "application/pdf", 0), "a PDF is not a page that failed to render"
    assert not s.needs_browser(200, "text/html", 40000), "a page that read fine"


@pytest.mark.anyio
async def test_a_page_built_in_the_browser_is_read_in_one():
    """The failure this whole piece of work exists for: a valid, well-formed,
    entirely empty document that scores as a brand with nothing to say."""
    import server as s
    f = _StubFetcher({"https://brand.test/": (200, "text/html", SHELL)},
                     rendered={"https://brand.test/": FULL})
    corpus, _images, pages, why, notes = await s.crawl_brand(f, {"name": "B", "url": "https://brand.test/"})
    assert f.renders == ["https://brand.test/"]
    assert notes["rendered"] == 1
    assert "once-daily treatment" in corpus
    assert pages == 1 and why == ""


@pytest.mark.anyio
async def test_a_page_that_reads_fine_never_costs_a_render():
    """The browser is the exception. If most pages reached it the service would
    not fit on the box, and the run would take ten minutes rather than three."""
    import server as s
    f = _StubFetcher({"https://brand.test/": (200, "text/html", FULL)})
    corpus, _i, _p, _w, notes = await s.crawl_brand(f, {"name": "B", "url": "https://brand.test/"})
    assert f.renders == [], "a readable page was escalated anyway"
    assert notes["rendered"] == 0
    assert "once-daily treatment" in corpus


@pytest.mark.anyio
async def test_the_page_data_is_looked_in_before_the_browser_is_started():
    """A shell whose copy is sitting in a JSON blob is already readable. It was
    readable before Chromium existed here, and it must stay free."""
    import server as s
    # Several keys, not one long one: a harvested string has to be sentence
    # length to count as copy rather than as a serialised blob.
    blob = json.dumps({"props": {f"block{i}": (
        "A once-daily treatment designed around the way people actually live "
        f"with this condition, rather than the way a clinic imagines they do, "
        f"as this brand puts it in section {i}.") for i in range(8)}})
    shell = ("<html><body><nav>Home</nav>"
             '<script id="__NEXT_DATA__" type="application/json">' + blob +
             "</script></body></html>")
    f = _StubFetcher({"https://brand.test/": (200, "text/html", shell)},
                     rendered={"https://brand.test/": FULL})
    corpus, _i, _p, _w, notes = await s.crawl_brand(f, {"name": "B", "url": "https://brand.test/"})
    assert f.renders == [], "the page data was already enough"
    assert notes["json_pages"] == 1 and notes["rendered"] == 0
    assert "once-daily treatment" in corpus


@pytest.mark.anyio
async def test_a_door_closed_on_the_client_is_tried_once_with_a_browser():
    """Bot protection answers 403 to a client it does not like. That is a fact
    about the client, not about the page."""
    import server as s
    f = _StubFetcher({"https://brand.test/": (403, "text/html", "Access denied")},
                     rendered={"https://brand.test/": FULL})
    corpus, _i, pages, why, notes = await s.crawl_brand(f, {"name": "B", "url": "https://brand.test/"})
    assert f.renders == ["https://brand.test/"] and notes["rendered"] == 1
    assert "once-daily treatment" in corpus and pages == 1 and why == ""


@pytest.mark.anyio
async def test_the_browser_failing_is_not_the_run_failing():
    """No Chromium, a crashed browser, a page that hangs — all of them come
    back as None, and the crawl keeps whatever plain HTTP gave it. A tool that
    will not run without a browser is worse than one that reads a site badly."""
    import server as s
    f = _StubFetcher({"https://brand.test/": (200, "text/html", SHELL)})   # render returns None
    corpus, _i, pages, why, notes = await s.crawl_brand(f, {"name": "B", "url": "https://brand.test/"})
    assert f.renders == ["https://brand.test/"] and notes["rendered"] == 0
    assert pages == 1 and why == "", "the page still counted, thin as it is"
    assert notes["thin_pages"] == 1


@pytest.mark.anyio
async def test_a_gate_in_front_of_a_rendered_site_is_still_walked_through():
    """Gate first, browser second. The two fixes have to compose: the common
    arrangement is an HCP gate in front of a site that renders in the browser,
    and handling either one alone still reads nothing."""
    import server as s
    f = _StubFetcher({"https://brand.test/": (200, "text/html", GATE_HTML),
                      "https://brand.test/hcp/home": (200, "text/html", SHELL)},
                     rendered={"https://brand.test/hcp/home": FULL})
    corpus, _i, _p, _w, notes = await s.crawl_brand(f, {"name": "B", "url": "https://brand.test/"})
    assert notes["gates"] == 1 and notes["rendered"] == 1
    assert "once-daily treatment" in corpus


# ---------------------------------------------------------------------------
# Photographing the evidence, and getting in the door.
#
# There is no Chromium in these tests — the renderer is stubbed, because what is
# being tested is which pages get visited, what gets uploaded, and what the
# report says when none of it is available. The pictures themselves are proved
# by looking at them, which is a different job.
# ---------------------------------------------------------------------------


class _StubRenderer:
    """A browser that returns what it is told to, and records what it was asked."""

    def __init__(self, pages=None, enabled=True):
        self.pages = pages or {}
        self.enabled = enabled
        self.visits = []

    def status(self):
        return {"enabled": self.enabled, "running": False, "pages": 2,
                "rendered": 0, "captured": 0, "failed": 0, "why": ""}

    async def visit(self, url, *, quotes=(), want_hero=False, **kw):
        self.visits.append({"url": url, "quotes": list(quotes), "hero": want_hero})
        spec = self.pages.get(url)
        if spec is None:
            return None
        import browser as bmod
        shots = {i: {"png": b"jpeg-" + str(i).encode(), "how": spec.get("how", "sentence")}
                 for i, q in enumerate(quotes) if q in spec.get("finds", [])}
        return bmod.Rendered(url, 200, "<html></html>", gates=spec.get("gates", 0),
                             hero=(b"jpeg-hero" if want_hero else None), shots=shots)

    async def close(self):
        return None


@pytest.mark.anyio
async def test_the_evidence_is_photographed_where_it_sits(monkeypatch):
    """The report's promise is that every number is one click from the sentence
    that produced it. A photograph of that sentence on the brand's own page is
    the strong version of the promise; the link is the weak one."""
    import server as s
    quote_a = "A once-daily treatment designed around how people actually live."
    quote_b = "Ask your doctor whether this is right for you."
    stub = _StubRenderer({
        "https://a.test/why": {"finds": [quote_a], "how": "sentence"},
        "https://a.test/": {"finds": []},
    })
    monkeypatch.setattr(s.browser, "renderer", stub)
    monkeypatch.setattr(s.shots, "configured", lambda: True)

    put = []

    async def fake_put(http, path, data, content_type="image/jpeg"):
        put.append((path, data))
        return "https://cdn.test/" + path

    monkeypatch.setattr(s.shots, "put", fake_put)

    got, heroes, stats = await s.capture_evidence(
        "run123", None,
        {"A": {"https://a.test/why": [("P01", quote_a), ("P02", quote_b)]}},
        {"A": "https://a.test/"})

    assert got[("A", "P01")]["url"] == "https://cdn.test/run123/a-quote-0.jpg"
    assert got[("A", "P01")]["how"] == "sentence"
    assert ("A", "P02") not in got, "a sentence not found on the page is not invented"
    assert stats == {"pages": 2, "sentence": 1, "block": 0, "heroes": 1, "missed": 1}
    assert heroes["A"] == "https://cdn.test/run123/a-hero.jpg"
    # The hero comes off the brand's own front page, and that page is visited
    # even though no evidence sits on it.
    assert {v["url"] for v in stub.visits} == {"https://a.test/why", "https://a.test/"}
    assert [v["hero"] for v in stub.visits if v["url"] == "https://a.test/"] == [True]


@pytest.mark.anyio
async def test_no_bucket_means_no_pictures_and_no_pretending(monkeypatch):
    """A missing picture must never cost somebody their analysis, and it must
    never be silent either."""
    import server as s
    monkeypatch.setattr(s.browser, "renderer", _StubRenderer({}, enabled=True))
    monkeypatch.setattr(s.shots, "configured", lambda: False)
    monkeypatch.setattr(s.shots, "why_not", lambda: "not configured: SUPABASE_URL")
    assert not s.shots_available()
    assert "SUPABASE_URL" in s.what_stops_the_pictures()
    got, heroes, stats = await s.capture_evidence("r", None, {"A": {"u": [("P01", "q")]}}, {})
    assert (got, heroes) == ({}, {})
    assert stats["pages"] == 0, "nothing is opened if there is nowhere to put the result"

    monkeypatch.setattr(s.browser, "renderer", _StubRenderer({}, enabled=False))
    monkeypatch.setattr(s.shots, "configured", lambda: True)
    assert s.what_stops_the_pictures() == "no browser available"


@pytest.mark.anyio
async def test_a_host_known_to_need_a_browser_gets_one_first():
    """Working out that a host serves a shell costs a wasted request every run,
    for the same hosts, forever. It is worked out once and remembered."""
    import server as s
    f = _StubFetcher({}, rendered={"https://brand.test/": FULL})
    corpus, _i, _p, _w, notes = await s.crawl_brand(
        f, {"name": "B", "url": "https://brand.test/"},
        hint={"needs_browser": True})
    assert notes["browser_first"] is True
    assert f.renders == ["https://brand.test/"]
    assert "once-daily treatment" in corpus
    # And plain HTTP was never tried, which is the whole saving.
    assert f.pages == {}


def test_the_stealth_patch_covers_what_a_page_actually_checks():
    """Not a defence and not a secret — a handful of properties a real Chrome
    has and an automated one, by default, does not. Sites whose robots.txt
    invites crawlers still turn away a client without them."""
    import browser as b
    for probe in ("navigator.webdriver", "window.chrome", "navigator.plugins",
                  "navigator.languages", "permissions.query"):
        assert probe.split(".")[-1] in b.STEALTH
    assert "--disable-blink-features=AutomationControlled" in b.LAUNCH_ARGS
    assert "--no-sandbox" in b.LAUNCH_ARGS and "--disable-dev-shm-usage" in b.LAUNCH_ARGS


def test_a_stored_object_has_a_predictable_safe_name():
    import shots
    assert shots.path_for("abc123", "Ozempic", "hero") == "abc123/ozempic-hero.jpg"
    assert shots.path_for("abc123", "Mounjaro (tirzepatide)", "quote", 3) == \
        "abc123/mounjaro--tirzepatide-quote-3.jpg"


@pytest.mark.anyio
async def test_a_hint_is_remembered_without_the_migration(monkeypatch):
    """The table only ever saves work. If the migration has not been run, a run
    must be exactly as fast and exactly as correct as it was before."""
    from store import Store
    st = Store(dsn="")
    await st.remember_hint("brand.test", needs_browser=True, chars=9000)
    assert (await st.crawl_hints(["brand.test"]))["brand.test"]["needs_browser"]
    # Additive: one run that managed without a browser does not erase the
    # knowledge that another one needed it.
    await st.remember_hint("brand.test", needs_browser=False, chars=9000)
    assert (await st.crawl_hints(["www.brand.test"]))["brand.test"]["needs_browser"]
    assert await st.crawl_hints(["nobody.test"]) == {}
