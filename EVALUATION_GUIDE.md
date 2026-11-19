# Execution & Evaluation Guide

This guide explains how to run the multi-agent customer support system from the terminal ([main.py](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/main.py)), how to evaluate a single agent version or the full pipeline against [data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl), and how to use the **Core Quality Targets** to decide which version wins.

---

## 1. Prerequisites

1. Make sure your `.env` file has a valid `OPENAI_API_KEY`:
   ```ini
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o-mini

   # Optional: LangSmith Tracing & Datasets
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=lsv2_pt_...
   LANGSMITH_PROJECT=soporte-multiagente
   LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
   LANGSMITH_DATASET_NAME=techstore-support-golden-v1
   ```
2. On the first run, the SQLite database (`data/soporte.db`) is automatically created and seeded with synthetic Faker records plus the deterministic test customers (`C900`–`C906`) and orders (`P9001`–`P9008`).
3. **Agent versions** are not set in `.env`. The production version of each agent lives in [src/agents/active_versions.yaml](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/agents/active_versions.yaml) (one entry per agent, files under `src/agents/specs/<agent>/<version>.yaml`). The CLI, the pipeline and CI all use it unless you pass `--version` / `--versions`. Model experiments are a new version file with a `model:` block (e.g. `model_name`, `temperature`).

---

## 2. Running Tickets (Interactive / Sample Mode)

### 2.1 Send a Single Custom Ticket
Use `--mensaje`, `--cliente`, and optionally `--pedido`:

```powershell
# Example 1: Eligible VIP return
.venv\Scripts\python main.py --mensaje "Quiero devolver mi smartwatch del pedido P9001" --cliente C900 --pedido P9001

# Example 2: Omitted order ID (resolved via CRM pedidos_recientes)
.venv\Scripts\python main.py --mensaje "Quiero devolver el último producto que compré" --cliente C900

# Example 3: Severe VIP complaint with a specific triage version (v2)
.venv\Scripts\python main.py --mensaje "Es inaceptable que mi pedido P9004 siga retrasado, exijo solución" --cliente C903 --pedido P9004 --version v2

# Example 4: Mix specific agent versions across the pipeline
.venv\Scripts\python main.py --mensaje "Mis auriculares del pedido P9005 no conectan por bluetooth" --cliente C904 --pedido P9005 --versions "triaje:v2,soporte_tecnico:v1,qa:v1"
```

### 2.2 Run All 8 Sample Tickets (`src/data/sample_tickets.py`)
```powershell
.venv\Scripts\python main.py
```

---

## 3. Running Evaluations (`--eval` Mode)

All evaluations run against the 23 scenarios in [data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl) (mapped in [data/eval_coverage.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_coverage.md)).

### 3.1 Evaluate a Single Agent Version in Isolation (`triaje`)
Runs only the Triage agent (`v1`, `v2`, or `v3`) without calling the specialists or QA—ideal for fast, low-cost prompt iteration and A/B testing:

```powershell
# Compare triaje v1 vs v2 vs v3 across all scenarios
.venv\Scripts\python main.py --eval --agent triaje --version v1
.venv\Scripts\python main.py --eval --agent triaje --version v2
.venv\Scripts\python main.py --eval --agent triaje --version v3

# Filter by category or limit number of scenarios
.venv\Scripts\python main.py --eval --agent triaje --version v3 --category edge_case
.venv\Scripts\python main.py --eval --agent triaje --version v3 --limit 5
```

### 3.2 Evaluate the Full Multi-Agent Pipeline
Runs the complete `Triaje -> Especialista -> QA (with retry loop & escalation)` pipeline against `data/eval_dataset.jsonl`:

```powershell
# Full pipeline evaluation with the active versions (src/agents/active_versions.yaml)
.venv\Scripts\python main.py --eval

# Full pipeline evaluation with a specific version across all 5 agents (v1, v2, or v3)
.venv\Scripts\python main.py --eval --version v3

# Full pipeline evaluation mixing specific agent versions
.venv\Scripts\python main.py --eval --versions "triaje:v3,devoluciones:v3,soporte_tecnico:v3,consultas:v3,qa:v2"

# Filter by dataset category: happy_path | edge_case | boundary_testing | tool_invocation
.venv\Scripts\python main.py --eval --category happy_path
.venv\Scripts\python main.py --eval --category boundary_testing

# Quick smoke evaluation on the first N scenarios
.venv\Scripts\python main.py --eval --limit 3
```

