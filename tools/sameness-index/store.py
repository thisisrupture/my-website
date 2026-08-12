"""
Sameness Index — run persistence.

A run takes two to five minutes, so the browser cannot hold the request open
for it. The request starts the work and returns an id; the work continues in
the background and writes its progress and its result here; the browser polls.
The same store is what makes `/r/<id>` possible afterwards.

Two backends, one interface:

- Postgres (Supabase), used whenever DATABASE_URL is set. This is what runs in
  production and what permalinks depend on.
- In-memory, used when it is not. Local development and the test harness work
  with no database, and a permalink survives until the server restarts.

Nothing here knows anything about the methodology. It stores what a run was,
what it said while it ran, and what it produced.
"""

import asyncio
import json
import os
import secrets
import time

# No vowels and no look-alike characters: an id gets read aloud, retyped and
# pasted into chat threads. 31^12 is roughly 7.9e17 — an id cannot be found by
# guessing, which matters because a run record carries the brands somebody
# chose to compare and, later, the email address they gave.
ALPHABET = "bcdfghjkmnpqrstvwxyz23456789"
ID_LENGTH = 12

# A run held open longer than this is not coming back. The usual cause is a
# deploy or a restart landing mid-run.
STALE_AFTER_SECONDS = int(os.environ.get("SAMENESS_STALE_AFTER", "900"))

STALE_MESSAGE = (
    "This run stopped before it finished, most likely because the server "
    "restarted while it was working. Nothing was scored. Start it again."
)


def new_id():
    return "".join(secrets.choice(ALPHABET) for _ in range(ID_LENGTH))


def now():
    return time.time()


