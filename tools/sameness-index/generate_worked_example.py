"""
Generate worked_example.json — the golden fixture for the Sameness Index front end.

Ports the metrics from score.py unchanged, then adds what the front end needs
and the prototype did not carry: availability tiers with reasoning, plain-English
descriptions, findings with evidence routes, the verbal/visual cross-check, the
boundary rules, and the limitations.

Run: python3 generate_worked_example.py
"""

import json
import math
from collections import Counter
from itertools import combinations

from concepts import CONCEPTS, CODING, PROVENANCE
from corpus import VISUAL

BRANDS = list(CODING)
SPACE = list(CONCEPTS)

# ---------------------------------------------------------------------------
# Availability tiers. A strategist's read requiring MLR review, not legal
# advice. Tier values: open / frame_only / constrained / closed.
# ---------------------------------------------------------------------------

TIERS = {
    "C01": ("open", "Being steroid-free is a fact of the label. Building the lead benefit around avoiding steroids is a messaging decision, not a new claim. Every brand in the set already does it."),
    "C02": ("open", "Available to any brand whose label covers the age group it depicts. The reassurance itself needs no new endpoint."),
    "C03": ("open", "An audience decision. Addressing the parent rather than the patient requires nothing from the label."),
    "C04": ("constrained", "Cannot be claimed without time-to-effect data. Opzelura can make it because its trials measured that endpoint; any other brand would need the same evidence."),
    "C05": ("open", "Itch is measured in every pivotal trial in the category. Choosing to lead on it is a decision about message hierarchy, not a new claim."),
    "C06": ("open", "Clearance is the registrational endpoint for every product in the category. Presenting it as the goal is a matter of emphasis."),
    "C07": ("constrained", "Depends entirely on what the label says about duration of use. Opzelura's label specifies non-continuous use, so this territory is not open to it."),
    "C08": ("constrained", "Claiming use anywhere on the body needs either data in sensitive areas or a label broad enough to cover it. Without one of those it is an unsupported claim."),
    "C09": ("open", "Describing how the formulation feels is not an efficacy claim, and carries little regulatory weight."),
    "C10": ("open", "Carried by imagery and tone rather than by an outcome claim. Routine in consumer healthcare advertising."),
    "C11": ("open", "A decision about how relief is described. Nothing is claimed that the label does not already support."),
    "C12": ("open", "Acknowledging the emotional burden is disease education and invokes no endpoint."),
    "C13": ("open", "Borrowing the codes of another category is an art direction and tone decision. Awards are earned rather than claimed."),
    "C14": ("open", "The pharmacology is determined by the molecule, but building the brand story around it is a creative decision and needs no new substantiation."),
    "C15": ("open", "Copay and access programmes already exist. Whether they lead the messaging or sit three clicks down is a decision."),
    "C16": ("open", "The dosing is set by the label. Describing it as simple is a wording decision and attracts little scrutiny."),
    "C17": ("constrained", "Number-one and first-in-class claims need substantiation and exact wording, and are treated as comparative claims. Expect close review."),
    "C18": ("open", "Discussion guides, conversation starters and routes to an appointment involve no product claim at all."),
    "C19": ("constrained", "Requires durability data. Vtama can make this claim on the strength of its open-label extension study; without equivalent evidence the territory is not available."),
    "C20": ("constrained", "Needs demonstrated representation in the trial population. Worded carelessly it becomes a subgroup efficacy claim."),
    "X01": ("frame_only", "Sleep loss can be described in disease education, because it is the most consistently reported burden in moderate-to-severe disease. Claiming the product improves sleep would need a sleep endpoint, which none of these trials measured."),
    "X02": ("open", "An audience decision. Describing the parent's own lost sleep is disease education and requires no product claim."),
    "X03": ("frame_only", "The anxiety and depression that accompany the disease are well documented and can be described. Any suggestion the product improves mood would need an endpoint that does not exist."),
    "X04": ("open", "Disease education. The social cost of visible disease is documented and can be described without a product claim."),
    "X05": ("open", "An audience decision that sits well within every label in the set. The category addresses the child by convention, not by requirement."),
    "X06": ("constrained", "Legally possible as education about the drug class, but it criticises the current standard of care. Reviewers will read it as an implied comparative claim against corticosteroids."),
    "X07": ("open", "The bathing, emollient and laundry burden is documented. Describing the daily work of the regimen requires no claim."),
    "X08": ("frame_only", "The anxiety of not knowing when the next flare will come can be described. Suggesting the product resolves it implies a prevention claim, which needs maintenance data."),
    "X09": ("open", "A decision about where in the patient journey the communications begin. Addressing someone who feels dismissed is an audience choice, not a claim."),
    "X10": ("constrained", "Referring to everything the patient has already tried implies that named alternatives failed. Possible, but reviewed as a comparative claim."),
    "H01": ("constrained", "Steroid fear is documented throughout the adherence literature, but naming it criticises the first-line class every prescriber uses daily. Possible with careful wording, and subject to close review."),
    "H02": ("closed", "Topical steroid withdrawal is a clinical question the field has not settled. A promotional website cannot take a position on it."),
    "H03": ("frame_only", "Patients stopping treatment is documented and can be described as the clinical problem. Claiming your product solves it would need persistence data."),
    "H04": ("frame_only", "Maintenance can be described as the goal of therapy, because treatment guidelines already recommend it. Claiming the product delivers it needs a maintenance endpoint. Vtama's treatment-free-months data supports part of this argument."),
    "H05": ("closed", "Requires a trial measuring reduction in steroid use, which nobody has run. Not available without generating that data."),
    "H06": ("open", "An audience and channel decision. Paediatricians and GPs are the most steroid-hesitant prescribers and report the lowest guideline adherence, and no brand in the set addresses them directly."),
    "H07": ("open", "Supporting the consultation itself — shared decision-making and patient-reported outcomes — is recommended in the guidelines and involves no product claim."),
    "H08": ("open", "Coverage, prior authorisation and hub support can be brought to the front of the messaging without any clinical claim. The literature identifies cost and formulary restriction as the dominant barrier to prescribing."),
    "H09": ("constrained", "Stinging and burning appear in every label's adverse event table, so the evidence exists. Framing tolerability against the category would be treated as an implied comparative claim. Zoryve's 'gentle formulation' implies this without stating it."),
    "H10": ("open", "A decision about where the communications start. Disease education before diagnosis requires no product claim."),
}

