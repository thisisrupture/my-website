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


async def fake_pipeline(brands, category=""):
    yield {"type": "progress", "text": "Reading the first site."}
    await asyncio.sleep(0.05)
    yield {"type": "progress", "text": "Reading the second site."}
    await asyncio.sleep(0.05)
    yield {"type": "result", "data": STUB_RESULT}


async def failing_pipeline(brands, category=""):
    yield {"type": "progress", "text": "Reading the first site."}
    yield {"type": "error", "text": "Could not read enough of that site."}


async def exploding_pipeline(brands, category=""):
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

    async def hanging_pipeline(brands, category=""):
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

    async def capture(brands, category=""):
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
    async def crawl(fetcher, brand):
        if brand["name"] == "Blocked":
            return "", [], 0, ""                  # nothing readable came back
        return "[PAGE https://x.test/]\n" + ("copy about the category. " * 60), [], 1, ""
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
    async def crawl(fetcher, brand):
        return ("", [], 0, "") if brand["name"] == "Mine" else ("[PAGE https://x/]\n" + "copy. " * 200, [], 1, "")
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

    async def crawl(fetcher, brand):
        if brand["name"] == "Private":
            return "", [], 0, "robots"
        return "[PAGE https://x.test/]\n" + ("copy about the category. " * 60), [], 1, ""

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

    async def crawl(fetcher, brand):
        return "[PAGE https://x.test/]\n" + ("words on a page. " * 60), [], 1, ""

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

    async def crawl(fetcher, brand):
        return "[PAGE https://x.test/]\n" + ("words on a page. " * 60), [], 1, ""

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
