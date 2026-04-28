# Genie Prototype Genomics Pipeline

This is a thin wrapper around existing open-source genomics tooling for a Genie-style prototype.

It piggybacks on:

- `bcftools` for VCF validation and basic QC
- `PLINK 2` for genotype conversion and scoring
- `PGS Catalog` for public polygenic score metadata and scoring files

It does not try to reinvent:

- VCF parsing
- genotype processing
- score computation

It only adds:

- a fixed Genie trait list
- PGS Catalog lookup for candidate scores
- orchestration from `VCF -> bcftools -> PLINK 2 --score`

## Files

- `genie_pipeline/traits.json`
  - fixed Genie shortlist of traits and query terms
- `genie_pipeline/fetch_pgs_candidates.py`
  - fetches candidate public PGS scores for each Genie trait
- `genie_pipeline/run_vcf_pipeline.py`
  - runs the local VCF pipeline using `bcftools` and `PLINK 2`
- `genie_pipeline/download_public_sample.py`
  - downloads a public benchmark/sample VCF
- `genie_pipeline/summarize_scores.py`
  - converts `.sscore` outputs into Genie-style summary JSON
- `genie_pipeline/derive_simple_traits.py`
  - derives heuristic traits such as eye color from specific variants
- `genie_pipeline/score_public_1000g_trait.py`
  - streams selected score positions for a public 1000 Genomes sample and runs a reduced demo score
- `genie_pipeline/report_builder.py`
  - assembles Genie-style report JSON from polygenic summaries and simple-trait outputs

## Install dependencies

You need these installed locally:

```bash
brew install bcftools
```

`plink2` is not available as a standard Homebrew formula on this machine. Install the official macOS ARM64 binary from [PLINK 2 downloads](https://www.cog-genomics.org/plink/2.0/) and place it on your `PATH`.

Python 3 is already present on this machine. The scripts use only the standard library.

## 1. Fetch public score candidates

```bash
python3 genie_pipeline/fetch_pgs_candidates.py \
  --traits genie_pipeline/traits.json \
  --out genie_pipeline/pgs_candidates.json
```

This creates a candidate manifest pulled from the PGS Catalog API.

## 2. Inspect and curate the candidate manifest

The generated manifest includes a heuristic `selected_candidate` per trait. You should inspect it before trusting it.

This is especially important for:

- intelligence
- autism
- ADHD
- schizophrenia
- anxiety
- depression
- bipolar disorder
- OCD
- insomnia
- migraine

## 3. Run the pipeline on a VCF

```bash
python3 genie_pipeline/run_vcf_pipeline.py \
  --vcf /absolute/path/to/sample.vcf.gz \
  --manifest genie_pipeline/pgs_candidates.json \
  --outdir genie_pipeline/output
```

The script will:

1. run `bcftools stats`
2. convert the VCF to a PLINK 2 dataset
3. download chosen PGS scoring files from the PGS Catalog
4. simplify them into PLINK score files
5. run `plink2 --score` for each selected trait

The script now keeps going if one trait fails, and records that failure in `summary.json`.

## 4. Summarize score outputs

```bash
python3 genie_pipeline/summarize_scores.py \
  --results-dir genie_pipeline/output/results \
  --manifest genie_pipeline/pgs_candidates.json \
  --out genie_pipeline/output/trait_summary.json
```

## 5. Derive simple traits like eye color

```bash
python3 genie_pipeline/derive_simple_traits.py \
  --vcf /absolute/path/to/sample.vcf.gz \
  --out genie_pipeline/output/simple_traits.json
```

Current implementation:

- `eye_color`
  - simple heuristic based on `rs12913832`

## 6. Download a public benchmark/sample

```bash
python3 genie_pipeline/download_public_sample.py --sample giab_hg001_grch37 --outdir genie_pipeline
```

Available sample presets:

- `1000g_hg00096_chr22`
- `giab_hg001_grch37`
- `giab_hg001_grch38`

## 7. Run the public-data demos

Reduced height demo on real public data:

```bash
python3 genie_pipeline/score_public_1000g_trait.py \
  --trait height \
  --sample HG00096 \
  --top-n 100 \
  --outdir genie_pipeline/output_public_hg00096_height_top100
```

Eye-color heuristic on a public chr15 subset:

```bash
bcftools view \
  -r 15:28100000-28400000 \
  -s HG00096 \
  -Oz \
  -o genie_pipeline/output_public_hg00096_eye_region.vcf.gz \
  https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/ALL.chr15.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz

bcftools index -f genie_pipeline/output_public_hg00096_eye_region.vcf.gz

python3 genie_pipeline/derive_simple_traits.py \
  --vcf genie_pipeline/output_public_hg00096_eye_region.vcf.gz \
  --out genie_pipeline/output_public_hg00096_eye_traits.json
```

Assemble a single Genie-style sample report:

```bash
python3 genie_pipeline/report_builder.py \
  --sample HG00096 \
  --polygenic-summary genie_pipeline/output_public_hg00096_height_top100/summary.json \
  --polygenic-summary genie_pipeline/output_public_hg00096_hair_top100/summary.json \
  --polygenic-summary genie_pipeline/output_public_hg00096_left_top100/summary.json \
  --simple-traits genie_pipeline/output_public_hg00096_eye_traits.json \
  --out genie_pipeline/output_public_hg00096_report.json
```

## Output structure

- `output/qc/`
  - `bcftools.stats`
- `output/work/`
  - PLINK intermediate files
- `output/scores/raw/`
  - downloaded PGS scoring files
- `output/scores/plink/`
  - simplified 3-column PLINK score files
- `output/results/`
  - one subfolder per trait with PLINK score output
- `output/summary.json`
  - pipeline run summary

## Important assumptions

- This bootstrap prefers harmonized `chr:pos` matching and falls back to VCF/score IDs when needed.
- It uses public PGS files as a starting point only.
- It does not handle imputation, ancestry adjustment, embryo-specific validation, or clinical interpretation.
- It is a prototype orchestration layer, not a production genomics engine.

## Next sensible step

Once you have a VCF that scores cleanly, the next job is not more infrastructure. It is:

- trait curation
- result normalization
- embryo-to-embryo comparison logic
- report language