# Position names as they appear on the map. concepts.py holds the analyst's
# shorthand; these are the same positions named for a brand lead reading the
# report, with no metaphor and no internal vocabulary.
LABELS = {
    "C01": "Steroid avoidance as the lead benefit",
    "C02": "Safety in young children",
    "C03": "The parent as the audience",
    "C04": "Speed of relief",
    "C05": "Itch as the primary symptom addressed",
    "C06": "Clear skin as the outcome",
    "C07": "Suitable for long-term use",
    "C08": "Use anywhere on the body",
    "C09": "How the formulation feels",
    "C10": "Return to everyday life",
    "C11": "Touch and closeness restored",
    "C12": "The emotional burden acknowledged",
    "C13": "Beauty and skincare codes rather than pharma",
    "C14": "The science as the brand story",
    "C15": "Affordability and access up front",
    "C16": "Simplicity and convenience",
    "C17": "Category leadership — first, only, number one",
    "C18": "Supporting the conversation with the doctor",
    "C19": "Time off treatment between flares",
    "C20": "Efficacy stated across all skin tones",
    "X01": "Sleep disruption as the primary burden",
    "X02": "The carer's own exhaustion",
    "X03": "Anxiety and depression alongside the disease",
    "X04": "Visible disease at school, work and in public",
    "X05": "Adults with persistent or late-onset disease",
    "X06": "The steroid cycle itself as the problem",
    "X07": "The daily work of the whole regimen",
    "X08": "Not knowing when the next flare will come",
    "X09": "Years of not being taken seriously",
    "X10": "The cost and effort of everything tried before",
    "H01": "Steroid fear named as the problem to solve",
    "H02": "Topical steroid withdrawal addressed directly",
    "H03": "Patients stopping treatment as the clinical problem",
    "H04": "Maintenance and flare prevention as the goal",
    "H05": "A measured reduction in steroid use",
    "H06": "Built for paediatricians and GPs",
    "H07": "Shared decision-making in the consultation",
    "H08": "Coverage and formulary friction as the real barrier",
    "H09": "Stinging and burning as the reason patients quit",
    "H10": "Reaching the patient before diagnosis",
}

DESCRIPTIONS = {
    "C01": "The brand's central promise is escaping steroids, not just the fact of being steroid-free.",
    "C02": "The site works to reassure that the product is safe for very young children.",
    "C03": "The parent or carer, not the patient, is treated as the person making the decision.",
    "C04": "How fast relief arrives is put forward as the reason to choose the brand.",
    "C05": "Itch, specifically, is cast as the thing the product defeats.",
    "C06": "Visibly clear skin is presented as what success looks like.",
    "C07": "The brand grants permission to keep using the product long term.",
    "C08": "Freedom to apply anywhere on the body, including sensitive areas.",
    "C09": "The feel and elegance of the formulation is sold as an experience.",
    "C10": "Getting ordinary life and its moments back is the promised outcome.",
    "C11": "Touch and physical closeness, restored, is the promised outcome.",
    "C12": "The emotional weight of living with the disease is named and acknowledged.",
    "C13": "The brand borrows the codes of beauty and skincare rather than pharma.",
    "C14": "The science or mechanism is the brand story, not background material.",
    "C15": "Affordability and access are placed in the foreground of the site.",
    "C16": "Simplicity and convenience of use are claimed as a benefit in themselves.",
    "C17": "Leadership of the category — number one, first, only — is the claim.",
    "C18": "The site equips the patient to have the conversation with their doctor.",
    "C19": "Life between flares — time off treatment — is part of the offer.",
    "C20": "Efficacy across all skin tones is stated, not just depicted.",
    "X01": "Sleep — the patient's ruined nights — treated as the primary burden the product answers.",
    "X02": "The carer's own exhaustion and lost sleep, addressed as a burden in its own right.",
    "X03": "The anxiety and depression that travel with the disease, named as part of it.",
    "X04": "The social cost of visible disease — school, work, being looked at.",
    "X05": "The adult who never grew out of it, or developed it late, as the primary audience.",
    "X06": "The steroid cycle itself — rebound, thinning, fear — named as the failure to escape.",
    "X07": "The sheer time and labour of the regimen: bathing, emollients, laundry.",
    "X08": "Not knowing when the next flare comes, and the anxiety of waiting for it.",
    "X09": "The years of being dismissed before anyone took the disease seriously.",
    "X10": "The money and effort already spent on everything that came before.",
    "H01": "Steroid fear in patients and parents, named directly as the problem a steroid-free option answers.",
    "H02": "The topical steroid withdrawal narrative circulating among patients, addressed head-on.",
    "H03": "Adherence — patients stopping — framed as the clinical problem, rather than efficacy.",
    "H04": "Keeping patients clear — maintenance and flare prevention — as the goal of therapy.",
    "H05": "A quantified reduction in total corticosteroid exposure as the offer to the prescriber.",
    "H06": "Built for the paediatrician and the GP — the prescribers who fear steroids most.",
    "H07": "Shared decision-making and patient-reported outcomes brought into the consultation.",
    "H08": "Coverage, formulary and prior-auth friction treated as the real barrier to prescribing.",
    "H09": "Stinging and burning on application, named as the reason patients quit.",
    "H10": "Meeting the patient earlier — before diagnosis, before the dermatologist.",
}

