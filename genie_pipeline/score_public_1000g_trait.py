#!/usr/bin/env python3
import argparse
import csv
import json
import subprocess
import urllib.request
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PHASE3_BASE = "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502"


def load_run_module():
    spec = spec_from_file_location("run_vcf_pipeline", ROOT / "run_vcf_pipeline.py")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def choose_candidate(manifest: dict, trait_slug: str, pgs_id: str | None) -> dict:
    trait = next(t for t in manifest["traits"] if t["slug"] == trait_slug)
    if pgs_id:
        for candidate in trait["candidates"]:
            if candidate["pgs_id"] == pgs_id:
                return candidate
        raise SystemExit(f"No candidate {pgs_id} found for trait {trait_slug}")
    candidates = [c for c in trait["candidates"] if c.get("genome_build") == "GRCh37"]
    if not candidates:
        raise SystemExit(f"No GRCh37 candidates found for trait {trait_slug}")
    return min(candidates, key=lambda c: c.get("variants_number") or 10**18)


def download(url: str, destination: Path) -> Path:
    if destination.exists():
        return destination
    request = urllib.request.Request(url, headers={"User-Agent": "GeniePrototype/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        handle.write(response.read())
    return destination


def trim_score_file(score_path: Path, top_n: int, output_path: Path) -> Path:
    rows = []
    with score_path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            rows.append(row)
    rows.sort(key=lambda r: abs(float(r["effect_weight"])), reverse=True)
    rows = rows[:top_n]

    with output_path.open("w", encoding="utf-8") as out:
        out.write("variant_id\teffect_allele\teffect_weight\n")
        for row in rows:
            out.write(f"{row['variant_id']}\t{row['effect_allele']}\t{row['effect_weight']}\n")

    return output_path


def write_regions_by_chrom(score_path: Path, outdir: Path) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    by_chrom: dict[str, list[str]] = {}
    with score_path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            chrom, pos = row["variant_id"].split(":", 1)
            by_chrom.setdefault(chrom, []).append(f"{chrom}\t{pos}\n")

    region_files: dict[str, Path] = {}
    for chrom, rows in by_chrom.items():
        path = outdir / f"chr{chrom}.regions.tsv"
        path.write_text("".join(rows))
        region_files[chrom] = path
    return region_files


def fetch_subset_vcfs(sample: str, region_files: dict[str, Path], outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    vcfs = []
    for chrom in sorted(region_files, key=lambda c: (len(c), c)):
        remote_vcf = f"{PHASE3_BASE}/ALL.chr{chrom}.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz"
        local_vcf = outdir / f"chr{chrom}.{sample}.vcf.gz"
        run([
            "bcftools", "view",
            "-R", str(region_files[chrom]),
            "-s", sample,
            "-Oz",
            "-o", str(local_vcf),
            remote_vcf
        ])
        run(["bcftools", "index", "-f", str(local_vcf)])
        vcfs.append(local_vcf)
    return vcfs


def concat_vcfs(vcfs: list[Path], out_path: Path) -> Path:
    run(["bcftools", "concat", "-a", "-Oz", "-o", str(out_path), *[str(v) for v in vcfs]])
    run(["bcftools", "index", "-f", str(out_path)])
    return out_path


def summarize_sscore(sscore_path: Path) -> dict:
    with sscore_path.open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        row = next(reader)
    return {
        "sample_id": row["#IID"],
        "allele_ct": int(float(row["ALLELE_CT"])),
        "named_allele_dosage_sum": float(row["NAMED_ALLELE_DOSAGE_SUM"]),
        "effect_weight_avg": float(row["effect_weight_AVG"]),
        "effect_weight_sum": float(row["effect_weight_SUM"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a public 1000 Genomes sample on a reduced trait score.")
    parser.add_argument("--manifest", default=str(ROOT / "pgs_candidates.json"))
    parser.add_argument("--trait", default="height")
    parser.add_argument("--sample", default="HG00096")
    parser.add_argument("--top-n", type=int, default=500)
    parser.add_argument("--pgs-id", default="")
    parser.add_argument("--outdir", required=True)
    args = parser.parse_args()

    run_module = load_run_module()
    manifest = json.loads(Path(args.manifest).read_text())
    candidate = choose_candidate(manifest, args.trait, args.pgs_id or None)

    outdir = Path(args.outdir).expanduser().resolve()
    raw_dir = outdir / "raw"
    work_dir = outdir / "work"
    raw_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    raw_score_path = raw_dir / f"{candidate['pgs_id']}.txt.gz"
    full_score_path = work_dir / f"{args.trait}.full.score.tsv"
    trimmed_score_path = work_dir / f"{args.trait}.top{args.top_n}.score.tsv"
    score_url = candidate.get("harmonized_grch37") or candidate["scoring_file"]
    download(score_url, raw_score_path)
    run_module.simplify_pgs_file(raw_score_path, full_score_path)
    trim_score_file(full_score_path, args.top_n, trimmed_score_path)

    region_files = write_regions_by_chrom(trimmed_score_path, work_dir / "regions")
    vcfs = fetch_subset_vcfs(args.sample, region_files, work_dir / "chrom_vcfs")
    merged_vcf = concat_vcfs(vcfs, work_dir / f"{args.sample}.{args.trait}.top{args.top_n}.vcf.gz")

    plink_prefix = work_dir / "genotypes"
    run([
        "plink2",
        "--vcf", str(merged_vcf),
        "--set-all-var-ids", "@:#",
        "--rm-dup", "force-first",
        "--make-pgen",
        "--out", str(plink_prefix)
    ])

    result_prefix = outdir / "results" / args.trait / args.trait
    result_prefix.parent.mkdir(parents=True, exist_ok=True)
    run([
        "plink2",
        "--pfile", str(plink_prefix),
        "--score", str(trimmed_score_path), "1", "2", "3", "header-read", "no-mean-imputation",
        "cols=+scoresums",
        "--out", str(result_prefix)
    ])

    summary = {
        "trait": args.trait,
        "sample": args.sample,
        "top_n": args.top_n,
        "candidate": {
            "pgs_id": candidate["pgs_id"],
            "name": candidate["name"],
            "variants_number": candidate["variants_number"],
            "score_url": score_url,
        },
        "merged_vcf": str(merged_vcf),
        "score_file": str(trimmed_score_path),
        "sscore": summarize_sscore(result_prefix.with_suffix(".sscore")),
    }
    summary_path = outdir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"Wrote summary to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
