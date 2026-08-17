"""
Sameness Index — where the evidence pictures live.

A screenshot is the strongest evidence the report has: the claim, highlighted,
on the competitor's own page, on a stated date. Which means it has to still be
there in six months, when somebody forwards the link to their boss. Three places
it could live, and only one of them survives that:

- **The Render disk.** Wiped on every deploy. A permalink whose pictures have
  vanished is worse than one that never had any.
- **Postgres.** Survives, but a run is twenty or thirty images and a database is
  the wrong shape for a few megabytes of JPEG each time — every image load would
  come back through the app, and the app is busy running the pipeline.
- **Supabase Storage.** A bucket, a public URL per object, served by a CDN and
  not by us. That is what this file talks to.

Uploaded with the service key, which never leaves the server. Read by anyone
with the link, which is the point — the report is meant to be forwarded.

Fails soft, deliberately and completely. No bucket configured, a refused
upload, a slow network: the run carries on and the report falls back to the
evidence links it has always had. A missing picture must never cost somebody
their analysis.

Set up:
    SUPABASE_URL          https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY  the service_role key, from the API settings page
    SAMENESS_SHOT_BUCKET  defaults to sameness-evidence

The bucket must be public. See DEPLOY.md.
"""

import os

import httpx

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
BUCKET = os.environ.get("SAMENESS_SHOT_BUCKET", "sameness-evidence")

# A screenshot that arrives at this size has gone wrong — a full-page capture of
# an infinite scroll, or a render of an error page. Not worth the bandwidth.
MAX_BYTES = 3_000_000


def configured():
    return bool(SUPABASE_URL and SERVICE_KEY)


def why_not():
    if SUPABASE_URL and SERVICE_KEY:
        return ""
    missing = [n for n, v in (("SUPABASE_URL", SUPABASE_URL),
                              ("SUPABASE_SERVICE_KEY", SERVICE_KEY)) if not v]
    return "not configured: " + ", ".join(missing)


def public_url(path):
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


async def put(http, path, data, content_type="image/jpeg"):
    """One object, uploaded. Returns its public URL, or "" if anything at all
    went wrong — including this not being set up, which is a normal state and
    not a failure worth a log line per image.
    """
    if not configured() or not data or len(data) > MAX_BYTES:
        return ""
    try:
        r = await http.post(
            f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}",
            content=data,
            headers={
                "Authorization": f"Bearer {SERVICE_KEY}",
                "apikey": SERVICE_KEY,
                "Content-Type": content_type,
                # A run id is unique, so a collision means a retry of the same
                # run and overwriting is the right answer.
                "x-upsert": "true",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
            timeout=30,
        )
        if r.status_code >= 300:
            return ""
    except Exception:
        return ""
    return public_url(path)


def path_for(run_id, brand, kind, n=0):
    """Predictable, sortable, and safe in a URL."""
    slug = "".join(c if c.isalnum() else "-" for c in brand.lower()).strip("-")[:40]
    return f"{run_id}/{slug}-{kind}{('-' + str(n)) if kind == 'quote' else ''}.jpg"
