#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


POLYGENIC_RULES = {
    "height": {
        "display_name": "Height",
        "positive": "higher height-associated polygenic signal",
        "negative": "lower height-associated polygenic signal",
        "neutral": "mixed height-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. Not calibrated to centimeters."
    },
    "left-handedness": {
        "display_name": "Left-handedness",
        "positive": "higher left-handedness-associated signal",
        "negative": "lower left-handedness-associated signal",
        "neutral": "mixed handedness-associated signal",
        "note": "Prototype label from the selected public PGS file. This is not a direct handedness prediction."
    },
    "bmi": {
        "display_name": "BMI",
        "positive": "higher BMI-associated polygenic signal",
        "negative": "lower BMI-associated polygenic signal",
        "neutral": "mixed BMI-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. Not calibrated to a numeric BMI."
    },
    "intelligence": {
        "display_name": "Intelligence",
        "positive": "higher intelligence-associated signal",
        "negative": "lower intelligence-associated signal",
        "neutral": "mixed intelligence-associated signal",
        "note": "Prototype label from the selected public PGS file. This is not a deterministic cognitive prediction."
    },
    "hair-color": {
        "display_name": "Hair color",
        "positive": "hair-color score computed",
        "negative": "hair-color score computed",
        "neutral": "hair-color score computed",
        "note": "Score direction exists, but the plain-language color mapping is not finalized in this prototype."
    },
    "adhd": {
        "display_name": "ADHD",
        "positive": "higher ADHD-associated polygenic signal",
        "negative": "lower ADHD-associated polygenic signal",
        "neutral": "mixed ADHD-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. This is not a diagnosis."
    },
    "autism": {
        "display_name": "Autism",
        "positive": "higher autism-associated polygenic signal",
        "negative": "lower autism-associated polygenic signal",
        "neutral": "mixed autism-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. This is not a diagnosis."
    },
    "anxiety": {
        "display_name": "Anxiety",
        "positive": "higher anxiety-associated polygenic signal",
        "negative": "lower anxiety-associated polygenic signal",
        "neutral": "mixed anxiety-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. This is not a diagnosis."
    },
    "depression": {
        "display_name": "Depression",
        "positive": "higher depression-associated polygenic signal",
        "negative": "lower depression-associated polygenic signal",
        "neutral": "mixed depression-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. This is not a diagnosis."
    },
    "schizophrenia": {
        "display_name": "Schizophrenia",
        "positive": "higher schizophrenia-associated polygenic signal",
        "negative": "lower schizophrenia-associated polygenic signal",
        "neutral": "mixed schizophrenia-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. This is not a diagnosis."
    },
    "bipolar-disorder": {
        "display_name": "Bipolar disorder",
        "positive": "higher bipolar-associated polygenic signal",
        "negative": "lower bipolar-associated polygenic signal",
        "neutral": "mixed bipolar-associated polygenic signal",
        "note": "Prototype label from the selected public PGS file. This is not a diagnosis."
    },
}


def classify_effect(score: float) -> str:
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def load_manifest(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text())
    return {trait["slug"]: trait for trait in data["traits"]}


def parse_sscore(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            return {
                "sample_id": row["#IID"],
                "allele_ct": int(float(row["ALLELE_CT"])),
                "named_allele_dosage_sum": float(row["NAMED_ALLELE_DOSAGE_SUM"]),
                "effect_weight_avg": float(row["effect_weight_AVG"]),
                "effect_weight_sum": float(row["effect_weight_SUM"])
            }
    return None


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


def build_polygenic_entry(trait_summary: dict, manifest_entry: dict, sscore: dict) -> dict:
    slug = trait_summary["slug"]
    rule = POLYGENIC_RULES.get(slug, {
        "display_name": manifest_entry.get("label", slug.replace("-", " ").title()),
        "positive": "higher relative polygenic signal",
        "negative": "lower relative polygenic signal",
        "neutral": "mixed relative polygenic signal",
        "note": "Prototype polygenic output."
    })
    polarity = classify_effect(sscore["effect_weight_sum"])
    selected = manifest_entry.get("selected_candidate") or {}
    matched_variants = sscore["allele_ct"] // 2
    return {
        "trait": slug,
        "display_name": rule["display_name"],
        "type": "polygenic_demo",
        "result_label": rule[polarity],
        "summary": rule["note"],
        "coverage_note": f"Matched {matched_variants} scored variants from the selected PGS file.",
        "sample_id": sscore["sample_id"],
        "score": {
            "effect_weight_sum": sscore["effect_weight_sum"],
            "effect_weight_avg": sscore["effect_weight_avg"],
            "allele_ct": sscore["allele_ct"],
            "named_allele_dosage_sum": sscore["named_allele_dosage_sum"]
        },
        "source": {
            "pgs_id": trait_summary.get("pgs_id") or selected.get("pgs_id"),
            "pgs_name": selected.get("name"),
            "score_url": trait_summary.get("score_url"),
            "plink_score_file": trait_summary.get("plink_score_file"),
            "result_prefix": trait_summary.get("result_prefix")
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Genie-style report JSON from a pipeline run.")
    parser.add_argument("--pipeline-summary", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--simple-traits", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    pipeline_summary_path = Path(args.pipeline_summary).expanduser().resolve()
    manifest = load_manifest(Path(args.manifest).expanduser().resolve())
    pipeline_summary = json.loads(pipeline_summary_path.read_text())

    report = {
        "sample_id": "",
        "product": "Genie",
        "report_type": "prototype_trait_report",
        "traits": [],
        "pipeline": {
            "vcf": pipeline_summary.get("vcf"),
            "genome_build": pipeline_summary.get("genome_build"),
            "pipeline_summary": str(pipeline_summary_path)
        }
    }

    for trait_summary in pipeline_summary.get("traits", []):
      if trait_summary.get("status") != "scored":
        continue
      slug = trait_summary["slug"]
      sscore_path = Path(trait_summary["result_prefix"] + ".sscore")
      sscore = parse_sscore(sscore_path)
      if not sscore:
        continue
      if not report["sample_id"]:
        report["sample_id"] = sscore["sample_id"]
      report["traits"].append(build_polygenic_entry(trait_summary, manifest.get(slug, {}), sscore))

    if args.simple_traits:
      report["traits"].extend(build_simple_entries(Path(args.simple_traits).expanduser().resolve()))

    report["traits"].sort(key=lambda item: item["display_name"].lower())

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"Wrote report to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
