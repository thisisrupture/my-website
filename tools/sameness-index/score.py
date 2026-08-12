"""
Sameness index — scored against the full opportunity space.

The earlier version measured brands only against each other. That answers
"who resembles whom" but not "is anybody anywhere". This version establishes
the set of positions that were AVAILABLE — observed in category, plus positions
evidenced in the patient burden and clinical barrier literature — and measures
what the category does say against what it could say.

Run: python3 score.py
"""

import json
from collections import Counter
from itertools import combinations

from concepts import CONCEPTS, CODING, EXOGENOUS, HCP_SOURCED, PROVENANCE
from corpus import VISUAL, VISUAL_DIMENSIONS

BRANDS = list(CODING)
SPACE = list(CONCEPTS)


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a | b) else 0.0


def counts():
    c = Counter()
    for b in BRANDS:
        c.update(CODING[b].keys())
    return c


def occupancy():
    """The headline. What proportion of the available space is used, and how
    much of what is used is crowded."""
    c = counts()
    occupied = [k for k in SPACE if c[k] > 0]
    crowded = [k for k in occupied if c[k] > len(BRANDS) / 2]
    contested = [k for k in occupied if c[k] > 1]
    sole = [k for k in occupied if c[k] == 1]
    return {
        "space_size": len(SPACE),
        "occupied": len(occupied),
        "empty": len(SPACE) - len(occupied),
        "occupancy_rate": round(len(occupied) / len(SPACE), 3),
        "crowded": len(crowded),
        "contested": len(contested),
        "sole_held": len(sole),
        # Of the ground actually taken, how much is shared rather than owned.
        "crowding_rate": round(len(contested) / len(occupied), 3) if occupied else 0.0,
        "empty_ids": [k for k in SPACE if c[k] == 0],
        "crowded_ids": crowded,
    }


def concept_rows():
    c = counts()
    rows = []
    for cid, label in CONCEPTS.items():
        claimers = [b for b in BRANDS if cid in CODING[b]]
        rows.append(
            {
                "id": cid,
                "label": label,
                "provenance": PROVENANCE[cid],
                "claimers": claimers,
                "n": len(claimers),
                "share": round(len(claimers) / len(BRANDS), 3),
                "receipts": {b: CODING[b][cid] for b in claimers},
            }
        )
    return sorted(rows, key=lambda r: (-r["n"], r["id"]))


def pairwise():
    return {
        f"{a} / {b}": round(jaccard(CODING[a], CODING[b]), 3)
        for a, b in combinations(BRANDS, 2)
    }


def brand_position():
    c = counts()
    crowded = {k for k in SPACE if c[k] > len(BRANDS) / 2}
    out = {}
    for b in BRANDS:
        own = set(CODING[b])
        unique = {x for x in own if c[x] == 1}
        out[b] = {
            "claimed": len(own),
            # Share of the whole opportunity space this brand occupies.
            "space_used": round(len(own) / len(SPACE), 3),
            "uniquely_owned": sorted(unique),
            "n_unique": len(unique),
            # Of what this brand says, how much is its own.
            "ownership": round(len(unique) / len(own), 3) if own else 0.0,
            # Of the crowded ground, how much this brand also stands on.
            "crowding": round(len(own & crowded) / len(crowded), 3) if crowded else 0.0,
        }
    return out


def visual_agreement():
    rows = []
    for dim in VISUAL_DIMENSIONS:
        vals = Counter(VISUAL[b][dim] for b in VISUAL)
        modal, n = vals.most_common(1)[0]
        rows.append(
            {
                "key": dim,
                "modal_value": modal,
                "agreement": round(n / len(VISUAL), 3),
                "spread": dict(vals),
            }
        )
    return sorted(rows, key=lambda r: -r["agreement"])


def run():
    occ = occupancy()
    pw = pairwise()
    return {
        "brands": BRANDS,
        "occupancy": occ,
        "concepts": concept_rows(),
        "pairwise_jaccard": pw,
        "mean_pairwise": round(sum(pw.values()) / len(pw), 3),
        "brand_position": brand_position(),
        "visual_agreement": visual_agreement(),
        "child_in_hero": sum(1 for b in VISUAL if VISUAL[b]["child_present"]),
        "provenance_counts": dict(Counter(PROVENANCE.values())),
    }


if __name__ == "__main__":
    r = run()
    with open("results.json", "w") as f:
        json.dump(r, f, indent=2)

    o = r["occupancy"]
    print(f"OPPORTUNITY SPACE          {o['space_size']} positions")
    print(f"  occupied by someone      {o['occupied']}  ({o['occupancy_rate']:.0%})")
    print(f"  standing empty           {o['empty']}")
    print(f"  contested (2+ brands)    {o['contested']}")
    print(f"  crowded (majority)       {o['crowded']}")
    print(f"  held alone               {o['sole_held']}")
    print(f"  crowding rate            {o['crowding_rate']:.0%} of occupied ground is shared")
    print(f"\nMEAN PAIRWISE OVERLAP      {r['mean_pairwise']}")

    print("\nBRAND POSITION")
    for b, d in sorted(r["brand_position"].items(), key=lambda kv: -kv[1]["ownership"]):
        print(
            f"  {b:10s} claims {d['claimed']:2d} of {o['space_size']} "
            f"({d['space_used']:.0%})  owns {d['n_unique']}  "
            f"ownership {d['ownership']:.2f}  crowding {d['crowding']:.2f}"
        )

    print("\nEMPTY GROUND")
    for cid in o["empty_ids"]:
        print(f"  {cid}  [{PROVENANCE[cid]}]  {CONCEPTS[cid]}")