### 3.3 Syncing the Golden Dataset to LangSmith (`--sync-dataset`)
You can upload or update all 23 scenarios from [data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl) into your LangSmith Datasets workspace idempotently (using deterministic `uuid5` example IDs so re-running updates existing examples in place without creating duplicates):

```powershell
# Sync to the default dataset name in config.py / .env (techstore-support-golden-v1)
.venv\Scripts\python main.py --sync-dataset

# Or specify a custom LangSmith dataset name
.venv\Scripts\python main.py --sync-dataset --dataset-name "techstore-support-golden-v2"
```

### 3.4 Running Automated Evaluations in LangSmith (`--eval --langsmith`)
Runs `langsmith.evaluate()` in the cloud using the 5 deterministic code evaluators (`categoria_match`, `especialista_match`, `escalado_match`, `tool_trajectory_match`, `qa_quality_gate`), executing scenarios concurrently:

```powershell
# Full evaluation of the production baseline (v3) across all 23 scenarios
.venv\Scripts\python main.py --eval --langsmith --version v3

# Evaluate with custom concurrency (default: 4 parallel workers)
.venv\Scripts\python main.py --eval --langsmith --version v3 --max-concurrency 4

# Fast smoke evaluation on a subset of scenarios
.venv\Scripts\python main.py --eval --langsmith --version v3 --limit 3

# Filter by scenario category
.venv\Scripts\python main.py --eval --langsmith --version v3 --category boundary_testing

# Compare different agent version combinations directly in LangSmith
.venv\Scripts\python main.py --eval --langsmith --versions "triaje:v3,devoluciones:v3,soporte_tecnico:v3,consultas:v3,qa:v2"
```

The CLI outputs the experiment URL, aggregate score table, and failure diagnostics. In the LangSmith web UI under **Datasets & Experiments -> techstore-support-golden-v1 -> Experiments**, you can click any row to inspect the run trace, token usage, and the specific evaluator diagnostic comments (under the **Feedback** tab). Experiments also carry six aggregate (summary) scores: `pass_rate`, `escalation_accuracy`, `mean_qa_politica`, `first_pass_qa_approval_rate`, `avg_tokens` and `avg_latency_seconds`.

### 3.5 Quality Gate (`--fail-on-gate`) and Baseline
The LangSmith runner always evaluates the **Quality Gate**: the absolute thresholds of section 4.2 plus a **regression check against the committed baseline** ([data/baseline_pipeline.json](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/baseline_pipeline.json)). Tolerances: `±0.05` on rates (about one scenario of 23) and `±0.25` on `mean_qa_politica`. `avg_tokens` and `avg_latency_seconds` are reported with their delta but never block.

```powershell
# Full run, exit code 1 if the gate fails (0 = pass, 2 = infrastructure error)
.venv\Scripts\python main.py --eval --langsmith --fail-on-gate

# Also write the report (Markdown for PR comments, JSON for tooling)
.venv\Scripts\python main.py --eval --langsmith --fail-on-gate --report-md outputs\eval_report.md --report-json outputs\eval_report.json

# Promote the current run as the new baseline (only if it passes the absolute thresholds)
.venv\Scripts\python main.py --eval --langsmith --update-baseline
```

`--fail-on-gate` and `--update-baseline` require the full dataset (no `--category` / `--limit`).

### 3.6 CI: Pull Request Workflow (`.github/workflows/eval-gate.yml`)
The workflow [eval-gate.yml](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/.github/workflows/eval-gate.yml) runs on every PR to `main` that touches `src/agents/**`, `src/pipeline/**`, `src/tools/**`, `src/schemas/**`, `src/llm/**`, `data/eval_dataset.jsonl`, `data/baseline_pipeline.json` or `main.py` (triggered by **paths**, not branch names), and manually via *Run workflow* (optional `versions` input).

How to run an experiment through CI:
1. Create a branch (any name, e.g. `experiment/triaje-prompt-v4`) and add `src/agents/specs/triaje/v4.yaml` (or a `model:` change for a model experiment).
2. In `src/agents/active_versions.yaml` set `triaje: v4`. **The PR evaluates what is listed there**; merging promotes it.
3. Open the PR. The job runs unit tests, syncs the CI dataset (`techstore-support-ci`), runs the full evaluation, and posts/updates a PR comment with thresholds, regression vs baseline, tokens and latency, and the LangSmith experiment link.
4. If the candidate is intentionally better, run `--update-baseline` locally and commit `data/baseline_pipeline.json` in a follow-up commit (CI compares against the baseline of the **base branch**, so a PR cannot hide a regression by editing its own baseline).

