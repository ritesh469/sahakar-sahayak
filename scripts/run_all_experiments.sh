#!/usr/bin/env bash
# Run Experiments 1-3 (P12/P13) one after another; a failed config does not stop the rest.
# Results: results/raw/<config>_<timestamp>.csv (per question) + one row per run in results/summary.csv.
#
# Usage: bash scripts/run_all_experiments.sh [--no-ragas] [--questions eval/coop_questions.yaml]
# Needs: Postgres/Qdrant up, collections coop_256 / coop_512 / coop_1024 ingested, API stopped
# (GPU memory, CLAUDE.md S11). Generation configs (exp3_*) are limited by the Groq free tier.
set -u
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
mkdir -p results/logs

CONFIGS=(
  exp1_chunk_256 exp1_chunk_512 exp1_chunk_1024
  exp2_bm25 exp2_tfidf exp2_dense exp2_hybrid exp2_dense_rerank
  exp3_hybrid exp3_hybrid_rerank
)

failed=()
for name in "${CONFIGS[@]}"; do
  log="results/logs/${name}_$(date +%Y%m%d_%H%M%S).log"
  echo "=== $name  (log: $log)"
  if uv run --env-file .env python eval/run_experiment.py --config "configs/${name}.yaml" "$@" >"$log" 2>&1; then
    tail -n 3 "$log"
  else
    echo "!!! $name failed, see $log"
    failed+=("$name")
  fi
done

# Paper tables (results/*_results.csv) from the latest run of each config
uv run python eval/make_result_tables.py

if [ ${#failed[@]} -gt 0 ]; then
  echo "Failed: ${failed[*]}"
  exit 1
fi
echo "All done. Summary: results/summary.csv"
