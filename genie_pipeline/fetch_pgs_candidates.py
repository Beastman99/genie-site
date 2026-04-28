#!/usr/bin/env python3
import argparse
import json
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path

API_ROOT = "https://www.pgscatalog.org/rest"


def get_json(url: str) -> dict:
    last_error = None
    for attempt in range(5):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "GeniePrototype/0.1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                time.sleep(2 + attempt * 2)
                continue
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def trait_search(term: str) -> list[dict]:
    url = f"{API_ROOT}/trait/search?term={urllib.parse.quote(term)}"
    return get_json(url).get("results", [])


def score_detail(pgs_id: str) -> dict:
    return get_json(f"{API_ROOT}/score/{pgs_id}")


def normalize_date(value: str | None) -> str:
    return value or "0000-00-00"


def build_candidate(score: dict) -> dict:
    harmonized = score.get("ftp_harmonized_scoring_files") or {}
    return {
        "pgs_id": score.get("id"),
        "name": score.get("name"),
        "trait_reported": score.get("trait_reported"),
        "trait_mapped": [item.get("label") for item in score.get("trait_efo", [])],
        "variants_number": score.get("variants_number"),
        "weight_type": score.get("weight_type"),
        "genome_build": score.get("variants_genomebuild"),
        "date_release": score.get("date_release"),
        "license": score.get("license"),
        "matches_publication": score.get("matches_publication"),
        "scoring_file": score.get("ftp_scoring_file"),
        "harmonized_grch37": ((harmonized.get("GRCh37") or {}).get("positions")),
        "harmonized_grch38": ((harmonized.get("GRCh38") or {}).get("positions"))
    }


def candidate_sort_key(candidate: dict) -> tuple:
    return (
        0 if candidate.get("matches_publication") else 1,
        0 if candidate.get("harmonized_grch37") else 1,
        -int(candidate.get("variants_number") or 0),
        normalize_date(candidate.get("date_release"))
    )


def choose_best(candidates: list[dict]) -> dict | None:
    if not candidates:
      return None
    ranked = sorted(candidates, key=candidate_sort_key)
    return ranked[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch candidate PGS Catalog scores for Genie traits.")
    parser.add_argument("--traits", required=True, help="Path to traits.json")
    parser.add_argument("--out", required=True, help="Where to write the candidate manifest")
    parser.add_argument("--top-k", type=int, default=5, help="Candidates to retain per trait")
    parser.add_argument(
        "--max-score-details",
        type=int,
        default=8,
        help="Maximum score detail records to fetch per trait before ranking"
    )
    args = parser.parse_args()

    traits_path = Path(args.traits)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    traits_doc = json.loads(traits_path.read_text())
    output = {"generated_from": str(traits_path), "traits": []}

    for trait in traits_doc["traits"]:
        print(f"Resolving trait: {trait['label']}", flush=True)
        seen_pgs_ids = set()
        candidate_ids = []
        matched_terms = []

        for term in trait["search_terms"]:
            try:
                trait_hits = trait_search(term)
            except Exception as exc:
                matched_terms.append({
                    "term": term,
                    "error": str(exc)
                })
                continue
            if trait_hits:
                matched_terms.append({
                    "term": term,
                    "matched_trait_labels": [item["label"] for item in trait_hits[:5]]
                })
            for hit in trait_hits:
                for pgs_id in hit.get("associated_pgs_ids", []):
                    if pgs_id not in seen_pgs_ids:
                        seen_pgs_ids.add(pgs_id)
                        candidate_ids.append(pgs_id)

        candidates = []
        limited_ids = candidate_ids[: args.max_score_details]
        print(
            f"  terms matched={len(matched_terms)} candidate_ids={len(candidate_ids)} fetching={len(limited_ids)}",
            flush=True
        )

        for pgs_id in limited_ids:
            try:
                candidates.append(build_candidate(score_detail(pgs_id)))
            except Exception as exc:
                candidates.append({
                    "pgs_id": pgs_id,
                    "error": str(exc)
                })
            time.sleep(0.08)

        valid_candidates = [candidate for candidate in candidates if "error" not in candidate]
        ranked = sorted(valid_candidates, key=candidate_sort_key)[: args.top_k]

        output["traits"].append({
            "slug": trait["slug"],
            "label": trait["label"],
            "search_terms": trait["search_terms"],
            "matched_terms": matched_terms,
            "selected_candidate": choose_best(ranked),
            "candidates": ranked
        })

    out_path.write_text(json.dumps(output, indent=2))
    print(f"Wrote candidate manifest to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
