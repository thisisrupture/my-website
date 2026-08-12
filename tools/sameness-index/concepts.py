"""
Concept-level coding of the elective layer.

Rationale: lexical similarity (TF-IDF cosine) fails at small n on short copy —
it cannot see that "reimagine relief", "the touch of calm skin" and "safe on skin"
are the same positioning move. Concepts are the unit of analysis; wording is not.

Each concept is a POSITIONING MOVE that was available to every brand in the
category. Presence is coded from the patient and HCP sites, elective layer only.
Molecule-determined content cannot trigger a concept.
"""

CONCEPTS = {
    "C01": "Steroid avoidance framed as the core promise, not just a product fact",
    "C02": "Paediatric reassurance — safe for very young children",
    "C03": "Caregiver addressed as the decision-maker",
    "C04": "Speed of relief",
    "C05": "Itch named as the enemy",
    "C06": "Visible clearance as the goal state",
    "C07": "Permission for long-term or continuous use",
    "C08": "Freedom to use anywhere on the body, including sensitive areas",
    "C09": "Formulation elegance / sensory experience",
    "C10": "Return to ordinary life and its moments",
    "C11": "Touch and physical intimacy restored",
    "C12": "Emotional burden of the disease acknowledged",
    "C13": "Beauty or cosmetic category framing",
    "C14": "Mechanism or science as the brand story",
    "C15": "Access and affordability foregrounded",
    "C16": "Convenience and simplicity as a benefit",
    "C17": "Category leadership or first-in-class authority claim",
    "C18": "Enabling the physician conversation",
    "C19": "Treatment-free intervals / life between flares",
    "C20": "Efficacy across all skin tones",
}

# --------------------------------------------------------------------------
# EXOGENOUS CONCEPTS
#
# Derived from the documented burden of atopic dermatitis, NOT from the
# corpus. Without these the taxonomy is circular — a concept list built from
# what the brands say can never surface ground nobody has taken.
#
# Sources: AD burden-of-illness literature; sleep disturbance affects the
# majority of patients with moderate-to-severe disease and is consistently
# reported as the single most burdensome symptom; anxiety and depression
# comorbidity is well established; caregiver sleep loss in paediatric AD is
# documented and substantial.
# --------------------------------------------------------------------------

EXOGENOUS = {
    "X01": "Sleep disruption named as the primary burden",
    "X02": "Caregiver exhaustion — the parent's own lost sleep and toll",
    "X03": "Mental health comorbidity — anxiety, depression, low mood",
    "X04": "Visible stigma in social, school or workplace settings",
    "X05": "Adult-persistent or adult-onset disease as the primary frame",
    "X06": "The steroid cycle itself named as the failure — rebound, thinning, fear",
    "X07": "Time and labour of the whole regimen — bathing, emollients, laundry",
    "X08": "Flare unpredictability and anticipatory anxiety",
    "X09": "Diagnostic delay and not being taken seriously",
    "X10": "Cost and effort of everything tried before this",
}

CONCEPTS.update(EXOGENOUS)

# --------------------------------------------------------------------------
# HCP-SOURCED CONCEPTS
#
# Positions available on the clinical side, derived from the treatment-barrier
# and guideline literature rather than from the corpus. See sources.md.
# --------------------------------------------------------------------------

HCP_SOURCED = {
    "H01": "Corticophobia named directly as the problem steroid-free answers",
    "H02": "The topical steroid withdrawal narrative addressed head-on",
    "H03": "Adherence and persistence framed as the clinical problem, not efficacy",
    "H04": "Maintenance and flare prevention as the goal, not flare clearance",
    "H05": "Quantified reduction in total corticosteroid exposure",
    "H06": "Built for the non-dermatologist prescriber — paediatrics and primary care",
    "H07": "Shared decision-making and patient-reported outcomes in the consultation",
    "H08": "Formulary and coverage friction treated as the real barrier",
    "H09": "Application tolerability — stinging and burning — as an adherence driver",
    "H10": "Meeting the patient earlier in the diagnostic journey",
}

CONCEPTS.update(HCP_SOURCED)