SOURCES = {
    "patient burden literature": "Established from patient burden literature — AD burden-of-illness studies; sleep disturbance, mental-health comorbidity and caregiver toll are documented independently of any brand's messaging. See sources.md (X-series).",
    "clinical barrier literature": "Established from clinical barrier literature — corticophobia, adherence and prescribing-barrier studies; guideline consensus on maintenance therapy. See sources.md (H-series). Congress transcripts are the stated upgrade path.",
    "observed in category": "Observed in category — at least one brand in the set makes this claim on its live site.",
}

META = {
    "tool": "Sameness Index",
    "version": "0.2",
    "category": "Non-steroidal topical therapies for atopic dermatitis",
    "market": "United States",
    "captured": "12 August 2026",
    "audience_note": "Patient and HCP sites, atopic dermatitis sections only. Opzelura HCP not captured in this run.",
    "brands": [
        {"name": "Zoryve", "company": "Arcutis", "url": "https://www.zoryve.com", "accent": "#FF686B"},
        {"name": "Vtama", "company": "Organon", "url": "https://www.vtama.com", "accent": "#1F5B4A"},
        {"name": "Opzelura", "company": "Incyte", "url": "https://www.opzelura.com", "accent": "#303030"},
        {"name": "Eucrisa", "company": "Pfizer", "url": "https://www.eucrisa.com", "accent": "#727270"},
    ],
}

BOUNDARY_RULES = [
    {"element": "“Steroid-free”", "layer": 2, "rule": "A factual property of the drug class, shared by everything in this category."},
    {"element": "“Steroid-free, so you can use it where steroids scare you”", "layer": 3, "rule": "What that fact is said to mean for the patient was written by someone."},
    {"element": "“Once daily”", "layer": 2, "rule": "The dosing is set by the label."},
    {"element": "“Simple once-daily treatment”", "layer": 3, "rule": "“Simple” is a claimed benefit, not a dosing fact."},
    {"element": "Age range (“down to 2 years”)", "layer": 2, "rule": "Set by the trials and the label."},
    {"element": "Photography of a two-year-old", "layer": 3, "rule": "Casting the youngest permitted age was a decision."},
    {"element": "Endpoint percentages", "layer": 2, "rule": "Trial results."},
    {"element": "Which endpoint appears first", "layer": 3, "rule": "Message hierarchy is a positioning decision."},
    {"element": "Clinical photography of lesions", "layer": 2, "rule": "A trial asset."},
    {"element": "Lifestyle photography", "layer": 3, "rule": "Commissioned and art directed."},
    {"element": "Explanation of how the drug works", "layer": 2, "rule": "Pharmacology."},
    {"element": "An analogy or metaphor for how it works", "layer": 3, "rule": "How the science is explained was a creative decision."},
]

LIMITATIONS = [
    "The percentages depend on how many territories were identified. Twenty were read off these four websites, so every one of them has a user by definition. The other twenty were established from published literature, and eighteen of those are unused — also close to by definition. Identify thirty from the literature rather than twenty and the usage figure falls from 55% to around 44% without anything changing in the market. Treat the percentages as a description of this list, not as a property of the category. The count of named, evidenced, unused territories does not move when the list length does, which is why it leads.",
    "Deciding what was determined by the label and what was a marketing decision is a judgement. The rules are published above, applied identically to every brand, and open to challenge. Different reasonable rules would change the numbers.",
    "Websites only. Congress activity, sales aids, field and MSL messaging, paid media and social are not included. This measures the public messaging each brand publishes, not its full commercial message.",
    "Four brands were analysed. The comparison is meaningful but sensitive to any one brand being unusual.",
    "A single capture, taken on 12 August 2026. This is a snapshot, not a trend.",
    "Eucrisa is not a like-for-like comparison. It was approved in 2016, its creative is materially older than the rest of the set, and its HCP site is currently serving an incomplete page in production. Treat it as a reference point for how the category used to communicate.",
    "Opzelura's HCP site was not captured in this run, so its prescriber-facing messaging is not represented.",
    "Deciding which territories a brand uses is a judgement made against the published rules. Every decision carries the exact wording from the site that produced it, so any of them can be checked and disagreed with.",
    "Availability ratings are a strategic assessment, not a regulatory one. Every position requires medical, legal and regulatory review before use.",
]

# ---------------------------------------------------------------------------
# The visual opportunity space.
#
# Built the same way the messaging space is, and from the same material: the
# art direction observations recorded for each brand's lead imagery in
# corpus.py. Every V-series territory is derived from those observations, and
# the evidence string under each brand is the observation itself — nothing here
# is asserted that the recorded reading does not support. The X and H series
# are established from the literature and depicted by nobody, which is the
# whole reason for having them: an inventory built only from what these four
# brands show would have a user for every territory by construction.
#
# The live pipeline builds this per category from the images. This fixture
# stands in for that, so the worked example exercises the same report.
# ---------------------------------------------------------------------------

