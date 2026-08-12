"""
Sameness index — coded corpus.
Category: US non-steroidal topical atopic dermatitis.
Captured: 12 August 2026.

Every string is assigned to a layer per methodology.md.
LAYER 1 (mandated) is not stored — it is stripped at capture.
"""

BRANDS = ["Zoryve", "Vtama", "Opzelura", "Eucrisa"]

# ---------------------------------------------------------------
# PATIENT LAYER
# ---------------------------------------------------------------

PATIENT = {
    "Zoryve": {
        "molecule": [
            "roflumilast cream 0.15% and 0.05%",
            "phosphodiesterase-4 inhibitor",
            "once daily",
            "not a steroid",
            "mild to moderate eczema atopic dermatitis",
            "for age 2 to 5 and age 6 and older",
            "strongly recommended as a treatment option by the American Academy of Dermatology 2025 guidelines",
        ],
        "elective": [
            "Everyone deserves the touch of calm skin",
            "Not the discomfort of eczema",
            "gentle formulation",
            "Over 1 million prescriptions and counting",
            "#1 prescribed branded topical",
            "Allure Best of Beauty award winner",
            "Glamour Beauty and Wellness Awards",
            "award-winning eczema treatment",
            "As a mom who also lives with eczema, walking this path alongside my daughter has been deeply personal",
            "see a dermatologist online",
            "living with eczema",
        ],
    },
    "Vtama": {
        "molecule": [
            "tapinarof cream 1%",
            "aryl hydrocarbon receptor agonist",
            "once daily",
            "steroid free",
            "eczema atopic dermatitis",
            "as young as 2 years of age",
            "up to 46% of patients achieved clear or almost clear skin compared to 18% on cream with no active ingredient",
            "8 week clinical studies",
        ],
        "elective": [
            "Tough on eczema, safe on skin",
            "first and only aryl hydrocarbon receptor agonist",
            "skin science",
            "visible results",
            "why VTAMA cream",
            "getting started on VTAMA cream",
            "what is eczema",
            "clinically proven to deliver sustained results even during treatment free months",
        ],
    },
    "Opzelura": {
        "molecule": [
            "ruxolitinib cream 1.5%",
            "topical JAK inhibitor",
            "steroid free",
            "twice daily",
            "short term and non continuous chronic treatment",
            "mild to moderate eczema atopic dermatitis",
            "patients as young as 2 years of age",
            "more than half of patients using OPZELURA saw skin clearance at 8 weeks versus 15%",
            "significantly reduce itch with more than half seeing relief at 8 weeks",
            "some patients saw itch improvement as early as 3 or 4 days",
        ],
        "elective": [
            "Reimagine relief with OPZELURA",
            "steroid free JAK inhibitor cream for you and your kids",
            "targets eczema at a key source",
            "on the spot treatment applied directly to the skin",
            "OPZELURA moments with patients",
            "moments of clarity",
            "I went from using multiple lotions, creams and ointments to now only needing to use OPZELURA",
            "treating mild to moderate eczema starts with a conversation",
            "reimagine your next doctor's appointment",
            "eczema e-guide",
            "highlighting the impact eczema has on you or your child",
            "stay in the know",
            "at every step of your eczema treatment journey",
            "book a virtual appointment",
        ],
    },
    "Eucrisa": {
        "molecule": [
            "crisaborole ointment 2%",
            "phosphodiesterase-4 inhibitor PDE4",
            "twice daily with expanded once daily dosing once clinical effect achieved",
            "100% steroid free",
            "mild to moderate eczema atopic dermatitis",
            "adults and children 3 months of age and older",
            "emollient rich vehicle ointment",
        ],
        "elective": [
            "works above and below the skin's surface",
            "can be used almost everywhere on almost everybody",
            "can be used on all skin tones",
            "can be part of a long term treatment plan",
            "see it in action",
            "approved for babies",
            "eczema and your child",
            "a closer look at eczema",
            "results you can see",
            "what to expect",
            "eczema tips",
        ],
    },
}

# ---------------------------------------------------------------
# HCP LAYER
# ---------------------------------------------------------------

