#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


def load_manifest(path: Path) -> dict:
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


def classify(score_sum: float) -> str:
    if score_sum > 0:
        return "higher relative score"
    if score_sum < 0:
        return "lower relative score"
    return "neutral"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize PLINK .sscore outputs into Genie-style JSON.")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    results_dir = Path(args.results_dir).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    manifest = load_manifest(Path(args.manifest).expanduser().resolve())

    summary = {"results_dir": str(results_dir), "traits": []}

    for trait_dir in sorted(results_dir.iterdir()):
        if not trait_dir.is_dir():
            continue
        slug = trait_dir.name
        sscore_path = trait_dir / f"{slug}.sscore"
        score = parse_sscore(sscore_path)
        trait_meta = manifest.get(slug, {})
        if score is None:
            summary["traits"].append({
                "slug": slug,
                "label": trait_meta.get("label", slug),
                "status": "missing"
            })
            continue
        summary["traits"].append({
            "slug": slug,
            "label": trait_meta.get("label", slug),
            "status": "scored",
            "sample_id": score["sample_id"],
            "effect_weight_sum": score["effect_weight_sum"],
            "effect_weight_avg": score["effect_weight_avg"],
            "named_allele_dosage_sum": score["named_allele_dosage_sum"],
            "allele_ct": score["allele_ct"],
            "relative_label": classify(score["effect_weight_sum"])
        })

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"Wrote summary to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