VISUAL_SPACE = [
    {
        "id": "V01", "label": "A child as the central figure",
        "description": "The person the photography is built around is a child rather than an adult patient.",
        "tier": "constrained",
        "tier_reasoning": "Available only to a brand whose label covers the age it casts. The picture makes an age claim whether or not the copy does.",
        "coding": {
            "Zoryve": "Child with arms raised in a living room, one panel of a split triptych.",
            "Vtama": "A child lying face to face with an adult on a striped blanket.",
            "Opzelura": "A shirtless toddler on an adult's lap in a nursery.",
            "Eucrisa": "An infant in a nappy crawling towards the camera, smiling.",
        },
    },
    {
        "id": "V02", "label": "An ordinary domestic setting",
        "description": "The scene is a home — living room, bedroom, nursery — rather than a clinic or an outdoor location.",
        "tier": "open",
        "tier_reasoning": "A location decision. Nothing in the label or the evidence base constrains it.",
        "coding": {
            "Zoryve": "Living room interior across the triptych.",
            "Vtama": "A darkened bedroom.",
            "Opzelura": "A nursery.",
            "Eucrisa": "A domestic interior, floor level.",
        },
    },
    {
        "id": "V03", "label": "An adult and child touching",
        "description": "Two figures in contact, the touch itself carrying the emotional argument.",
        "tier": "open",
        "tier_reasoning": "A casting and direction decision. It claims nothing the label has to support.",
        "coding": {
            "Vtama": "Mother and child lying face to face, laughing, in contact on the blanket.",
            "Opzelura": "Mother reading to a toddler held on her lap.",
        },
    },
    {
        "id": "V04", "label": "Someone touching their own skin",
        "description": "The figure's hand is on their own face or body, making the skin the subject without showing disease.",
        "tier": "open",
        "tier_reasoning": "A direction decision that implies nothing about outcome, provided no result is shown.",
        "coding": {"Zoryve": "Adult woman with eyes closed, touching her own face."},
    },
    {
        "id": "V05", "label": "The disease visible on the model",
        "description": "Eczema is shown on the person in the lifestyle photography rather than in clinical imagery.",
        "tier": "constrained",
        "tier_reasoning": "Showing severity in a lifestyle image implies a baseline, and anything nearby implies a result. Expect close review of both the image and its captioning.",
        "coding": {"Opzelura": "Visible erythematous lesions on the toddler's torso and arms."},
    },
    {
        "id": "V06", "label": "Clear skin shown as the outcome",
        "description": "The central figure's skin is visibly clear, and the image is doing the work of the efficacy claim.",
        "tier": "constrained",
        "tier_reasoning": "An image of clear skin reads as a result. It needs the endpoint behind it and the disclaimer beside it.",
        "coding": {"Eucrisa": "Infant with clear skin, smiling, filling the frame."},
    },
    {
        "id": "V07", "label": "A range of skin tones in one execution",
        "description": "More than one skin tone appears across the lead imagery rather than a single casting.",
        "tier": "open",
        "tier_reasoning": "A casting decision, and the evidence base supports it. Nothing needs substantiating.",
        "coding": {"Zoryve": "Triptych casts a broad range of skin tones across its three panels."},
    },
    {
        "id": "V08", "label": "An adult as the central figure",
        "description": "An adult patient, rather than a parent or a child, is the person the photography is about.",
        "tier": "open",
        "tier_reasoning": "An audience decision inside every label in this set. Adults are the larger patient population.",
        "coding": {"Zoryve": "Adult male laughing and adult woman touching her face occupy two of the three panels."},
    },
    {
        "id": "V09", "label": "An illustrated overlay on the photography",
        "description": "Drawn elements sit over the image — clouds, stars, marks — softening the register.",
        "tier": "open",
        "tier_reasoning": "A treatment decision with no claim attached.",
        "coding": {"Opzelura": "Illustrated cloud and star overlays across the hero."},
    },
    {
        "id": "V10", "label": "Expressive display typography as the graphic device",
        "description": "The type itself carries the art direction, in place of a graphic motif.",
        "tier": "open",
        "tier_reasoning": "A design decision. Nothing to substantiate.",
        "coding": {
            "Vtama": "Gradient display typography running orange to magenta to violet.",
            "Opzelura": "Condensed serif display type.",
        },
    },
    {
        "id": "V11", "label": "Badges and roundels carrying the claims",
        "description": "Claims are set in circular badges over the imagery rather than in body copy.",
        "tier": "open",
        "tier_reasoning": "A layout decision. The claims inside the badges carry their own requirements; the device does not.",
        "coding": {
            "Zoryve": "Allure and Glamour beauty award roundels sit in the hero.",
            "Eucrisa": "Badge system reading '3 months & up FDA approved', '100% steroid free', 'works at and below'.",
        },
    },
    {
        "id": "V12", "label": "Borrowing the codes of beauty and skincare",
        "description": "The photography, awards and endorsements read as a cosmetics brand rather than a prescription medicine.",
        "tier": "open",
        "tier_reasoning": "A register decision. Awards are earned rather than claimed, and the borrow itself substantiates nothing.",
        "coding": {"Zoryve": "Beauty-press award roundels and celebrity endorsement below the fold."},
    },
    {
        "id": "V13", "label": "The product pack in frame",
        "description": "The tube or bottle appears inside the lifestyle photography rather than in a separate pack shot.",
        "tier": "open",
        "tier_reasoning": "A composition decision, subject to the usual requirements on how a pack is shown.",
        "coding": {"Opzelura": "Product tube visible within the nursery scene."},
    },
    {
        "id": "X01", "label": "The itch, and scratching",
        "description": "The dominant symptom of the disease, shown as it is experienced rather than named in copy.",
        "tier": "frame_only",
        "tier_reasoning": "Itch can be depicted as part of the disease. An image implying it is resolved would need the endpoint that supports it.",
        "coding": {},
    },
    {
        "id": "X02", "label": "Night waking and lost sleep",
        "description": "The night-time scene the burden literature describes — the patient or the parent awake.",
        "tier": "frame_only",
        "tier_reasoning": "Sleep loss is documented and can be depicted as part of the disease. Showing it resolved would need a sleep endpoint none of these trials measured.",
        "coding": {},
    },
    {
        "id": "X03", "label": "The daily routine of emollients and bathing",
        "description": "The work the regimen takes, shown as an ordinary domestic task.",
        "tier": "open",
        "tier_reasoning": "Disease education. Depicting the routine claims nothing about the product.",
        "coding": {},
    },
    {
        "id": "X04", "label": "An older adult with the disease",
        "description": "A central figure who reads as over fifty, rather than a child or a young adult.",
        "tier": "open",
        "tier_reasoning": "A casting decision inside every label in the set. The disease does not stop at forty.",
        "coding": {},
    },
    {
        "id": "X05", "label": "A school or workplace setting",
        "description": "The public settings where visible symptoms are most often described as difficult.",
        "tier": "open",
        "tier_reasoning": "A location decision. Nothing about it requires substantiation.",
        "coding": {},
    },
    {
        "id": "H01", "label": "Eczema on darker skin",
        "description": "The disease shown as it presents on darker skin tones, where it looks different and is recognised later.",
        "tier": "constrained",
        "tier_reasoning": "Depicting disease carries the same requirements whatever the skin tone. The reason nobody does it is not that the tier is high.",
        "coding": {},
    },
    {
        "id": "H02", "label": "The hands, the most-affected site",
        "description": "Hand involvement, which the literature records as both the commonest visible site and the hardest to conceal.",
        "tier": "constrained",
        "tier_reasoning": "A body site shown is a body site claimed. It needs the label and the data to cover it.",
        "coding": {},
    },
    {
        "id": "H03", "label": "Face and eyelid involvement",
        "description": "The sites patients report as most distressing and clinicians treat most cautiously.",
        "tier": "constrained",
        "tier_reasoning": "Sensitive-site depiction implies sensitive-site use, which needs the label behind it.",
        "coding": {},
    },
    {
        "id": "H04", "label": "A clinician in the frame",
        "description": "The consultation itself, rather than the patient alone at home.",
        "tier": "open",
        "tier_reasoning": "A casting decision. It makes no claim, and it is routine elsewhere in healthcare advertising.",
        "coding": {},
    },
]