One-time repository setup: add the secrets `OPENAI_API_KEY` and `LANGSMITH_API_KEY` (optional repository variable `LANGSMITH_ENDPOINT`, default EU), and enable branch protection on `main` with the **Quality Gate** check required so a failing gate blocks the merge. PRs from forks are skipped because they do not receive secrets.

---

## 4. Core Quality Targets — How to Decide Which Version Wins

Instead of weighing 11 metrics equally, the evaluator grades each run against a **3-tier decision hierarchy** (`quality_targets` in the terminal table and JSON report) and emits an overall `quality_gate_passed: true | false` verdict:

### 4.1 Decision Hierarchy for Single-Agent `triaje` (`--eval --agent triaje`)

| Decision Priority | Metric | Target | How to Compare `v1` vs `v2` |
|---|---|---|---|
| **1. Hard Gate (CRM Lookup)** | `tool_call_accuracy` | **`>= 100.0%`** (`1.00`) | Must pass first. Triage must always call `consultar_cliente` before classifying. |
| **2. Primary Winner Metric** | `category_accuracy` | **`>= 90.0%`** (`0.90`) | **Pick the version with higher `category_accuracy`.** It determines which specialist receives the ticket. |
| **3. Tie-Breaker** | `priority_accuracy` | **`>= 85.0%`** (`0.85`) | If two versions tie on `category_accuracy`, pick the one with higher `priority_accuracy`. |

### 4.2 Decision Hierarchy for Full Pipeline (`--eval`)

| Decision Priority | Metric | Target | How to Compare Pipeline Versions |
|---|---|---|---|
| **1. Hard Gate (Safety & Escalation)** | `escalation_accuracy` | **`>= 95.0%`** (`0.95`) | Must pass first. Ensures hardware damage, missing KB articles, and pre-shipment cancellations escalate to a human without false escalations. |
| **1b. Hard Gate (Policy Score)** | `mean_qa_politica` | **`>= 4.50 / 5.00`** | Must pass first. Ensures return windows, ownership checks, and compensation policies are respected. |
| **2. Primary Winner Metric** | **`pass_rate`** | **`>= 85.0%`** (`0.85`) | **Pick the version with higher `pass_rate`.** Percentage of scenarios where category, routing, tool calls, escalation, and QA all pass together from start to finish. |
| **3. Tie-Breaker** | `first_pass_qa_approval_rate` | **`>= 80.0%`** (`0.80`) | If two versions tie on `pass_rate`, pick the one where the specialist gets approved by QA on the first try (`intentos_qa == 1`) more often. |

*(Secondary diagnostics such as `tool_trajectory_recall`, `mean_qa_score`, `avg_latency_seconds`, and `avg_tokens` are saved under `diagnostics` in the JSON file for debugging. For the verified `v3` production baseline and version-by-version benchmark results, see [SPECIFICATIONS.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/SPECIFICATIONS.md#L134-L160) and [docs/eval_history/v3_FLAWS_SUMMARY.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/docs/eval_history/v3_FLAWS_SUMMARY.md).)*

---

## 5. Saved Output Files (`outputs/`)

Every run saves a timestamped JSON file in `outputs/`:

1. **Ticket Runs (`outputs/resultados_YYYYMMDD_HHMMSS.json`)**:
   - Saves a list of `ResultadoTicket` objects with `clasificacion`, `especialista`, `borrador`, `qa`, `respuesta_final`, `intentos_qa`, `escalado_humano`, `versiones_agentes`, `metricas_agentes` (per-agent latency, tokens, and tool calls), `tool_calls`, `total_tokens`, and `segundos`.
2. **Evaluation Runs (`outputs/eval_<target>_YYYYMMDD_HHMMSS.json`)**:
   - Saves an `EvalSummaryReport` object containing:
     - `quality_gate_passed`: `true` if all Core Quality Targets met their threshold.
     - `quality_targets`: The 3-tier decision table with `priority`, `metric`, `value`, `target`, `passed`, and `description`.
     - `pass_rate`, `passed_scenarios`, `total_scenarios`.
     - `diagnostics`: Secondary metrics (`avg_latency_seconds`, `avg_tokens`, etc.).
     - `results`: Per-scenario breakdown of checks and tool calls.
