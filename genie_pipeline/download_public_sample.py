#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SAMPLES = {
    "1000g_hg00096_chr22": {
        "kind": "subset_remote_sample",
        "source_vcf": "https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/ALL.chr22.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz",
        "sample_id": "HG00096",
        "output_name": "HG00096.chr22.1000G.vcf.gz"
    },
    "giab_hg001_grch37": {
        "kind": "direct_vcf",
        "source_vcf": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/NA12878_HG001/latest/GRCh37/HG001_GRCh37_1_22_v4.2.1_benchmark.vcf.gz",
        "output_name": "HG001.GRCh37.GIAB.vcf.gz"
    },
    "giab_hg001_grch38": {
        "kind": "direct_vcf",
        "source_vcf": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/NA12878_HG001/latest/GRCh38/HG001_GRCh38_1_22_v4.2.1_benchmark.vcf.gz",
        "output_name": "HG001.GRCh38.GIAB.vcf.gz"
    }
}


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)


def require_tool(name: str) -> None:
    if not shutil.which(name):
        raise SystemExit(f"Required tool not found on PATH: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a public benchmark/sample VCF for Genie testing.")
    parser.add_argument("--sample", choices=sorted(SAMPLES), required=True)
    parser.add_argument("--outdir", default="genie_pipeline")
    args = parser.parse_args()

    require_tool("bcftools")

    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    sample = SAMPLES[args.sample]
    output_vcf = outdir / sample["output_name"]

    if sample["kind"] == "direct_vcf":
        run([
            "curl", "-L", "-o", str(output_vcf), sample["source_vcf"]
        ])
    else:
        run([
            "bcftools", "view",
            "-s", sample["sample_id"],
            "-Oz",
            "-o", str(output_vcf),
            sample["source_vcf"]
        ])

    run(["bcftools", "index", "-f", "-t", str(output_vcf)])
    print(f"Saved to {output_vcf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