VISUAL_SOURCES = {
    "observed in category": "Observed in category — recorded in the art direction reading of at least one brand's lead imagery.",
    "patient burden literature": "Established from patient burden literature — AD burden-of-illness and lived-experience studies on itch, sleep loss, the daily regimen and where the disease is seen. See sources.md (X-series).",
    "clinical barrier literature": "Established from representation and barrier literature — presentation and recognition in darker skin, body-site distribution, and the consultation itself. See sources.md (H-series).",
}

FINDINGS = [
    {
        "text": "All four brands build their core message from the same three elements: steroid avoidance as the lead benefit, the parent as the audience, and paediatric reassurance. Four different molecules, one shared message hierarchy.",
        "refs": ["C01", "C03", "C02"],
    },
    {
        "text": "The best-evidenced patient needs in this disease appear in nobody's messaging. Sleep disruption, caregiver exhaustion and the anxiety and depression comorbidity are the most consistently documented burdens in the literature, and not one brand builds a message on any of them.",
        "refs": ["X01", "X02", "X03"],
    },
    {
        "text": "All four brands state that they are steroid-free. None of them addresses why a patient or parent would care. Steroid fear is documented throughout the clinical literature as a main reason first-line treatment fails, and the category states the product attribute without ever making the patient argument.",
        "refs": ["H01", "C01", "X06"],
    },
    {
        "text": "Differentiation present in the copy is absent from the imagery. All four brand heroes show an everyday domestic scene with a child, and Vtama — which has the most distinctive verbal positioning in the set, built on science — makes the same three art direction decisions as Opzelura.",
        "refs": ["visual:V01", "visual:V02", "visual:V03"],
    },
    {
        "text": "The art direction is the more converged of the two dimensions. Ten of the twenty-two visual territories are used by nobody in this set, including the itch itself, the night waking the burden literature records, an adult over fifty, and how the disease presents on darker skin.",
        "refs": ["visual:VX01", "visual:VX02", "visual:VX04", "visual:VH01"],
    },
    {
        "text": "Treatment guidelines point towards maintenance and flare prevention, and almost no brand messaging follows. Vtama's treatment-free-months claim is the only partial move in that direction, and the stronger version — a quantified reduction in steroid use — is unavailable to everyone until someone runs the trial to support it.",
        "refs": ["H04", "C19", "H05"],
    },
]


