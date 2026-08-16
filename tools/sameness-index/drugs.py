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


# ---------------------------------------------------------------------------
# The index behind the type-ahead.
#
# Ranking openFDA by how many listings a product has puts Oxygen, Nitrogen and
# Sodium Chloride at the top, because a commodity has hundreds of pack sizes.
# The signal for a promoted brand is simpler than a popularity score: a branded
# product has a brand name that is not merely its generic. Ozempic and
# Semaglutide differ; Oxygen and Oxygen do not.
#
# Built once, cached, and refreshed on a timer — a new brand launch is not an
# hourly event, and nobody should wait for a network call between keystrokes.
# ---------------------------------------------------------------------------

INDEX_PAGE = 1000          # openFDA's maximum per request
INDEX_MAX_PAGES = 40       # ~40k listings, comfortably the whole branded set
INDEX_TTL_SECONDS = 60 * 60 * 24 * 30


def _is_branded(row):
    """A brand, rather than a commodity sold under its own chemical name."""
    brand = (row.get("brand_name") or "").strip()
    generic = (row.get("generic_name") or "").strip()
    if len(brand) < 3:
        return False
    if (row.get("marketing_category") or "").upper() not in BRANDED_CATEGORIES:
        return False
    if not (row.get("pharm_class") or []):
        return False
    a = re.sub(r"[^a-z]", "", brand.lower())
    b = re.sub(r"[^a-z]", "", generic.lower())
    if not a or a == b:
        return False
    # "Semaglutide Injection" against generic "Semaglutide" is still the
    # molecule wearing a coat, not a brand.
    return not (b and a.startswith(b))


async def build_index(http, on_progress=None):
    """Every branded prescription medicine openFDA knows about.

    Roughly thirty requests, run once. Returns a list ordered by how many
    listings each brand has, which is a reasonable proxy for how widely it is
    actually dispensed and therefore how likely somebody is typing it.
    """
    found = {}
    for page in range(INDEX_MAX_PAGES):
        rows = await _query(http, "ndc", {
            "search": 'marketing_category:"NDA" OR marketing_category:"BLA"',
            "limit": INDEX_PAGE,
            "skip": page * INDEX_PAGE,
        })
        if not rows:
            break
        for r in rows:
            if not _is_branded(r):
                continue
            name = tidy_brand(_strip_dose_form(r.get("brand_name", "")))
            if len(name) < 3:
                continue
            k = name.lower()
            if k not in found:
                cls = next((c for c in (r.get("pharm_class") or []) if c.endswith("[EPC]")), "")
                found[k] = {
                    "brand": name,
                    "generic": tidy_brand((r.get("generic_name") or "").strip()),
                    "company": (r.get("labeler_name") or "").strip(),
                    "cls": cls.replace(" [EPC]", ""),
                    "n": 0,
                }
            found[k]["n"] += 1
        if on_progress:
            on_progress(len(found), page + 1)
        if len(rows) < INDEX_PAGE:
            break
    out = sorted(found.values(), key=lambda v: -v["n"])
    return out


def score(query, entry):
    """How well an entry answers what is being typed.

    Prefix first, because that is what somebody typing a name they know is
    doing. Then the generic, so typing "semaglutide" finds Ozempic. Then a
    fuzzy pass, so "ozempick" and "trulicty" still land — a person half
    remembering a brand name is the normal case, not the edge case.
    """
    from difflib import SequenceMatcher
    q = query.strip().lower()
    if not q:
        return 0
    b = entry["brand"].lower()
    g = (entry.get("generic") or "").lower()
    # Clean bands, with no length term in them: two prefix matches have to tie
    # so that the tiebreak below — how widely the drug is dispensed — decides.
    if b.startswith(q):
        return 1000
    if any(w.startswith(q) for w in b.split()):
        return 900
    if g.startswith(q):
        return 700
    if q in b:
        return 600
    if q in g or q in (entry.get("cls") or "").lower():
        return 400
    # Somebody who remembers the company but not the brand is still looking for
    # the brand: "lilly" should offer Trulicity and Mounjaro.
    c = (entry.get("company") or "").lower()
    if c.startswith(q) or any(w.startswith(q) for w in c.split()):
        return 350
    if len(q) >= 4:
        r = SequenceMatcher(None, q, b[:len(q) + 3]).ratio()
        if r >= 0.72:
            return int(300 * r)
    return 0


def search_index(index, query, limit=8):
    """Best match first, then the drug more people are actually taking.

    Ranking a tie by name length put Ozobax above Ozempic for "oz", which is
    not what anybody typing two letters means. Listing count is a rough proxy
    for how widely a product is dispensed, and a good enough one to break ties.
    """
    scored = ((score(query, e), e.get("n", 0), e) for e in index)
    hits = sorted((s for s in scored if s[0] > 0),
                  key=lambda s: (-s[0], -s[1], len(s[2]["brand"])))
    return [e for _s, _n, e in hits[:limit]]


