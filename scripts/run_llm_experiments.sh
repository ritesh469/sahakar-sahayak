#!/usr/bin/env bash
# Run the experiments that need an LLM (answers): Exp 3 (answers + Ragas; Exp 4 and 5 are splits of
# exp3_hybrid_rerank) and Exp 6 (HyDE, CRAG, Self-RAG x 2 prompts, English), then rebuild the paper
# tables and figures. A failed config does not stop the rest; a run stopped by a provider daily
# limit prints a --resume command in its log.
#
# Usage: bash scripts/run_llm_experiments.sh [--no-ragas]
# Needs: LLM key in .env (LLM_PROVIDER / LLM_MODEL_ANSWER / LLM_MODEL_GRADER), Postgres/Qdrant up,
# coop_512 ingested, API stopped (GPU memory, CLAUDE.md S11). All configs must use the same LLM.
# The guardrail test (eval/run_security_test.py) needs the API running, so it is started separately.
set -u
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
mkdir -p results/logs

CONFIGS=(
  exp3_hybrid_rerank exp3_hybrid
  exp6_selfrag exp6_selfrag_original exp6_crag exp6_hyde
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

# Paper tables and figures from the latest run of each config
uv run python eval/make_result_tables.py
uv run python scripts/make_plots.py

if [ ${#failed[@]} -gt 0 ]; then
  echo "Failed: ${failed[*]}"
  exit 1
fi
echo "All done. Summary: results/summary.csv, tables: results/*_results.csv, figures: results/figures"