def r0(x):
    """Round half up. Python breaks ties to even and JavaScript rounds half up,
    so a score landing on .5 disagreed with the page that recalculated it."""
    return int(math.floor(float(x) + 0.5))


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else 0.0


def build():
    c = Counter()
    for b in BRANDS:
        c.update(CODING[b].keys())

    occupied = [k for k in SPACE if c[k] > 0]
    crowded = [k for k in occupied if c[k] > len(BRANDS) / 2]
    contested = [k for k in occupied if c[k] > 1]
    sole = [k for k in occupied if c[k] == 1]
    empty = [k for k in SPACE if c[k] == 0]
    open_empty = [k for k in empty if TIERS[k][0] == "open"]

    positions = []
    for cid in SPACE:
        claimers = [b for b in BRANDS if cid in CODING[b]]
        tier, reasoning = TIERS[cid]
        positions.append({
            "id": cid,
            "label": LABELS.get(cid, CONCEPTS[cid]),
            "analyst_label": CONCEPTS[cid],
            "description": DESCRIPTIONS[cid],
            "provenance": PROVENANCE[cid],
            "source": SOURCES[PROVENANCE[cid]],
            "tier": tier,
            "tier_reasoning": reasoning,
            "claimers": claimers,
            "n": len(claimers),
            "receipts": {b: CODING[b][cid] for b in claimers},
        })

    pw = {f"{a} / {b}": round(jaccard(CODING[a], CODING[b]), 3)
          for a, b in combinations(BRANDS, 2)}

    brand_position = {}
    crowded_set = set(crowded)
    for b in BRANDS:
        own = set(CODING[b])
        unique = {x for x in own if c[x] == 1}
        brand_position[b] = {
            "claimed": len(own),
            "space_used": round(len(own) / len(SPACE), 3),
            "uniquely_owned": sorted(unique),
            "n_unique": len(unique),
            "ownership": round(len(unique) / len(own), 3) if own else 0.0,
            "crowding": round(len(own & crowded_set) / len(crowded_set), 3) if crowded_set else 0.0,
        }

    # The visual inventory, coded exactly as the messaging one is.
    visual_brands = list(VISUAL)
    vid_of = lambda t: t["id"] if t["id"][0] == "V" else "V" + t["id"]
    visual_coding = {b: {vid_of(t): t["coding"][b] for t in VISUAL_SPACE if b in t["coding"]}
                     for b in visual_brands}
    visual_positions = []
    for t in VISUAL_SPACE:
        prov = ("observed in category" if t["id"][0] == "V"
                else "patient burden literature" if t["id"][0] == "X"
                else "clinical barrier literature")
        claimers = [b for b in visual_brands if b in t["coding"]]
        # Namespaced with a leading V: the messaging inventory already has an
        # X01 and an H01, and an id has to identify one territory on the page.
        vid = t["id"] if t["id"][0] == "V" else "V" + t["id"]
        visual_positions.append({
            "id": vid,
            "label": t["label"],
            "description": t["description"],
            "provenance": prov,
            "source": VISUAL_SOURCES[prov],
            "tier": t["tier"],
            "tier_reasoning": t["tier_reasoning"],
            "visual": True,
            "claimers": claimers,
            "n": len(claimers),
            "receipts": {b: t["coding"][b] for b in claimers},
        })
    visual_positions.sort(key=lambda p: (-p["n"], p["id"]))

    # The convergence score. For one brand, the share of its territories a
    # rival also uses; for the category, the mean across brands. Identical
    # calculation over each inventory, and the headline is the mean of the two.
    def convergence(items, pool):
        per = []
        for b in pool:
            used = [p for p in items if b in p["claimers"]]
            shared = [p for p in used if len(p["claimers"]) > 1]
            per.append({
                "brand": b, "used": len(used), "shared": len(shared),
                "alone": len(used) - len(shared),
                "pct": r0(len(shared) / len(used) * 100) if used else 0,
                "shared_ids": [p["id"] for p in shared],
                "alone_ids": [p["id"] for p in used if len(p["claimers"]) == 1],
            })
        return {"per": per, "mean": r0(sum(p["pct"] for p in per) / len(per)) if per else 0}

    conv_msg = convergence(positions, BRANDS)
    conv_img = convergence(visual_positions, visual_brands)
    overall = r0((conv_msg["mean"] + conv_img["mean"]) / 2)
    bands = [
        (40, "Distinct", "good", "Brands are saying different things. There is still advantage available inside the current frame."),
        (60, "Converging", "mid", "The category is drifting together. Differentiation still exists, but it thins with every cycle."),
        (80, "Converged", "bad", "Most of what each brand says, a rival also says. Messaging no longer separates the field."),
        (101, "Indistinguishable", "bad", "The category speaks with one voice. Share of voice is the only lever left inside this frame."),
    ]
    to, bname, bcls, bnote = next(b for b in bands if overall < b[0])
    convergence_block = {
        "overall": overall,
        "band": {"name": bname, "cls": bcls, "note": bnote},
        "messaging": conv_msg,
        "imagery": conv_img,
        "imagery_brands": visual_brands,
        "basis": ("For each brand, the share of its territories that at least one rival also uses. The category "
                  "score is the mean across the brands analysed, calculated the same way for messaging and for "
                  "imagery, and the headline is the mean of the two."),
        "bands_note": ("Under 40 distinct, 40 to 59 converging, 60 to 79 converged, 80 and above indistinguishable. "
                       "Scores compare within a category over time, not between categories of different size."),
    }

    # ---------------------------------------------------------------------
    # Distance from the category centre.
    #
    # The centre is what most of the category does: for each territory anyone
    # uses, the majority behaviour. A brand's distance is the share of those
    # territories where it departs from the majority — either by using
    # something most brands do not, or by declining something most brands do.
    #
    # Measured over territories anyone uses (not all 40), because the 18 nobody
    # touches carry no information about how brands differ from each other.
    # Majority means more than half, so at four brands there is no tie to break.
    # ---------------------------------------------------------------------
    occupied_ids = [k for k in SPACE if c[k] > 0]
    centre = []
    for b in BRANDS:
        departures = [
            k for k in occupied_ids
            if (k in CODING[b]) != (c[k] > len(BRANDS) / 2)
        ]
        centre.append({
            "brand": b,
            "distance": round(len(departures) / len(occupied_ids), 3),
            "departures": len(departures),
            "of": len(occupied_ids),
            "departure_ids": departures,
        })
    centre.sort(key=lambda r: -r["distance"])

    # ---------------------------------------------------------------------
    # The two-axis plot.
    #
    # Both axes are the same operation applied to two different feature sets:
    # a brand's mean dissimilarity to every other brand. Messaging uses overlap
    # of territories used; imagery uses share of coded dimensions matching.
    # Using one definition for both is what makes the axes comparable.
    #
    # Note this is NOT the same as departure-from-majority above, and can rank
    # differently. A brand that claims a great many territories overlaps more
    # with everybody, so it scores as less dissimilar even while departing from
    # the majority most often. Both are true and they answer different
    # questions; the drawer shows both.
    # ---------------------------------------------------------------------
    def jaccard_sets(a, b):
        a, b = set(a), set(b)
        return len(a & b) / len(a | b) if (a | b) else 0.0

    others = lambda b: [o for o in BRANDS if o != b]
    plot = []
    for b in BRANDS:
        msg = 1 - sum(jaccard_sets(CODING[b], CODING[o]) for o in others(b)) / len(others(b))
        img = None
        if b in visual_coding:
            peers = [o for o in others(b) if o in visual_coding]
            if peers:
                img = 1 - sum(jaccard_sets(visual_coding[b], visual_coding[o]) for o in peers) / len(peers)
        plot.append({
            "brand": b,
            "messaging": round(msg, 3),
            "imagery": round(img, 3) if img is not None else None,
        })

    plotted = [p for p in plot if p["imagery"] is not None]
    plot_meta = {
        "messaging_mean": round(sum(p["messaging"] for p in plot) / len(plot), 3),
        "imagery_mean": round(sum(p["imagery"] for p in plotted) / len(plotted), 3) if plotted else None,
        "imagery_territories": len(visual_positions),
        "caveat": (
            "Both axes measure how unlike the other brands each brand is — the same calculation, applied to "
            "the messaging territories and to the visual territories. The view is zoomed to the brands "
            "plotted, so read position relative to the crosshair rather than as an absolute score. "
            f"There are {len(visual_positions)} visual territories against {len(positions)} messaging ones, "
            "so the vertical axis moves in coarser steps than the horizontal."
        ),
    }

    # Which brands actually match each other on imagery. This is where the
    # finding lives, and it survives the small sample better than any distance.
    vlabels = {p["id"]: p["label"] for p in visual_positions}
    imagery_pairs = []
    for a, b in combinations(visual_brands, 2):
        same = sorted(set(visual_coding[a]) & set(visual_coding[b]))
        union = set(visual_coding[a]) | set(visual_coding[b])
        imagery_pairs.append({
            "pair": [a, b],
            "match": round(len(same) / len(union), 3) if union else 0.0,
            "shared": [vlabels[k] for k in same],
        })
    imagery_pairs.sort(key=lambda r: -r["match"])

    # Verbal/visual cross-check, both sides now measured the same way.
    v_counts = Counter()
    for b in visual_brands:
        v_counts.update(visual_coding[b].keys())
    v_occupied = [p["id"] for p in visual_positions if p["n"] > 0]
    cross_check = []
    for b in BRANDS:
        if b not in visual_coding:
            continue
        departures = [pid for pid in v_occupied
                      if (pid in visual_coding[b]) != (v_counts[pid] > len(visual_brands) / 2)]
        v_used = len(visual_coding[b])
        v_alone = sum(1 for pid in visual_coding[b] if v_counts[pid] == 1)
        cross_check.append({
            "brand": b,
            "verbal_ownership": brand_position[b]["ownership"],
            "visual_ownership": round(v_alone / v_used, 3) if v_used else 0.0,
            "visual_distance": round(len(departures) / len(v_occupied), 3) if v_occupied else 0.0,
            "hero_notes": VISUAL[b]["notes"],
        })

    comments = {
        "Zoryve": "Makes the most claims of any brand in the set and appears in almost every territory the category shares. Its borrow from beauty and skincare is the most visually differentiated decision in the category.",
        "Vtama": "The clearest example of the copy-versus-imagery gap. Its verbal positioning — skin science — is the most distinctive in the set, but its hero image matches Opzelura on who is pictured, whether they touch, the emotional register and the scene.",
        "Opzelura": "Copy and imagery are consistent with each other. The touch-avoidance narrative in the messaging is delivered as restored touch in the photography. Highly similar to competitors, but internally coherent.",
        "Eucrisa": "Holds no position exclusively, and its imagery is the most conventionally pharmaceutical in the set. It has not been out-positioned by competitors; it has not taken a position.",
    }
    for row in cross_check:
        row["comment"] = comments[row["brand"]]

    occ_rate = len(occupied) / len(SPACE)
    crowd_rate = len(contested) / len(occupied)

    lit_empty = [k for k in empty if k[0] in "XH"]
    universal = [k for k in occupied if c[k] == len(BRANDS)]

    v_unused = sum(1 for p in visual_positions if p["n"] == 0)
    headline = (
        f"This category scores {overall} for convergence — {bname.lower()}. "
        f"{len(contested)} of the {len(occupied)} messaging territories in play are shared with a competitor, "
        f"and {len(universal)} are used by every brand in the category. "
        f"A further {len(lit_empty)}, each with published evidence behind it, are explored by nobody. "
        f"The art direction scores {conv_img['mean']}, with {v_unused} of {len(visual_positions)} "
        "visual territories depicted by nobody."
    )

    standfirst = (
        "Shared territory is the expensive part. Where several brands make the same argument, none of them "
        "owns it, and the audience is given no basis on which to tell them apart. "
        f"Of the {len(lit_empty)} territories nobody explores, {len(open_empty)} need no new clinical evidence "
        "to work with — no additional trial, no new endpoint, nothing further to substantiate. They are decisions "
        "about how the disease is described, who the communications address, and where they appear, all inside "
        "the existing label. They are unexplored because nobody chose them, not because nobody could."
    )

    return {
        "meta": META,
        "headline": headline,
        "standfirst": standfirst,
        "convergence": convergence_block,
        "tier_labels": {
            "open": "Explore now",
            "frame_only": "Raise, not claim",
            "constrained": "Needs substantiation",
            "closed": "Not viable",
        },
        "metrics": {
            "space_size": len(SPACE),
            "occupied": len(occupied),
            "empty": len(empty),
            "occupancy_rate": round(occ_rate, 3),
            "crowded": len(crowded),
            "contested": len(contested),
            "sole_held": len(sole),
            "crowding_rate": round(crowd_rate, 3),
            "open_empty": len(open_empty),
            "empty_ids": empty,
            "open_empty_ids": open_empty,
            "crowded_ids": crowded,
            "mean_pairwise": round(sum(pw.values()) / len(pw), 3),
            "pairwise": pw,
            "provenance_counts": dict(Counter(PROVENANCE.values())),
            "empty_by_tier": dict(Counter(TIERS[k][0] for k in empty)),
        },
        "positions": positions,
        "brand_position": brand_position,
        "centre": centre,
        "plot": plot,
        "plot_meta": plot_meta,
        "imagery_pairs": imagery_pairs,
        "provenance_breakdown": [
            {
                "key": k,
                "label": label,
                "total": sum(1 for p in positions if p["provenance"] == k),
                "unused": sum(1 for p in positions if p["provenance"] == k and p["n"] == 0),
                "note": note,
            }
            for k, label, note in [
                ("observed in category",
                 "Read off the four websites",
                 "Territories at least one brand actually uses. Every one has a user by definition — that is what identifying them from the corpus means."),
                ("patient burden literature",
                 "Established from patient burden literature",
                 "Territories evidenced in the burden-of-illness literature, identified independently of anything these brands say."),
                ("clinical barrier literature",
                 "Established from clinical barrier literature",
                 "Territories evidenced in the prescribing, adherence and guideline literature, identified independently of anything these brands say."),
            ]
        ],
        "visual_positions": visual_positions,
        "visual_provenance": [
            {
                "key": k,
                "label": label,
                "total": sum(1 for p in visual_positions if p["provenance"] == k),
                "unused": sum(1 for p in visual_positions if p["provenance"] == k and p["n"] == 0),
                "note": note,
            }
            for k, label, note in [
                ("observed in category", "Read off the four websites",
                 "Visual territories at least one brand actually uses. Every one has a user by definition — that is what identifying them from the imagery means."),
                ("patient burden literature", "Established from patient burden literature",
                 "Visual territories evidenced in the burden-of-illness and lived-experience literature, identified independently of anything these brands show."),
                ("clinical barrier literature", "Established from representation and barrier literature",
                 "Visual territories evidenced in the literature on who this disease affects and where it is under-recognised, identified independently of anything these brands show."),
            ]
            if sum(1 for p in visual_positions if p["provenance"] == k)
        ],
        "visual": {
            "brands": visual_brands,
            "notes": {b: VISUAL[b]["notes"] for b in VISUAL},
            "images": {},
            "territories": len(visual_positions),
            "unclaimed": sum(1 for p in visual_positions if p["n"] == 0),
            "exclusions": "Only commissioned photography is scored here. Clinical images, diagrams of how the drug works and pack shots are excluded, because they were determined by the product rather than chosen by art direction. The visual territories are built for this category the same way the messaging territories are — from what these brands show, plus what the literature evidences and nobody shows. This worked example is a stored capture, so the images themselves are not served with it; each territory carries the recorded observation instead.",
        },
        "cross_check": cross_check,
        "findings": FINDINGS,
        "boundary_rules": BOUNDARY_RULES,
        "limitations": LIMITATIONS,
    }


if __name__ == "__main__":
    data = build()
    with open("worked_example.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    m = data["metrics"]
    print(data["headline"])
    print(f"space {m['space_size']} · occupied {m['occupied']} · crowded {m['contested']} · open+empty {m['open_empty']}")
    print("empty by tier:", m["empty_by_tier"])
