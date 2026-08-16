"""
Sameness Index — the drug database.

The finder used to ask a model to name a brand's competitors and guess their
web addresses, then fetch twenty speculative URLs to see which existed. That is
slow, and a model asked for a fact it does not have will produce something
shaped like one: it is how a run ended up reading Boehringer's corporate portal
instead of Jardiance.

This asks openFDA instead. A brand resolves to its generic and its established
pharmacologic class; the class resolves to every other branded product in it.
Those are facts on a label, not recollections. The model's job afterwards is
only to say which of the real competitors belong in the same conversation —
judgement it is good at, applied to a list it did not invent.

openFDA needs no key at the volume this runs at (240 requests a minute without
one, and a run makes two). It is the FDA's own data, so it is US-scoped: a
category outside the US falls back to the model, and the report says so.

  https://open.fda.gov/apis/drug/ndc/
  https://open.fda.gov/apis/drug/label/
"""

import asyncio
import re

BASE = "https://api.fda.gov/drug"
TIMEOUT = 20

# A branded product has its own application. ANDA is a generic of somebody
# else's brand, and "unapproved" covers the long tail of grandfathered products
# — neither is competing on messaging, which is what this measures.
BRANDED_CATEGORIES = ("NDA", "BLA", "NDA AUTHORIZED GENERIC")

# openFDA shouts its brand names. The reader should not be shouted at, and
# these appear on the page.
_ALL_CAPS = re.compile(r"^[A-Z0-9][A-Z0-9 \-'/.]*$")


def tidy_brand(name):
    """OZEMPIC -> Ozempic, but leave a name that is already mixed case alone."""
    n = (name or "").strip()
    if not n:
        return ""
    if _ALL_CAPS.match(n):
        # Title-case each word, but keep short all-caps tokens that are almost
        # certainly initialisms rather than words (XR, HFA, ER).
        parts = []
        for w in n.split():
            parts.append(w if (len(w) <= 3 and w.isalpha()) else w.capitalize())
        n = " ".join(parts)
    return n


def _strip_dose_form(name):
    """"Ozempic 0.5 mg/dose" and "Ozempic Pen" are the same brand."""
    n = re.sub(r"\s*\(.*?\)\s*", " ", name)
    n = re.sub(r"\b\d+(\.\d+)?\s*(mg|mcg|g|ml|%|units?)\b.*$", "", n, flags=re.I)
    n = re.sub(r"\b(injection|tablets?|capsules?|solution|cream|ointment|gel|foam|"
               r"spray|pen|autoinjector|prefilled|syringe|kit|xr|er|sr|odt)\b.*$", "", n, flags=re.I)
    return re.sub(r"[\s,\-]+$", "", n).strip()


class _Cache:
    """One process, one memory. openFDA is stable and a category is often run
    more than once in a sitting; there is no reason to ask twice."""

    def __init__(self):
        self.data = {}
        self.lock = asyncio.Lock()

    async def get_or_set(self, key, make):
        async with self.lock:
            if key in self.data:
                return self.data[key]
        value = await make()
        async with self.lock:
            self.data[key] = value
        return value


_cache = _Cache()


async def _query(http, path, params):
    """One openFDA call. A miss is a 404 there, which is not an error."""
    try:
        r = await http.get(f"{BASE}/{path}.json", params=params, timeout=TIMEOUT)
    except Exception:
        return []
    if r.status_code == 404:
        return []
    if r.status_code != 200:
        return []
    try:
        return r.json().get("results", []) or []
    except Exception:
        return []