# The therapy areas a brand lead would actually name. Pharmacologic class is a
# controlled vocabulary but it is written for pharmacists — nobody types
# "Glucagon-Like Peptide-1 Receptor Agonist" into a box. This is the language of
# the room, and the field fills itself from the drug in most cases anyway.
THERAPY_AREAS = [
    "Type 2 diabetes", "Type 1 diabetes", "Obesity and weight management",
    "Atopic dermatitis", "Plaque psoriasis", "Psoriatic arthritis", "Acne",
    "Vitiligo", "Alopecia areata", "Hidradenitis suppurativa", "Chronic urticaria",
    "Rheumatoid arthritis", "Axial spondyloarthritis", "Lupus", "Gout", "Osteoporosis",
    "Crohn's disease", "Ulcerative colitis", "Coeliac disease", "IBS",
    "Asthma", "COPD", "Cystic fibrosis", "Idiopathic pulmonary fibrosis",
    "Multiple sclerosis", "Parkinson's disease", "Alzheimer's disease", "Epilepsy",
    "Migraine", "Narcolepsy", "ADHD", "Depression", "Schizophrenia", "Bipolar disorder",
    "Anxiety", "Insomnia",
    "Breast cancer", "Lung cancer", "Prostate cancer", "Colorectal cancer",
    "Melanoma", "Multiple myeloma", "Leukaemia", "Lymphoma", "Ovarian cancer",
    "Bladder cancer", "Renal cell carcinoma", "Pancreatic cancer",
    "Heart failure", "Hypertension", "Atrial fibrillation", "Hyperlipidaemia",
    "Pulmonary arterial hypertension", "Chronic kidney disease", "Anaemia",
    "HIV", "Hepatitis B", "Hepatitis C", "COVID-19", "Influenza", "RSV",
    "Haemophilia", "Sickle cell disease", "Thalassaemia",
    "Macular degeneration", "Diabetic macular oedema", "Glaucoma", "Dry eye",
    "Endometriosis", "Menopause", "Contraception", "Fertility",
    "Rare disease", "Gene therapy", "Vaccines", "Transplant rejection",
    "Chronic pain", "Osteoarthritis", "Smoking cessation", "Opioid dependence",
]


# What people type versus what the label calls it. A brand lead says eczema and
# the register says atopic dermatitis; both should find the same thing.
AREA_SYNONYMS = {
    "eczema": "Atopic dermatitis",
    "psoriasis": "Plaque psoriasis",
    "ra": "Rheumatoid arthritis",
    "as": "Axial spondyloarthritis",
    "ankylosing spondylitis": "Axial spondyloarthritis",
    "ms": "Multiple sclerosis",
    "ibd": "Crohn's disease",
    "inflammatory bowel": "Crohn's disease",
    "uc": "Ulcerative colitis",
    "t2d": "Type 2 diabetes",
    "t1d": "Type 1 diabetes",
    "diabetes": "Type 2 diabetes",
    "weight loss": "Obesity and weight management",
    "obesity": "Obesity and weight management",
    "hypercholesterolaemia": "Hyperlipidaemia",
    "cholesterol": "Hyperlipidaemia",
    "high blood pressure": "Hypertension",
    "af": "Atrial fibrillation",
    "ckd": "Chronic kidney disease",
    "amd": "Macular degeneration",
    "dme": "Diabetic macular oedema",
    "dementia": "Alzheimer's disease",
    "hair loss": "Alopecia areata",
    "hives": "Chronic urticaria",
    "pah": "Pulmonary arterial hypertension",
    "ipf": "Idiopathic pulmonary fibrosis",
    "spinal muscular atrophy": "Rare disease",
    "nash": "Rare disease",
}


def search_areas(query, limit=8):
    from difflib import SequenceMatcher
    q = query.strip().lower()
    if not q:
        return THERAPY_AREAS[:limit]
    out = []
    for word, area in AREA_SYNONYMS.items():
        if word.startswith(q) or q.startswith(word):
            out.append((1100 - len(area), area))
    for a in THERAPY_AREAS:
        low = a.lower()
        if low.startswith(q):
            out.append((1000 - len(a), a))
        elif any(w.startswith(q) for w in low.replace("-", " ").split()):
            out.append((900 - len(a), a))
        elif q in low:
            out.append((700 - len(a), a))
        elif len(q) >= 4:
            # Compare word by word as well as whole-string: "diabetis" against
            # "type 2 diabetes" scores badly as a whole and perfectly against
            # the word somebody was actually reaching for.
            best = max([SequenceMatcher(None, q, low).ratio()] +
                       [SequenceMatcher(None, q, w).ratio()
                        for w in low.replace("-", " ").replace("'", " ").split() if len(w) > 3])
            if best >= 0.7:
                out.append((int(300 * best), a))
    out.sort(key=lambda x: -x[0])
    seen, keep = set(), []
    for _s, a in out:
        if a not in seen:
            seen.add(a)
            keep.append(a)
    return keep[:limit]


def short_indication(text):
    """The disease out of a paragraph of indications-and-usage."""
    t = re.sub(r"^.*?indicated\s+(?:for(?:\s+the)?(?:\s+treatment\s+of)?|to|in)\s+", "", text, flags=re.I)
    t = re.split(r"[.;]", t)[0]
    return re.sub(r"\s+", " ", t).strip()[:110] or text[:110]


def area_matches(typed, label_text, prof=None):
    """Does the therapy area somebody typed have anything to do with the drug?

    Deliberately generous — it only has to find one meaningful word in common,
    because a label says "moderate-to-severe plaque psoriasis" where a brand
    lead types "psoriasis". It is looking for a category error, not a
    difference of phrasing.
    """
    stop = {"the", "and", "for", "with", "adults", "adult", "patients", "patient",
            "treatment", "moderate", "severe", "chronic", "acute", "years", "age",
            "older", "type", "disease", "care", "use", "who", "have", "been"}
    words = {w for w in re.findall(r"[a-z]{4,}", typed.lower()) if w not in stop}
    if not words:
        return True
    hay = (label_text or "").lower()
    if prof:
        hay += " " + " ".join(prof.get("classes") or []).lower() + " " + (prof.get("generic") or "").lower()
    for w in words:
        # A stem match, so "psoriasis" finds "psoriatic" and "diabetes" finds
        # "diabetic".
        if w[:6] in hay:
            return True
    return False