# Provenance — which concepts came from the corpus and which from outside it.
PROVENANCE = {}
for _c in CONCEPTS:
    if _c in EXOGENOUS:
        PROVENANCE[_c] = "patient burden literature"
    elif _c in HCP_SOURCED:
        PROVENANCE[_c] = "clinical barrier literature"
    else:
        PROVENANCE[_c] = "observed in category"

def _credit_partial_claims():
    """Two brands get part-way to an HCP-sourced position. Credited so the
    empty-ground list is not overstated. Applied after CODING is defined."""
    CODING["Vtama"]["H04"] = (
        "'sustained results, even during treatment-free months' — the closest "
        "anything in the category comes to a maintenance frame"
    )
    CODING["Zoryve"]["H09"] = (
        "'gentle formulation' / 'elegant formulations' — tolerability implied, "
        "never named as an adherence driver"
    )

# Presence coding. Evidence string is the anchor that justifies the code.
CODING = {
    "Zoryve": {
        "C01": "'NOT A STEROID' set in the hero benefit bar, second of three",
        "C03": "'As a mom who also lives with eczema, walking this path alongside my daughter'",
        "C05": "'powerful skin clearance and reduction in itch' (HCP)",
        "C06": "'powerful skin clearance'",
        "C07": "'safe, long-term disease control for any skin type' (HCP)",
        "C08": "'ZORYVE cream. Once a day. Anywhere.' / 'reliable results anywhere on the body'",
        "C09": "'gentle formulation' / 'discover elegant formulations' (HCP)",
        "C10": "'Everyone deserves the touch of calm skin'",
        "C11": "'the touch of calm skin' — touch is the headline noun",
        "C13": "Allure Best of Beauty and Glamour Beauty & Wellness award roundels in hero",
        "C15": "'committed to affordable patient access' / savings card in primary nav",
        "C16": "'simple, once-daily treatment' / 'simplify atopic dermatitis treatment' (HCP)",
        "C17": "'#1 prescribed branded topical' / 'over 1 million prescriptions'",
        "C18": "'see a dermatologist online' — persistent CTA",
        "C20": "'for any skin type' (HCP); broad skin tone casting in hero",
    },
    "Vtama": {
        "C01": "'steroid-free' in the persistent hero banner",
        "C02": "'as young as 2 years of age' in the hero banner",
        "C03": "Caregiver-and-child hero; 'Not actual patients/caregiver'",
        "C05": "Dedicated 'Itch Relief' section in primary nav",
        "C06": "'Powerful Skin Clearance' as the first content block",
        "C09": "'safe on skin' — the second half of the hero antithesis",
        "C14": "'It's not fiction. It's Skin Science.' — the brand line is a science claim",
        "C16": "'once-daily' foregrounded in the hero banner",
        "C17": "'first and only AhR agonist' / 'First in Class'",
        "C19": "'sustained results, even during treatment-free months'",
        "C20": "'across all disease severities, skin tones, and treatment areas'",
    },
    "Opzelura": {
        "C01": "'STEROID-FREE JAK INHIBITOR CREAM' — first line of hero subcopy",
        "C02": "'for you and your kids as young as 2 years'",
        "C03": "Mother-and-child hero; 'the impact eczema has on you or your child'",
        "C04": "'itch improvement as early as 3 or 4 days'",
        "C05": "'significantly reduce itch'; dedicated Itch Relief section",
        "C06": "'clear or almost clear skin'",
        "C10": "'OPZELURA moments with patients' / 'Moments of Clarity'",
        "C11": "Patient narrative built entirely on hand-holding and touch refusal",
        "C12": "'I was devastated... they were trying to stay away from my eczema'",
        "C15": "'as little as $0 per tube' in primary nav",
        "C18": "'Treating eczema starts with a conversation'; Eczema E-Guide",
    },
    "Eucrisa": {
        "C01": "'100% steroid-free' as a hero roundel",
        "C02": "'Approved for babies' — one of three hero cards",
        "C03": "'Eczema and Your Child' section in primary nav",
        "C07": "'can be part of a long-term treatment plan'",
        "C08": "'can be used almost everywhere on almost everybody'",
        "C14": "'works above and below the skin's surface' — the hero claim is mechanistic",
        "C15": "'pay as little as $10' banner",
        "C20": "'can be used on all skin tones'",
    },
}


_credit_partial_claims()