class Store:
    """Async run storage. Call `start()` once at application startup."""

    def __init__(self, dsn=None):
        self.dsn = dsn if dsn is not None else os.environ.get("DATABASE_URL", "")
        self.pool = None
        self._mem = {}
        self._lock = asyncio.Lock()

    @property
    def persistent(self):
        return self.pool is not None

    async def start(self):
        if not self.dsn:
            return
        import asyncpg

        # Supabase's transaction pooler is pgbouncer in transaction mode, which
        # cannot hold server-side prepared statements. Without this asyncpg
        # fails on its second query with a DuplicatePreparedStatementError.
        self.pool = await asyncpg.create_pool(
            self.dsn,
            min_size=1,
            max_size=int(os.environ.get("SAMENESS_DB_POOL", "5")),
            statement_cache_size=0,
            command_timeout=30,
        )

    async def stop(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    # -- writing ------------------------------------------------------------

    async def create(self, brands, client_ip=None, user_agent=None):
        """Insert a new run and return its id."""
        for _ in range(5):
            run_id = new_id()
            if self.pool is None:
                async with self._lock:
                    if run_id in self._mem:
                        continue
                    self._mem[run_id] = {
                        "id": run_id,
                        "status": "running",
                        "created_at": now(),
                        "started_at": now(),
                        "finished_at": None,
                        "category": None,
                        "brands": brands,
                        "progress": [],
                        "result": None,
                        "error": None,
                        "summary": None,
                        "client_ip": client_ip,
                        "user_agent": user_agent,
                    }
                    return run_id
            try:
                async with self.pool.acquire() as c:
                    await c.execute(
                        """insert into runs (id, status, brands, client_ip, user_agent, started_at)
                           values ($1, 'running', $2::jsonb, $3, $4, now())""",
                        run_id, json.dumps(brands), client_ip, (user_agent or "")[:500],
                    )
                return run_id
            except Exception as e:
                if "duplicate key" in str(e).lower():
                    continue
                raise
        raise RuntimeError("Could not allocate a run id.")

    async def append_progress(self, run_id, event):
        """Append one narration line. Written as a jsonb concatenation so two
        writes can never lose one another."""
        event = {"t": now(), **event}
        if self.pool is None:
            async with self._lock:
                run = self._mem.get(run_id)
                if run:
                    run["progress"].append(event)
            return
        async with self.pool.acquire() as c:
            await c.execute(
                "update runs set progress = progress || $2::jsonb where id = $1",
                run_id, json.dumps([event]),
            )

    async def finish(self, run_id, result):
        """Store a completed result, plus the handful of fields worth having in
        columns so the run list is readable without opening the JSON."""
        meta = result.get("meta", {}) or {}
        metrics = result.get("metrics", {}) or {}
        category = meta.get("category")
        summary = {
            "crowding_rate": metrics.get("crowding_rate"),
            "occupancy_rate": metrics.get("occupancy_rate"),
            "space_size": metrics.get("space_size"),
            "contested": metrics.get("contested"),
            "open_empty": metrics.get("open_empty"),
            "brands": [b.get("name") for b in meta.get("brands", [])],
        }
        if self.pool is None:
            async with self._lock:
                run = self._mem.get(run_id)
                if run:
                    run.update(status="complete", result=result, category=category,
                               summary=summary, finished_at=now())
            return
        async with self.pool.acquire() as c:
            await c.execute(
                """update runs set status = 'complete', result = $2::jsonb,
                       category = $3, summary = $4::jsonb, finished_at = now()
                   where id = $1""",
                run_id, json.dumps(result), category, json.dumps(summary),
            )

    async def fail(self, run_id, message):
        if self.pool is None:
            async with self._lock:
                run = self._mem.get(run_id)
                if run:
                    run.update(status="failed", error=message, finished_at=now())
            return
        async with self.pool.acquire() as c:
            await c.execute(
                "update runs set status = 'failed', error = $2, finished_at = now() where id = $1",
                run_id, message,
            )

    # -- reading ------------------------------------------------------------

    async def get(self, run_id, since=0):
        """Return a run, with only the progress lines the caller has not seen.
        A run that has been abandoned mid-flight is marked failed on read —
        there is no scheduler here and nothing else would ever notice."""
        if self.pool is None:
            async with self._lock:
                run = self._mem.get(run_id)
                if run is None:
                    return None
                if run["status"] == "running" and now() - run["started_at"] > STALE_AFTER_SECONDS:
                    run.update(status="failed", error=STALE_MESSAGE, finished_at=now())
                row = dict(run)
        else:
            async with self.pool.acquire() as c:
                await c.execute(
                    """update runs set status = 'failed', error = $2, finished_at = now()
                       where id = $1 and status = 'running'
                         and started_at < now() - ($3 || ' seconds')::interval""",
                    run_id, STALE_MESSAGE, str(STALE_AFTER_SECONDS),
                )
                r = await c.fetchrow(
                    """select id, status, category, brands, progress, result, error, summary
                       from runs where id = $1""",
                    run_id,
                )
            if r is None:
                return None
            row = dict(r)
            for k in ("brands", "progress", "result", "summary"):
                if isinstance(row.get(k), str):
                    row[k] = json.loads(row[k])

        progress = row.get("progress") or []
        return {
            "id": row["id"],
            "status": row["status"],
            "category": row.get("category"),
            "brands": row.get("brands") or [],
            "progress": progress[since:],
            "progress_total": len(progress),
            "result": row.get("result"),
            "error": row.get("error"),
        }

    async def runs_since(self, client_ip, seconds):
        """How many runs this address has started recently. The cost control:
        every run spends real money on crawling and model calls, and a public
        URL is a public URL."""
        if not client_ip:
            return 0
        cutoff = now() - seconds
        if self.pool is None:
            async with self._lock:
                return sum(1 for r in self._mem.values()
                           if r.get("client_ip") == client_ip and r["created_at"] > cutoff)
        async with self.pool.acquire() as c:
            return await c.fetchval(
                """select count(*) from runs where client_ip = $1
                   and created_at > now() - ($2 || ' seconds')::interval""",
                client_ip, str(int(seconds)),
            )
