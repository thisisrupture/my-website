# Putting the Sameness Index online

Written for someone who has not deployed anything before. Every step says what
it is for, so you can tell when something has gone wrong rather than just
following instructions and hoping.

---

## First, what each thing actually does

There is one common misunderstanding worth clearing up before you start.

**Cloudflare does not run the tool.** Cloudflare Pages takes your Astro site,
turns it into finished HTML pages, and serves them very fast from all over the
world. That is all it can do. It cannot run Python, so it cannot crawl a
website, call the Anthropic API or hold a job for three minutes. When you push
to GitHub, Cloudflare will build the marketing site and completely ignore the
`tools/` folder.

**Render runs the tool.** Somebody has to own a computer that is switched on
all the time, running Python, waiting for requests. That is Render. It watches
the same GitHub repository, but it only looks at `tools/sameness-index`, and it
runs `server.py`. This is the only place your Anthropic key ever exists.

**Supabase stores the results.** When a run finishes, the result has to be
written down somewhere that survives the server restarting, or every `/r/<id>`
link would break each time you deployed. Supabase is a hosted database with a
web interface. It is already set up.

So: one repository, two deployments that do not know about each other.
`thisisrupture.com` is Cloudflare. `tools.thisisrupture.com` is Render. Both
are yours, both come from the same `git push`.

**Yes, you will use Terminal and GitHub.** Terminal for about four commands,
GitHub only as the place both services read from. You already have the
repository — `thisisrupture/my-website` — so this is a normal commit and push,
not a new setup.

---

## Where this folder lives

`my-website/tools/sameness-index/` is now the real home of the tool. The copy in
`Claude Workspace/Rupture 2.0/sameness-index/` is the older working copy —
**stop editing that one**, or you will end up deploying an old version and
wondering why a change did nothing.

---

## What already exists

- Supabase project **Rupture Tools**, London region, £10/month, with the `runs`
  table created and locked down.
- The job infrastructure and permalinks, tested.

## What does not exist yet

The email gate, the notification when someone runs it, and the page on
`thisisrupture.com` that sends people to the tool. Those come after this. Do
not link to the tool from anywhere until the gate is in.

---

## Step 1 — Push the code (Terminal)

Open Terminal and paste these one at a time.

```bash
cd ~/Library/CloudStorage/GoogleDrive-kristian@thisisrupture.com/My\ Drive/Rupture/Rupture\ Assets/my-website
git status
```

`git status` should list `tools/sameness-index/` as new. If it lists thousands
of files, or anything mentioning `node_modules`, stop and say so before going
further.

```bash
git add tools/sameness-index
git commit -m "Sameness Index: background jobs, permalinks, deployment config"
git push
```

Cloudflare will start a build of the marketing site. That is expected and
harmless — nothing on the site has changed.

## Step 2 — Get the database connection string (Supabase)

1. Go to supabase.com and open the **Rupture Tools** project.
2. Click **Connect** at the top of the page.
3. Choose the **Transaction pooler** string. It looks like this:

```
postgresql://postgres.upflzhglbfkslwysopll:[YOUR-PASSWORD]@aws-1-eu-west-2.pooler.supabase.com:6543/postgres
```

4. Replace `[YOUR-PASSWORD]` with the database password from when the project
   was created. If you do not have it, reset it under **Settings → Database**
   and use the new one.

Use the *transaction pooler* string, not the direct connection. Render opens
and closes connections as it works, and the pooler is the thing that handles
that without running the database out of them.

Keep this string somewhere safe for the next step. It is a password — it does
not go in the repository, in Slack, or in a document.

## Step 3 — Create the Render service

1. Sign up at render.com and connect your GitHub account.
2. **New → Web Service**, choose the `thisisrupture/my-website` repository.
3. Render reads `render.yaml` and fills most of it in. Confirm it shows:
   - Root directory `tools/sameness-index` — **this one matters most.** If it
     is blank, Render will try to build the Astro site as if it were Python and
     fail.
   - Build command `pip install -r requirements.txt`
   - Start command `uvicorn server:app --host 0.0.0.0 --port $PORT`
   - Instance type **Starter**, about $7/month
4. Under **Environment**, add two variables:
   - `ANTHROPIC_API_KEY` — your key from console.anthropic.com
   - `DATABASE_URL` — the string from step 2
5. Deploy. It takes a few minutes.

**Do not choose the free instance type.** Free instances go to sleep when
nobody is using them and get restarted whenever the host feels like it. A run
takes two to five minutes, and a sleep in the middle of one loses the work. The
tool notices and tells the user, but the run is gone and the API call is still
paid for.

## Step 4 — Check it before anyone sees it

Render gives you an address like `rupture-tools.onrender.com`. Open it.

1. You should see the input screen.
2. Open `rupture-tools.onrender.com/api/health`. You want
   `{"ok":true,"persistent":true,...}`. **If `persistent` says `false`, stop** —
   it means `DATABASE_URL` is wrong or missing, and every permalink will break
   the next time the service restarts.
3. Open `rupture-tools.onrender.com/server.py`. You want **404 Not Found**. If
   it shows you code, stop and tell me — that would be the method published.
4. Run the index against two brands you know are readable. Watch for the
   narration appearing, the address bar changing to `/r/...` as it starts, and
   the result at the end.
5. **Reload the page while it is still running.** The narration should pick up
   where it was. This is the whole point of the change.
6. Copy the link, open it in a private window with no login. Same result.

## Step 5 — Point a subdomain at it

Only once step 4 is clean.

1. In Render: **Settings → Custom Domains**, add `tools.thisisrupture.com`.
   Render shows you a CNAME record.
2. In Cloudflare: open the `thisisrupture.com` DNS settings, add that CNAME,
   and set it to **DNS only** (the grey cloud, not the orange one) for now.
   Cloudflare's proxy buffers responses in ways that are worth ruling out while
   you are still checking things work.
3. Repeat the step 4 checks on the new address.

Do not add a link to it from `thisisrupture.com` yet. The tool has no email
gate, so every run it does right now costs you money and tells you nothing
about who ran it.

---

## What it costs to leave running

| | |
|---|---|
| Render Starter | about $7/month |
| Supabase | £10/month |
| Anthropic | per run — about a dozen model calls plus the crawling |

The first two are fixed and predictable. The third is not, which is why the
service refuses more than five runs a day from one connection and three at
once. Both are settings in Render (`SAMENESS_RUNS_PER_IP`,
`SAMENESS_MAX_CONCURRENT`) that you can change without touching code.

## Running it on your own machine

Still works, and still needs no database:

```bash
cd ~/Library/CloudStorage/GoogleDrive-kristian@thisisrupture.com/My\ Drive/Rupture/Rupture\ Assets/my-website/tools/sameness-index
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn server:app --reload
```

Then open http://127.0.0.1:8000. Without `DATABASE_URL` the runs live in
memory, so permalinks work until you stop the server.

## Checking the code without spending anything

```bash
python3 -m pytest test_jobs.py -q
```

Eight checks with the analysis replaced by a stub: starting a run, polling it,
storing and replaying the result, the permalink, a failed crawl, an unexpected
crash, the daily cap, and a run abandoned by a restart. No network, no model
calls, no cost.