HCP = {
    "Zoryve": {
        "molecule": [
            "roflumilast cream 0.05% and 0.15%",
            "contraindicated in patients with moderate to severe liver impairment",
            "31% of patients achieved vIGA-AD success at week 4 versus 14% with vehicle",
            "32% achieved WI-NRS success at week 4 versus 17% with vehicle",
            "INTEGUMENT-1 and INTEGUMENT-2 phase 3 vehicle controlled studies",
            "INTEGUMENT-PED",
            "once daily",
            "not a steroid, no boxed warning",
        ],
        "elective": [
            "ZORYVE it, relieve it",
            "has the power and versatility to be your go-to topical",
            "powerful skin clearance and reduction in itch",
            "safe long term disease control for any skin type",
            "simple once daily treatment",
            "simplify atopic dermatitis treatment",
            "ZORYVE cream, once a day, anywhere",
            "reliable results anywhere on the body",
            "discover elegant formulations",
            "committed to affordable patient access",
        ],
    },
    "Vtama": {
        "molecule": [
            "tapinarof cream 1% aryl hydrocarbon receptor agonist",
            "up to 46% of patients achieved clear or almost clear skin versus 18% on vehicle",
            "ADORING 1 and ADORING 2 pivotal phase 3 trials",
            "ADORING 3 48 week open label extension",
            "vIGA-AD success at week 8",
            "no to minimal systemic absorption",
            "dual indication",
            "steroid free topical",
        ],
        "elective": [
            "It's not fiction, it's skin science",
            "powerful skin clearance",
            "first in class",
            "proven results across all disease severities, skin tones, and treatment areas",
            "consecutive treatment free months",
            "clinically proven to deliver sustained results even during treatment free months",
            "uncover more",
            "discover the science",
            "visible results",
        ],
    },
    "Eucrisa": {
        "molecule": [
            "crisaborole ointment 2%",
            "PDE4 inhibitor",
            "topical treatment of mild to moderate atopic dermatitis in patients 3 months and older",
            "ISGA clear or almost clear",
            "safety data across 5 studies including pivotal and open label safety extension studies",
            "52 week trial",
            "expanded dosing recommendation to consider once daily application once clinical effect has been achieved",
        ],
        "elective": [
            "a steroid free option",
            "steroid free EUCRISA provides efficacy and can be used as part of a long term treatment plan",
            "dosing regimen that can be adjusted to fit your patient's needs",
            "established safety profile",
            "proven efficacy",
            "real patient case reports",
        ],
    },
    # Opzelura HCP not captured in this run — see limitations.
}

# ---------------------------------------------------------------
# VISUAL CODING — patient layer hero
# ---------------------------------------------------------------

VISUAL = {
    "Zoryve": {
        "human_configuration": "individual alone",
        "touch": "self-touch",
        "disease_depiction": "absent",
        "skin_tone_range": "broad",
        "life_moment": "ordinary domestic",
        "emotional_register": "calm control",
        "abstraction_motif": "none",
        "category_borrow": "beauty and skincare",
        "child_present": True,
        "notes": "Split triptych: child arms raised in living room, adult male laughing, adult woman eyes closed touching own face. Allure and Glamour beauty award roundels in hero. Celebrity endorsement (Tori Spelling, Max Homa) below fold.",
    },
    "Vtama": {
        "human_configuration": "caregiver-child dyad",
        "touch": "interpersonal touch",
        "disease_depiction": "implied only",
        "skin_tone_range": "limited",
        "life_moment": "ordinary domestic",
        "emotional_register": "tenderness",
        "abstraction_motif": "none",
        "category_borrow": "consumer tech",
        "child_present": True,
        "notes": "Mother and child lying face to face on striped blanket in darkened bedroom, laughing. Gradient display typography (orange to magenta to violet). 'Not actual patients/caregiver'.",
    },
    "Opzelura": {
        "human_configuration": "caregiver-child dyad",
        "touch": "interpersonal touch",
        "disease_depiction": "visible on lifestyle model",
        "skin_tone_range": "single",
        "life_moment": "ordinary domestic",
        "emotional_register": "tenderness",
        "abstraction_motif": "celestial",
        "category_borrow": "wellness",
        "child_present": True,
        "notes": "Mother reading to shirtless toddler on lap in nursery; visible erythematous lesions on torso and arms. Illustrated cloud and star overlays. Condensed serif display type. Product tube in frame.",
    },
    "Eucrisa": {
        "human_configuration": "individual alone",
        "touch": "absent",
        "disease_depiction": "absent",
        "skin_tone_range": "single",
        "life_moment": "ordinary domestic",
        "emotional_register": "neutral clinical",
        "abstraction_motif": "none",
        "category_borrow": "pharma",
        "child_present": True,
        "notes": "Infant in nappy crawling toward camera, smiling, clear skin. Badge/roundel system: '3 months & up FDA approved', '100% steroid free', 'works at and below'. Hero claim footnoted 'The specific way EUCRISA works is not well defined.'",
    },
}

VISUAL_DIMENSIONS = [
    "human_configuration",
    "touch",
    "disease_depiction",
    "skin_tone_range",
    "life_moment",
    "emotional_register",
    "abstraction_motif",
    "category_borrow",
]

# Plain-English labels for the report. The keys stay stable for the code;
# nobody outside the build should have to read the word "abstraction motif".
VISUAL_LABELS = {
    "human_configuration": "Who is in the picture",
    "touch": "Is anyone touching anyone",
    "disease_depiction": "Is the eczema shown",
    "skin_tone_range": "Range of skin tones",
    "life_moment": "What is happening",
    "emotional_register": "How it is meant to feel",
    "abstraction_motif": "Graphic device used",
    "category_borrow": "What it looks like it is selling",
}
