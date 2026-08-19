"""
Sameness Index — why a site could not be read.

For months the answer to "why did that brand fail?" was a shrug and another
parsing fix. The crawl recorded a name and an address and nothing else, so every
theory about what was blocking us — the TLS fingerprint, the JavaScript, the
gates — was argued from how these systems generally work rather than from what
actually came back. Some of those fixes were right. There is no way to know
which, because nothing was measured.

This module measures. Given what the first request produced — the status, the
response headers, the first few thousand characters — it names the reason in
terms that point at a fix:

    robots     the site asked not to be read. Nothing to fix, and nothing to do.
    geo        a wall for the wrong country. We are reading US brands from
               Frankfurt; this is the one we did to ourselves.
    challenge  bot management, and which vendor. Reputation, not rendering —
               no amount of stealth gets past an edge that has already decided.
    blocked    refused, vendor unknown.
    gone       the address is wrong. A discovery problem, not an access one.
    shell      we got in and there was nothing to read. This is the one the
               browser was built for; if it still happens, the browser failed.
    server     their side broke.
    network    nothing came back at all.

The point of the split is that the four causes need four different answers, and
until now they all looked identical in the report: "could not be read".
"""

import re

# Bot management leaves fingerprints, in headers and in the body of the page it
# serves instead of yours. Named individually because the vendor tells you what
# you are up against: Cloudflare and DataDome will often let a real browser
# through eventually, Akamai and Imperva score the address and stop caring.
VENDORS = [
    ("Cloudflare", ("cf-ray", "cf-mitigated", "cf-chl-bypass"),
     ("just a moment", "cf-browser-verification", "__cf_chl", "cf_chl_opt",
      "attention required! | cloudflare", "enable javascript and cookies to continue",
      "checking your browser before accessing")),
    ("Akamai", ("x-akamai-transformed", "akamai-grn", "x-akamai-request-id"),
     ("access denied", "reference&#32;#", "errors.edgesuite.net",
      "you don't have permission to access", "akamai")),
    ("Imperva", ("x-iinfo", "x-cdn"),
     ("incapsula incident id", "_incapsula_resource", "powered by imperva")),
    ("PerimeterX", ("x-px",),
     ("px-captcha", "perimeterx", "human.px")),
    ("DataDome", ("x-datadome", "x-dd-b"),
     ("datadome", "geo.captcha-delivery.com")),
    ("Kasada", ("x-kpsdk-ct", "x-kpsdk-cd"), ("kpsdk", "kasada")),
]

# A wall, not a gate. A gate offers a way through and the crawler clicks it; a
# wall states that the site is not for you and offers nothing. The difference
# matters because one is a bug in our gate handling and the other is a fact
# about where the server thinks we are.
GEO_WALL = (
    "not intended for residents", "intended only for residents",
    "intended for us residents", "intended for residents of the united states",
    "only for residents of", "not available in your country",
    "not available in your region", "this site is not intended for",
    "content is not available in your location", "unavailable in your country",
    "you are attempting to access this site from outside",
    "please visit the website for your country",
    "restricted to visitors from", "access from your location",
)

# A wall that wants a person, not a country.
LOGIN_WALL = ("sign in to continue", "log in to continue", "please log in",
              "registration required", "members only")

CHALLENGE_STATUSES = {401, 403, 405, 406, 409, 429}
SERVER_STATUSES = {500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526}


def _vendor(headers, body, refused):
    """Who refused us, if anyone did.

    A header alone convicts nobody. Cloudflare fronts half the web and most of
    it serves us perfectly well, so `cf-ray` on a 200 with seven thousand words
    behind it is a CDN doing its job, not a wall. The header only names a vendor
    when the request was actually refused; the body markers stand on their own,
    because a challenge page says what it is.
    """
    hdr = " ".join(str(k) for k in (headers or {}))
    for name, header_keys, body_marks in VENDORS:
        if any(m in body for m in body_marks):
            return name
        if refused and any(k in hdr for k in header_keys):
            return name
    return ""


def classify(status, headers, body, chars_read=0, rendered=False):
    """Why this site could not be read. Returns (code, sentence).

    `body` is the first few thousand characters of whatever was served —
    lower-cased by this function, so the caller need not care. `chars_read` is
    how much readable text the crawl eventually recovered, which is what
    separates "we got in and it was empty" from "we never got in".
    """
    body = (body or "").lower()
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    vendor = _vendor(headers, body, refused=status in CHALLENGE_STATUSES)

    if status == 0:
        return "network", ("Nothing came back at all — the connection failed or timed out. "
                           "Usually the address is wrong or the host is refusing us outright.")

    if status in (404, 410):
        return "gone", ("That address does not exist. This is a discovery problem rather than "
                        "an access one: the brand's real site is somewhere else.")

    if status in SERVER_STATUSES and not vendor:
        return "server", f"Their server returned {status}. Their side, not ours; worth another run later."

    if any(m in body for m in GEO_WALL):
        return "geo", ("A wall for the wrong country, not a gate we can click through. "
                       "The service reads from Frankfurt and these are US brands, so the site "
                       "refuses before it shows anything.")

    if status in CHALLENGE_STATUSES or vendor:
        if vendor:
            return "challenge", (
                f"{vendor} bot management refused the connection. This is a judgement about "
                "where the request came from, not about how it was made — a datacentre address "
                "scores badly however convincing the browser is.")
        return "blocked", (f"Refused with {status}, and nothing identifies what refused it. "
                           "Most likely bot management we do not have a fingerprint for.")

    if any(m in body for m in LOGIN_WALL):
        return "login", ("Behind a login. Out of scope on purpose — the index reads public "
                         "pages only and does not hold anyone's credentials.")

    if chars_read < 400:
        if rendered:
            return "shell", ("We got in, rendered the page in a real browser, and there was still "
                             "nothing to read. Either the copy is entirely in images, or the site "
                             "served us a stub.")
        return "shell", ("We got in and the page was empty of words. The browser should have "
                         "caught this — worth checking why it was not used here.")

    return "ok", ""


# What each reason means for what to do next. Kept here rather than in the
# report so that the operator's view and the reader's view cannot drift apart.
FIXABLE = {
    "geo":       "Move the service to a US region.",
    "challenge": "Needs a residential or ISP address. Rendering will not fix it.",
    "blocked":   "Needs a residential or ISP address, probably.",
    "shell":     "Ours to fix — the browser did not do its job.",
    "gone":      "Ours to fix — the address discovery is wrong.",
    "network":   "Ours to check — address or timeout.",
    "server":    "Nobody's; try again later.",
    "robots":    "Nothing to fix. The site asked not to be read.",
    "login":     "Out of scope by design.",
}

READER_LABELS = {
    "robots":    "asked not to be read",
    "geo":       "not served to this location",
    "challenge": "blocked by bot protection",
    "blocked":   "blocked by bot protection",
    "gone":      "no site found at that address",
    "shell":     "nothing readable on the page",
    "server":    "the site was unavailable",
    "network":   "the site did not respond",
    "login":     "behind a login",
}
