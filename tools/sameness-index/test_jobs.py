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


async def fake_pipeline(brands):
    yield {"type": "progress", "text": "Reading the first site."}
    await asyncio.sleep(0.05)
    yield {"type": "progress", "text": "Reading the second site."}
    await asyncio.sleep(0.05)
    yield {"type": "result", "data": STUB_RESULT}


async def failing_pipeline(brands):
    yield {"type": "progress", "text": "Reading the first site."}
    yield {"type": "error", "text": "Could not read enough of that site."}


async def exploding_pipeline(brands):
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

    async def hanging_pipeline(brands):
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