async def profile(http, brand):
    """What this brand is: generic name, company, and pharmacologic class.

    Returns None when openFDA has never heard of it — which is the answer for a
    brand outside the US, or a misspelling, and is worth saying out loud rather
    than papering over.
    """
    key = ("profile", brand.strip().lower())

    async def build():
        # The NDC directory is the register of what is actually marketed, which
        # is a better question than what has ever been labelled.
        rows = await _query(http, "ndc", {
            "search": f'brand_name:"{brand}"',
            "limit": 20,
        })
        if not rows:
            rows = await _query(http, "ndc", {
                "search": f'brand_name:{brand}',
                "limit": 20,
            })
        if not rows:
            return None

        classes, generics, labelers = [], [], []
        for r in rows:
            for c in r.get("pharm_class", []) or []:
                if c.endswith("[EPC]") and c not in classes:
                    classes.append(c)
            g = (r.get("generic_name") or "").strip()
            if g and g not in generics:
                generics.append(g)
            lab = (r.get("labeler_name") or "").strip()
            if lab and lab not in labelers:
                labelers.append(lab)

        return {
            "brand": tidy_brand(rows[0].get("brand_name") or brand),
            "generic": generics[0] if generics else "",
            "company": labelers[0] if labelers else "",
            # A product can sit in more than one class; the first is the one the
            # label leads with.
            "classes": classes,
            "route": (rows[0].get("route") or [""])[0] if rows[0].get("route") else "",
        }

    return await _cache.get_or_set(key, build)


async def peers(http, prof, limit=40):
    """Every other branded product sharing this one's pharmacologic class.

    Class, not indication, on purpose. Two brands in the same class are
    competing for the same prescription whatever their labels say, and class is
    a field on the record rather than a judgement about wording.
    """
    if not prof or not prof.get("classes"):
        return []
    key = ("peers", "|".join(prof["classes"]))

    async def build():
        found = {}
        for cls in prof["classes"][:2]:
            rows = await _query(http, "ndc", {
                "search": f'pharm_class:"{cls}"',
                "limit": 500,
            })
            for r in rows:
                if (r.get("marketing_category") or "").upper() not in BRANDED_CATEGORIES:
                    continue
                raw = (r.get("brand_name") or "").strip()
                if not raw:
                    continue
                name = tidy_brand(_strip_dose_form(raw))
                if len(name) < 3:
                    continue
                k = name.lower()
                # A brand appears once per pack size; keep the first and count
                # how much of the class it accounts for.
                if k not in found:
                    found[k] = {
                        "brand": name,
                        "generic": (r.get("generic_name") or "").strip(),
                        "company": (r.get("labeler_name") or "").strip(),
                        "n": 0,
                    }
                found[k]["n"] += 1
        out = [v for v in found.values() if v["brand"].lower() != prof["brand"].lower()]
        # The products with the most listings are the ones actually on shelves.
        out.sort(key=lambda v: -v["n"])
        return out[:limit]

    return await _cache.get_or_set(key, build)


async def category_of(http, prof):
    """A one-line description of what this class treats, from the label.

    Used as the category when the user has not said what it is. It comes from
    the indications section of a real label rather than from recollection.
    """
    if not prof:
        return ""
    key = ("indication", prof.get("brand", "").lower())

    async def build():
        rows = await _query(http, "label", {
            "search": f'openfda.brand_name:"{prof["brand"]}"',
            "limit": 1,
        })
        if not rows:
            return ""
        text = " ".join(rows[0].get("indications_and_usage", []) or [])
        text = re.sub(r"\s+", " ", text).strip()
        # The first sentence that names a disease is almost always the one.
        m = re.search(r"(?:indicated (?:for|to|in)[^.]{10,200})\.", text, re.I)
        return (m.group(0) if m else text[:200]).strip()

    return await _cache.get_or_set(key, build)


# ---------------------------------------------------------------------------
# Where a brand's website probably lives.
#
# Only ever a starting point: every address is fetched and confirmed before it
# is shown to anyone, and confirmed addresses are remembered so the guessing
# happens once per brand rather than once per run.
# ---------------------------------------------------------------------------

def candidate_urls(brand, audience="patient"):
    slug = re.sub(r"[^a-z0-9]", "", brand.lower())
    if not slug:
        return []
    if audience == "hcp":
        return [
            f"https://www.{slug}hcp.com",
            f"https://{slug}hcp.com",
            f"https://www.{slug}.com/hcp",
            f"https://www.{slug}.com/healthcare-professionals",
            f"https://www.{slug}pro.com",
            f"https://hcp.{slug}.com",
            f"https://www.{slug}.com",
        ]
    return [
        f"https://www.{slug}.com",
        f"https://{slug}.com",
        f"https://www.{slug}.com/patient",
        f"https://www.{slug}.co.uk",
    ]
