# Execution & Evaluation Guide

This guide covers running the multi-agent customer support system from the CLI ([main.py](main.py)), testing candidate agent versions, enforcing the **Quality Gate** locally against the golden dataset ([data/eval_dataset.jsonl](data/eval_dataset.jsonl)), and deploying changes through automated Pull Requests.

---

## 1. Prerequisites & Versioning Setup

1. **Environment Configuration**: Configure your `.env` file:
   ```ini
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o-mini

   # Optional: LangSmith Tracing & Dataset Observability
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=lsv2_pt_...
   LANGSMITH_PROJECT=soporte-multiagente
   LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com
   LANGSMITH_DATASET_NAME=techstore-support-golden-v1
   ```
2. **Database Initialization**: The SQLite database (`data/soporte.db`) is automatically created and seeded on first run with synthetic Faker records and deterministic test cases (`C900`–`C906`, `P9001`–`P9008`).
3. **Active Agent Versions**: Production versions are managed in [src/agents/active_versions.yaml](src/agents/active_versions.yaml) (not in `.env`). Declarative YAML specs live under `src/agents/specs/<agent>/<version>.yaml`. Both the CLI and CI use this file as the single source of truth unless overridden with `--version` or `--versions`.

---

## 2. Interactive Mode (Running Tickets)

### 2.1 Send a Custom Ticket
```powershell
# Eligible VIP return
.venv\Scripts\python main.py --mensaje "Quiero devolver mi smartwatch del pedido P9001" --cliente C900 --pedido P9001

# Missing order ID (resolved via CRM customer lookup)
.venv\Scripts\python main.py --mensaje "Quiero devolver el último producto que compré" --cliente C900

# Test a candidate agent version on a specific message
.venv\Scripts\python main.py --mensaje "No puedo conectar mis auriculares por bluetooth" --cliente C904 --pedido P9005 --versions "soporte_tecnico:v4"
```

### 2.2 Run Sample Test Suite (8 Default Tickets)
```powershell
.venv\Scripts\python main.py
```

---

## 3. Running Automated Evaluations (`--eval`)

The benchmark runs through LangSmith against the 23 golden scenarios in [data/eval_dataset.jsonl](data/eval_dataset.jsonl). The [coverage matrix](data/eval_coverage.md) describes automated and manual checks.

### 3.1 Synchronize the dataset

Run this after changing the golden dataset. The evaluation checks remote inputs and expectations against the checked-in scenarios before starting model calls.

```powershell
.\.venv\Scripts\python.exe main.py --sync-dataset
```

If LangSmith contains extra examples, review them and remove them from the benchmark dataset before running again.

### 3.2 Run an experiment

```powershell
# Full benchmark using the active versions
.\.venv\Scripts\python.exe main.py --eval --fail-on-gate

# Test a prompt version with the same full benchmark
.\.venv\Scripts\python.exe main.py --eval --versions "triaje:v4" --fail-on-gate

# Filter a smoke run
.\.venv\Scripts\python.exe main.py --eval --category boundary_testing --limit 3
```

Full runs default to `data/latest_eval_report.json` and `data/latest_eval_report.md`. Use `--report-json` and `--report-md` to save a candidate elsewhere. Filtered runs write to `outputs/` by default and cannot update a baseline or replace the full reports. The earlier `--eval --langsmith` spelling remains accepted.

### 3.3 Establish a baseline after an evaluation change

If the current baseline predates benchmark fingerprints or uses different checks, supply a path to a new file. The run applies the absolute thresholds and saves candidate metrics after passing the gate.

```powershell
$baseline = ".\outputs\baseline-$(Get-Date -Format yyyyMMdd-HHmmss).json"
.\.venv\Scripts\python.exe main.py --eval --baseline $baseline --update-baseline
```

## 4. Evaluate and promote a candidate

1. Create or update the candidate spec and run the full LangSmith benchmark with its version override.
2. Review the per-scenario failures and manual criteria in the report. Compare only runs with compatible benchmark fingerprints.
3. Update [active_versions.yaml](src/agents/active_versions.yaml) when promoting the candidate. Archive the candidate baseline under [data/baselines](data/baselines), index it in the [agent history](AGENT_IMPROVEMENTS_HISTORY.md#4-baseline-history), and update the active baseline if approved.
4. Commit both reports with the evaluated source. The [CI workflow](.github/workflows/eval-gate.yml) runs unit tests, verifies full scenario coverage, active versions, runtime and benchmark fingerprints, and checks that Markdown matches the JSON report.

---

## 5. Core Quality Targets & Decision Hierarchy

The system grades versions against a **3-tier decision hierarchy** rather than treating all metrics equally:

### 5.1 Full Pipeline Quality Gate

| Decision Priority | Metric | Target | How to Compare Pipeline Candidates |
|---|---|---:|---|
| **1. Hard Gate (Safety & Escalation)** | `escalation_accuracy` | **`>= 95.0%`** | Must pass first. Guarantees mandatory escalations without false alerts. |
| **1b. Hard Gate (Policy Compliance)** | `mean_qa_politica` | **`>= 4.50 / 5`** | Must pass first. Enforces return windows and ownership rules. |
| **2. Primary Winner Metric** | **`pass_rate`** | **`>= 85.0%`** | **Pick version with higher pass rate** (% of end-to-end flawless tickets). |
| **3. Tie-Breaker** | `first_pass_qa_approval_rate`| **`>= 80.0%`** | % of tickets approved by QA on the first try without retries. |

### 5.2 Cost & Performance Metrics (Informative Tracking)
These metrics are compared against [data/baseline_pipeline.json](data/baseline_pipeline.json) showing percentage delta ($\Delta \%$), but do not block the gate:
* **`avg_cost_usd`**: Estimated cost from the reported model and measured input/output tokens. The metric is unavailable when pricing or usage is missing.
* **`avg_tokens`**: Average total tokens consumed per ticket.
* **`avg_latency_seconds`**: End-to-end elapsed time per ticket.
* **`avg_ttft_seconds`**: Unavailable while agents use non-streaming invocations.

*(For detailed historical results across `v1` $\rightarrow$ `v2` $\rightarrow$ `v3`, see [AGENT_IMPROVEMENTS_HISTORY.md](AGENT_IMPROVEMENTS_HISTORY.md), [INFRASTRUCTURE_IMPROVEMENTS_HISTORY.md](INFRASTRUCTURE_IMPROVEMENTS_HISTORY.md), and [docs/eval_history/](docs/eval_history/)).*

---

## 6. Output Artifacts & File Structure

| File | Purpose | Version Controlled? |
|---|---|:---:|
| `data/latest_eval_report.md` | Markdown summary rendered as a comment on GitHub PRs | ✅ Yes |
| `data/latest_eval_report.json` | Full structured evaluation output for CI validation | ✅ Yes |
| `data/baseline_pipeline.json` | Certified production baseline standard for regression checks | ✅ Yes |
| `data/eval_dataset.jsonl` | 23 golden evaluation test scenarios | ✅ Yes |
| `outputs/resultados_*.json` | Full ticket trace for interactive runs (`--mensaje`) | ❌ No (`.gitignore`) |
| `outputs/eval-smoke-*.json` and `.md` | Filtered LangSmith evaluation reports | ❌ No (`.gitignore`) |
