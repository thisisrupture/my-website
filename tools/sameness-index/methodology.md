# The sameness index — classification schema and method

**Version 0.1 — prototype**
**Category under test:** non-steroidal topical therapies for atopic dermatitis, US market
**Corpus:** Zoryve (Arcutis), Vtama (Organon), Opzelura (Incyte), Eucrisa (Pfizer) — patient and HCP sites, atopic dermatitis sections only

---

## What the index claims

The index measures how much daylight exists between competing brands in a category, using the brand's own website as the single source of truth.

It does not claim to measure brand strength, creative quality, or commercial performance. It measures one thing: the distance between what these brands have chosen to say and show, relative to each other.

The word "chosen" is doing the work. Most of what appears on a pharmaceutical brand site is not a choice. Separating the choices from the constraints is the whole method.

---

## The three layers

Every element of copy and every image is assigned to exactly one layer.

### Layer 1 — Mandated

Content that exists because a regulator requires it. Nobody chose a word of it, and its presence carries no strategic information.

Includes: Important Safety Information, boxed warnings, contraindications, adverse reaction lists, the indication statement, prescribing information and medication guide links, adverse event reporting numbers, "for topical use only" instructions, pregnancy registry text, copay programme terms and conditions, privacy and cookie notices, "actor portrayal" and "individual results may vary" disclaimers.

**Treatment: stripped entirely. Excluded from all scoring.**

Note: mandated volume varies enormously by molecule and is not a marketing decision. Opzelura carries the JAK class boxed warning and so runs roughly 1,500 words of mandated safety text; Eucrisa's ISI is under 150 words. Failing to strip this would make Opzelura appear maximally differentiated on the basis of FDA labelling.

### Layer 2 — Molecule-determined

Content that is technically elective but constrained by what the molecule is, what the label permits, and what the trials measured. A brand cannot say it if the science does not support it, and if the science does support it, saying it is close to obligatory.

Includes: mechanism of action and target class, approved population and age floor, dosing frequency and duration, trial names and design, primary and secondary endpoint results, comparator data, before-and-after clinical photography, mechanism diagrams, product form (cream, ointment, foam), guideline recognition.

**Treatment: retained, scored separately, reported as context. Convergence here is expected and is not a finding.**

### Layer 3 — Elective

Everything remaining. Content that was written or commissioned by choice, where a different choice was available and would have been equally supportable.

Includes: how the disease is named and characterised, how the unmet need is framed, who the patient is understood to be, what the category's failure is taken to be, what relief is framed as, the emotional register, metaphor and motif, tone of voice, site architecture and what is placed first, all lifestyle photography, colour, typography, and visual borrow.

**Treatment: this is the index. Convergence here is the finding.**

---

## Boundary rules

The layer 2 / layer 3 boundary is the contestable part of the method. These rules are applied identically to every brand and are open to challenge.

| Element | Layer | Rule |
|---|---|---|
| "Steroid-free" | 2 | Factual property of the molecule class. Universal in this category. |
| "Steroid-free, so you can use it where steroids scare you" | 3 | The consequence framing is elective. |
| "Once daily" | 2 | Label-determined dosing. |
| "Simple once-daily treatment" | 3 | "Simple" is a claimed benefit, not a dosing fact. |
| Age floor ("down to 2 years") | 2 | Trial and label determined. |
| Imagery of a two-year-old | 3 | The decision to dramatise the age floor is elective. |
| Endpoint percentages | 2 | Trial output. |
| Which endpoint is placed first | 3 | Hierarchy is a positioning decision. |
| Clinical lesion photography | 2 | Trial asset. |
| Lifestyle photography | 3 | Commissioned. |
| Mechanism of action explanation | 2 | Pharmacology. |
| Mechanism analogy or metaphor | 3 | Explanatory framing is elective. |

**Ambiguity default:** where an element could plausibly sit in either layer, it is assigned to layer 2. This biases the index toward under-reporting convergence, which is the conservative direction — a finding of high elective convergence is then harder to dismiss.

---

## Metrics

### 1. Elective share

Elective content as a proportion of total non-mandated content, per brand, per audience layer.

A low elective share means the brand is largely restating its label. It has not been out-positioned; it has declined to position. This is the "what the molecule cannot do for you" measure — whatever sits outside the molecule layer is the only thing that survives a competitor publishing better data.

### 2. Elective convergence

Similarity between brands computed on layer 3 content only.

Reported two ways:
- **Pairwise** — which brands most resemble each other
- **Distance from category centroid** — how much daylight each brand has claimed

The centroid distance is the headline. Pairwise says who you look like; centroid distance says whether anybody is anywhere.

### 3. Molecule convergence (control)

The same computation on layer 2. Expected to be high. Reported only as a baseline — if elective convergence approaches molecule convergence, the category has stopped making decisions.

### 4. Shared-claim receipts

Verbatim phrases and claims appearing across two or more brands within layer 3, with attribution. The evidence beneath the score.

---

## Visual rubric

Elective imagery is coded on eight categorical dimensions. Clinical photography, mechanism diagrams and product shots are layer 2 and excluded.

| Dimension | Values |
|---|---|
| Human configuration | none / individual alone / caregiver-child dyad / family group / clinician-patient |
| Touch | absent / self-touch / interpersonal touch |
| Disease depiction | clinical lesion / visible on lifestyle model / implied only / absent |
| Skin tone range | single / limited / broad |
| Life moment | clinical / ordinary domestic / leisure / achievement / abstract |
| Emotional register | relief / celebration / calm control / confidence / tenderness / neutral clinical |
| Abstraction motif | none / natural / scientific / cosmetic / celestial |
| Category borrow | pharma / beauty and skincare / wellness / consumer tech |

**Touch is the discriminating variable in this category.** Atopic dermatitis is a disease of touch avoidance. Whether a brand depicts people touching each other is a strategic decision with a clear rationale either way, which makes agreement across brands meaningful rather than incidental.

Outputs:
- **Modal agreement per dimension** — the proportion of brands sharing the most common value. The visual receipt.
- **Visual distance from the modal category profile** — the visual equivalent of centroid distance.

### Verbal/visual cross-check

The two indices are compared per brand. A brand that scores as verbally distinct but visually converged has written differentiation into the copy and lost it in the shoot. This is the most common and least visible failure mode in the category, and it is only detectable by scoring both layers separately.

---

## Known limitations

1. **Layer boundary is a judgement.** Documented above, applied consistently, open to challenge. Different reasonable rules would move the score.
2. **Website only.** Congress presence, sales aids, MSL messaging, paid media and social are excluded. The index measures the self-declared public position, not the whole commercial message.
3. **Small n.** Four brands. The centroid is meaningful but not robust to one brand being unusual.
4. **Point in time.** A single capture. Longitudinal comparison requires re-running against archived captures.
5. **Eucrisa is temporally offset.** Approved 2016, materially older creative, and its HCP site is currently serving a partial render with unreplaced placeholder text in production. It functions as a rough temporal control rather than a like-for-like competitor.

---

## Validity check

The same pipeline is run against IgA nephropathy, a two-brand category. If a two-brand category returns a comparably high convergence score, the index is measuring therapy-area vocabulary rather than strategic choice, and the layer 2 stripping has failed. This check is run before any result is reported.
