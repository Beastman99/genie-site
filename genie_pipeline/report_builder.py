#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


POLYGENIC_RULES = {
    "height": {
        "display_name": "Height",
        "positive": "higher height-associated polygenic signal",
        "negative": "lower height-associated polygenic signal",
        "neutral": "mixed height-associated polygenic signal",
        "note": "Prototype label from a reduced public PGS subset. Not calibrated to centimeters."
    },
    "left-handedness": {
        "display_name": "Left-handedness",
        "positive": "higher left-handedness-associated signal",
        "negative": "lower left-handedness-associated signal",
        "neutral": "mixed handedness-associated signal",
        "note": "Prototype label from a reduced public PGS subset. This is not a direct handedness prediction."
    },
    "bmi": {
        "display_name": "BMI",
        "positive": "higher BMI-associated polygenic signal",
        "negative": "lower BMI-associated polygenic signal",
        "neutral": "mixed BMI-associated polygenic signal",
        "note": "Prototype label from a reduced public PGS subset. Not calibrated to a numeric BMI."
    },
    "intelligence": {
        "display_name": "Intelligence",
        "positive": "higher intelligence-associated signal",
        "negative": "lower intelligence-associated signal",
        "neutral": "mixed intelligence-associated signal",
        "note": "Prototype label from a reduced public PGS subset. This is not a deterministic cognitive prediction."
    },
    "hair-color": {
        "display_name": "Hair color",
        "positive": "hair-color score computed",
        "negative": "hair-color score computed",
        "neutral": "hair-color score computed",
        "note": "Score direction exists, but the plain-language color mapping is not finalized in this prototype."
    },
}


def coverage_note(top_n: int, allele_ct: int) -> str:
    matched_variants = allele_ct // 2
    return f"Used {matched_variants} scored variants from a reduced top-{top_n} demo subset."


def classify_effect(score: float) -> str:
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def build_polygenic_entry(summary_path: Path) -> dict:
    summary = json.loads(summary_path.read_text())
    trait = summary["trait"]
    rule = POLYGENIC_RULES.get(trait, {
        "display_name": trait.replace("-", " ").title(),
        "positive": "higher relative polygenic signal",
        "negative": "lower relative polygenic signal",
        "neutral": "mixed relative polygenic signal",
        "note": "Prototype polygenic output."
    })
    sscore = summary["sscore"]
    polarity = classify_effect(sscore["effect_weight_sum"])
    label = rule[polarity]
    return {
        "trait": trait,
        "display_name": rule["display_name"],
        "type": "polygenic_demo",
        "result_label": label,
        "summary": rule["note"],
        "coverage_note": coverage_note(summary["top_n"], sscore["allele_ct"]),
        "sample_id": summary["sample"],
        "score": {
            "effect_weight_sum": sscore["effect_weight_sum"],
            "effect_weight_avg": sscore["effect_weight_avg"],
            "allele_ct": sscore["allele_ct"],
            "named_allele_dosage_sum": sscore["named_allele_dosage_sum"]
        },
        "source": {
            "pgs_id": summary["candidate"]["pgs_id"],
            "pgs_name": summary["candidate"]["name"],
            "summary_file": str(summary_path)
        }
    }


def build_simple_entries(simple_path: Path) -> list[dict]:
    payload = json.loads(simple_path.read_text())
    entries = []
    for trait in payload.get("traits", []):
        entry = {
            "trait": trait["trait"],
            "display_name": trait["trait"].replace("_", " ").title(),
            "type": "single_variant_heuristic",
            "status": trait["status"],
            "source": {
                "simple_traits_file": str(simple_path)
            }
        }
        if trait["status"] == "derived":
            entry["result_label"] = trait["prediction"]
            entry["summary"] = f"Derived from {trait['method']}."
            entry["variant"] = trait["variant"]
        else:
            entry["result_label"] = "not derived"
            entry["summary"] = trait.get("note", "Trait could not be derived from the supplied VCF.")
        entries.append(entry)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble Genie-style report JSON from trait outputs.")
    parser.add_argument("--sample", required=True)
    parser.add_argument("--polygenic-summary", action="append", default=[])
    parser.add_argument("--simple-traits", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    report = {
        "sample_id": args.sample,
        "product": "Genie",
        "report_type": "prototype_trait_report",
        "traits": []
    }

    for path in args.polygenic_summary:
        report["traits"].append(build_polygenic_entry(Path(path).expanduser().resolve()))

    for path in args.simple_traits:
        report["traits"].extend(build_simple_entries(Path(path).expanduser().resolve()))

    report["traits"].sort(key=lambda item: item["display_name"].lower())

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Wrote report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
