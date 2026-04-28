#!/usr/bin/env python3
import argparse
import gzip
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Required tool not found on PATH: {name}")
    return path


def ensure_dirs(root: Path) -> dict[str, Path]:
    paths = {
        "root": root,
        "qc": root / "qc",
        "work": root / "work",
        "scores_raw": root / "scores" / "raw",
        "scores_plink": root / "scores" / "plink",
        "results": root / "results"
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def download(url: str, destination: Path) -> Path:
    if destination.exists():
        return destination
    request = urllib.request.Request(url, headers={"User-Agent": "GeniePrototype/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def simplify_pgs_file(raw_gz_path: Path, output_path: Path) -> Path:
    with gzip.open(raw_gz_path, "rt", encoding="utf-8") as handle:
        header = None
        for line in handle:
            if line.startswith("#"):
                continue
            header = line.rstrip("\n").split("\t")
            break

        if not header:
            raise RuntimeError(f"No score header found in {raw_gz_path}")

        try:
            effect_allele_idx = header.index("effect_allele")
            effect_weight_idx = header.index("effect_weight")
        except ValueError as exc:
            raise RuntimeError(f"Expected score columns missing in {raw_gz_path}: {exc}") from exc

        rsid_idx = None
        for candidate in ("rsID", "hm_rsID"):
            if candidate in header:
                rsid_idx = header.index(candidate)
                break

        hm_chr_idx = header.index("hm_chr") if "hm_chr" in header else None
        hm_pos_idx = header.index("hm_pos") if "hm_pos" in header else None
        chr_name_idx = header.index("chr_name") if "chr_name" in header else None
        chr_position_idx = header.index("chr_position") if "chr_position" in header else None

        with output_path.open("w", encoding="utf-8") as out:
            out.write("variant_id\teffect_allele\teffect_weight\n")
            seen_variant_ids = set()
            for line in handle:
                if not line.strip():
                    continue
                fields = line.rstrip("\n").split("\t")
                if len(fields) <= effect_weight_idx:
                    continue
                rsid = fields[rsid_idx] if rsid_idx is not None and len(fields) > rsid_idx else ""
                effect_allele = fields[effect_allele_idx]
                effect_weight = fields[effect_weight_idx]
                variant_id = None
                if hm_chr_idx is not None and hm_pos_idx is not None:
                    hm_chr = fields[hm_chr_idx]
                    hm_pos = fields[hm_pos_idx]
                    if hm_chr and hm_chr != "." and hm_pos and hm_pos != ".":
                        variant_id = f"{hm_chr}:{hm_pos}"
                if not variant_id and chr_name_idx is not None and chr_position_idx is not None:
                    chr_name = fields[chr_name_idx]
                    chr_position = fields[chr_position_idx]
                    if chr_name and chr_name != "." and chr_position and chr_position != ".":
                        variant_id = f"{chr_name}:{chr_position}"
                if not variant_id or variant_id == ".":
                    variant_id = rsid

                if not variant_id or variant_id == "." or not effect_allele or not effect_weight:
                    continue
                if variant_id in seen_variant_ids:
                    continue
                seen_variant_ids.add(variant_id)
                out.write(f"{variant_id}\t{effect_allele}\t{effect_weight}\n")

    return output_path


def pick_score_url(selected_candidate: dict, genome_build: str) -> str | None:
    if genome_build == "GRCh38":
        return selected_candidate.get("harmonized_grch38") or selected_candidate.get("scoring_file")
    return selected_candidate.get("harmonized_grch37") or selected_candidate.get("scoring_file")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal Genie-style VCF scoring pipeline.")
    parser.add_argument("--vcf", required=True, help="Input VCF or VCF.GZ")
    parser.add_argument("--manifest", required=True, help="PGS candidate manifest JSON")
    parser.add_argument("--outdir", required=True, help="Output directory")
    parser.add_argument("--genome-build", default="GRCh37", choices=["GRCh37", "GRCh38"])
    parser.add_argument(
        "--only-traits",
        default="",
        help="Comma-separated trait slugs to run; default runs everything in the manifest"
    )
    args = parser.parse_args()

    require_tool("bcftools")
    require_tool("plink2")

    vcf_path = Path(args.vcf).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    paths = ensure_dirs(outdir)

    manifest = json.loads(manifest_path.read_text())
    only_traits = {item.strip() for item in args.only_traits.split(",") if item.strip()}
    summary = {
        "vcf": str(vcf_path),
        "manifest": str(manifest_path),
        "genome_build": args.genome_build,
        "traits": []
    }

    stats_path = paths["qc"] / "bcftools.stats"
    with stats_path.open("w", encoding="utf-8") as stats_handle:
        subprocess.run(
            ["bcftools", "stats", str(vcf_path)],
            stdout=stats_handle,
            check=True
        )

    plink_prefix = paths["work"] / "genotypes"
    run([
        "plink2",
        "--vcf", str(vcf_path),
        "--set-all-var-ids", "@:#",
        "--rm-dup", "force-first",
        "--make-pgen",
        "--out", str(plink_prefix)
    ])

    for trait in manifest["traits"]:
        if only_traits and trait["slug"] not in only_traits:
            continue
        selected = trait.get("selected_candidate")
        if not selected:
            summary["traits"].append({
                "slug": trait["slug"],
                "status": "skipped",
                "reason": "No selected candidate"
            })
            continue

        score_url = pick_score_url(selected, args.genome_build)
        if not score_url:
            summary["traits"].append({
                "slug": trait["slug"],
                "status": "skipped",
                "reason": "No compatible scoring file URL"
            })
            continue

        raw_gz_path = paths["scores_raw"] / f"{selected['pgs_id']}.txt.gz"
        plink_score_path = paths["scores_plink"] / f"{trait['slug']}.score.tsv"
        download(score_url, raw_gz_path)
        simplify_pgs_file(raw_gz_path, plink_score_path)

        trait_out_prefix = paths["results"] / trait["slug"] / trait["slug"]
        trait_out_prefix.parent.mkdir(parents=True, exist_ok=True)

        try:
            run([
                "plink2",
                "--pfile", str(plink_prefix),
                "--score", str(plink_score_path), "1", "2", "3", "header-read", "no-mean-imputation",
                "cols=+scoresums",
                "--out", str(trait_out_prefix)
            ])
            summary["traits"].append({
                "slug": trait["slug"],
                "label": trait["label"],
                "status": "scored",
                "pgs_id": selected["pgs_id"],
                "score_url": score_url,
                "plink_score_file": str(plink_score_path),
                "result_prefix": str(trait_out_prefix)
            })
        except subprocess.CalledProcessError as exc:
            summary["traits"].append({
                "slug": trait["slug"],
                "label": trait["label"],
                "status": "failed",
                "pgs_id": selected["pgs_id"],
                "score_url": score_url,
                "plink_score_file": str(plink_score_path),
                "result_prefix": str(trait_out_prefix),
                "error": str(exc)
            })

    summary_path = paths["root"] / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Wrote summary to {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
