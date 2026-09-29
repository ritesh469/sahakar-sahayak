# Run Experiments 1-3 (P12/P13) one after another; a failed config does not stop the rest.
# Results: results/raw/<config>_<timestamp>.csv (per question) + one row per run in results/summary.csv.
#
# Usage (PowerShell, repo root):
#   powershell -ExecutionPolicy Bypass -File scripts\run_all_experiments.ps1 [--no-ragas] [--questions eval/coop_questions.yaml]
# Needs: Postgres/Qdrant up, collections coop_256 / coop_512 / coop_1024 ingested, API stopped
# (GPU memory, CLAUDE.md S11). Generation configs (exp3_*) are limited by the Groq free tier.

$ErrorActionPreference = "Continue"
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force "results\logs" | Out-Null

$configs = @(
    "exp1_chunk_256", "exp1_chunk_512", "exp1_chunk_1024",
    "exp2_bm25", "exp2_tfidf", "exp2_dense", "exp2_hybrid", "exp2_dense_rerank",
    "exp3_hybrid", "exp3_hybrid_rerank"
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
        Write-Host "!!! $name failed, see $log"
        $failed += $name
    }
}

# Paper tables (results/*_results.csv) from the latest run of each config
cmd /c "uv run python eval/make_result_tables.py"

if ($failed.Count -gt 0) {
    Write-Host ("Failed: " + ($failed -join ", "))
    exit 1
}
Write-Host "All done. Summary: results\summary.csv"
