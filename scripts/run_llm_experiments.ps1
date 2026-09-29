# Run the experiments that need an LLM (answers): Exp 3 (answers + Ragas; Exp 4 and 5 are splits of
# exp3_hybrid_rerank) and Exp 6 (HyDE, CRAG, Self-RAG x 2 prompts, English), then rebuild the paper
# tables and figures. A failed config does not stop the rest; a run stopped by a provider daily
# limit prints a --resume command in its log.
#
# Usage (PowerShell, repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\run_llm_experiments.ps1 [--no-ragas]
# Needs: LLM key in .env (LLM_PROVIDER / LLM_MODEL_ANSWER / LLM_MODEL_GRADER), Postgres/Qdrant up,
# coop_512 ingested, API stopped (GPU memory, CLAUDE.md S11). All configs must use the same LLM.
# The guardrail test (eval/run_security_test.py) needs the API running, so it is started separately.

$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force "results\logs" | Out-Null

$configs = @(
    "exp3_hybrid_rerank", "exp3_hybrid",
    "exp6_selfrag", "exp6_selfrag_original", "exp6_crag", "exp6_hyde"
)

$failed = @()
foreach ($name in $configs) {
    $log = "results\logs\{0}_{1}.log" -f $name, (Get-Date -Format "yyyyMMdd_HHmmss")
    Write-Host "=== $name  (log: $log)"
    # cmd /c keeps native stderr out of PowerShell's error stream (see PowerShell 5.1 notes)
    cmd /c "uv run --env-file .env python eval/run_experiment.py --config configs/$name.yaml $args > `"$log`" 2>&1"
    if ($LASTEXITCODE -eq 0) {
        Get-Content $log -Tail 3
    } else {
        Write-Host "!!! $name failed (exit $LASTEXITCODE), see $log"
        $failed += $name
    }
}

# Paper tables and figures from the latest run of each config
cmd /c "uv run python eval/make_result_tables.py"
cmd /c "uv run python scripts/make_plots.py"

if ($failed.Count -gt 0) {
    Write-Host ("Failed: " + ($failed -join ", "))
    exit 1
}
Write-Host "All done. Summary: results\summary.csv, tables: results\*_results.csv, figures: results\figures"
