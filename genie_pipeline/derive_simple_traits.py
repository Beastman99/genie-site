#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path


def bcftools_query(vcf: str, region: str) -> str:
    cmd = [
        "bcftools", "query",
        "-r", region,
        "-f", "%ID\t%CHROM\t%POS\t%REF\t%ALT[\t%GT]\n",
        vcf
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


def eye_color_from_variants(lines: list[str]) -> dict:
    by_id = {}
    by_position = {}
    for line in lines:
        fields = line.strip().split("\t")
        if len(fields) >= 6:
            record = {
                "chrom": fields[1],
                "pos": fields[2],
                "ref": fields[3],
                "alt": fields[4],
                "gt": fields[5]
            }
            by_id[fields[0]] = record
            by_position[(fields[1], fields[2])] = record

    rs12913832 = by_id.get("rs12913832") or by_position.get(("15", "28365618"))
    if not rs12913832:
        return {
            "status": "missing",
            "trait": "eye_color",
            "note": "Key eye-color variant rs12913832 not found in input VCF."
        }

    gt = rs12913832["gt"].replace("|", "/")
    alt_is_blue_associated = rs12913832["ref"] == "A" and rs12913832["alt"] == "G"
    if alt_is_blue_associated:
        if gt == "1/1":
            label = "blue / lighter eyes more likely"
        elif gt in {"0/1", "1/0"}:
            label = "intermediate / mixed eye color signal"
        else:
            label = "brown / darker eyes more likely"
    else:
        if gt == "0/0":
            label = "blue / lighter eyes more likely"
        elif gt in {"0/1", "1/0"}:
            label = "intermediate / mixed eye color signal"
        else:
            label = "brown / darker eyes more likely"

    return {
        "status": "derived",
        "trait": "eye_color",
        "method": "simple rs12913832 heuristic",
        "variant": {
            "id": "rs12913832",
            "chrom": rs12913832["chrom"],
            "pos": rs12913832["pos"],
            "ref": rs12913832["ref"],
            "alt": rs12913832["alt"],
            "genotype": gt
        },
        "prediction": label
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive simple heuristic traits from a VCF.")
    parser.add_argument("--vcf", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    query_output = bcftools_query(args.vcf, "15:28100000-28400000")
    lines = [line for line in query_output.splitlines() if line.strip()]
    result = {
        "vcf": args.vcf,
        "traits": [
            eye_color_from_variants(lines)
        ]
    }

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Wrote simple trait summary to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
