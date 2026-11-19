# Execution & Evaluation Guide

This guide covers running the multi-agent customer support system from the CLI ([main.py](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/main.py)), testing candidate agent versions, enforcing the **Quality Gate** locally against the golden dataset ([data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl)), and deploying changes through automated Pull Requests.

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
3. **Active Agent Versions**: Production versions are managed in [src/agents/active_versions.yaml](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/agents/active_versions.yaml) (not in `.env`). Declarative YAML specs live under `src/agents/specs/<agent>/<version>.yaml`. Both the CLI and CI use this file as the single source of truth unless overridden with `--version` or `--versions`.

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

All evaluations run against the 23 golden scenarios in [data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl) (mapped in [data/eval_coverage.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_coverage.md)).

### 3.1 Evaluate a Single Agent in Isolation (`triaje`)
Evaluates only the Triage agent without calling specialists or QA—ideal for fast, low-cost prompt iterations:
```powershell
# Evaluate specific triage version across all scenarios
.venv\Scripts\python main.py --eval --agent triaje --version v3

# Filter by category or subset
.venv\Scripts\python main.py --eval --agent triaje --version v3 --category edge_case --limit 5
```

### 3.2 Full Pipeline & LangSmith Quality Gate
Runs the full multi-agent pipeline (`Triaje -> Especialista -> QA -> Escalation`) in parallel with the 5 code evaluators, checks for baseline regressions, and automatically saves reports to `data/latest_eval_report.*`:

```powershell
# Standard: Evaluate production active versions with Quality Gate enforcement
.venv\Scripts\python main.py --eval --langsmith --fail-on-gate

# Test a candidate version without changing production yet
.venv\Scripts\python main.py --eval --langsmith --versions "triaje:v4" --fail-on-gate

# Fast smoke check on a subset (3 scenarios)
.venv\Scripts\python main.py --eval --langsmith --versions "triaje:v4" --limit 3

# Filter by scenario category: happy_path | edge_case | boundary_testing | tool_invocation
.venv\Scripts\python main.py --eval --langsmith --category boundary_testing

# Update the official baseline standard (when candidate improves the benchmark)
.venv\Scripts\python main.py --eval --langsmith --update-baseline
```

*Note: `--fail-on-gate` and `--update-baseline` require the full 23-scenario dataset (cannot combine with `--limit` or `--category`).*

### 3.3 Synchronize Dataset to LangSmith (`--sync-dataset`)
Idempotently updates all 23 scenarios into LangSmith Datasets using deterministic UUIDv5 identifiers:
```powershell
.venv\Scripts\python main.py --sync-dataset
```

---

## 4. End-to-End Developer Workflow (Step-by-Step)

```
  1. Edit Spec                  2. Evaluate Locally                 3. Promote & PR
┌──────────────────────┐      ┌─────────────────────────────┐     ┌──────────────────────────────┐
│ specs/<agent>/v4.yaml│  ──> │ python main.py              │ ──> │ active_versions.yaml (v4)    │
│ (prompt, model, temp)│      │   --eval --langsmith        │     │ Commit code + reports        │
└──────────────────────┘      │   --fail-on-gate            │     │ Open PR -> CI posts report   │
                              └─────────────────────────────┘     └──────────────────────────────┘
                                            │
                                            ▼ Auto-generated:
                                   • data/latest_eval_report.md
                                   • data/latest_eval_report.json
```

1. **Create the Candidate Version**:
   - Copy `src/agents/specs/<agent>/v3.yaml` to `v4.yaml` and edit the prompt or `model:` parameters.
2. **Evaluate Locally (100% Visibility, ~$0.04)**:
   - Run:
     ```powershell
     .venv\Scripts\python main.py --eval --langsmith --versions "<agent>:v4" --fail-on-gate
     ```
   - If regressions occur (exit code 1), fix them directly in your editor without polluting git.
   - If the candidate improves on production and you want to lock in the new standard:
     ```powershell
     .venv\Scripts\python main.py --eval --langsmith --versions "<agent>:v4" --update-baseline
     ```
3. **Promote the Version**:
   - Update [src/agents/active_versions.yaml](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/agents/active_versions.yaml) to point to `v4`.
4. **Open Pull Request**:
   - Commit the spec, `active_versions.yaml`, and the auto-generated `data/latest_eval_report.*` (and `data/baseline_pipeline.json` if updated).
   - Push your branch and open a PR.
5. **Zero-LLM CI Verification ([.github/workflows/eval-gate.yml](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/.github/workflows/eval-gate.yml))**:
   - GitHub Actions runs in ~15 seconds at **$0 cost** (no LLM calls in CI):
     - Executes unit tests (`pytest`).
     - Validates that `data/latest_eval_report.json` matches `active_versions.yaml` and that the Quality Gate passed.
     - Automatically posts `data/latest_eval_report.md` as a formatted comment on the PR.

---

## 5. Core Quality Targets & Decision Hierarchy

The system grades versions against a **3-tier decision hierarchy** rather than treating all metrics equally:

### 5.1 Single-Agent Triage (`--eval --agent triaje`)

| Decision Priority | Metric | Target | How to Compare Candidates |
|---|---|---:|---|
| **1. Hard Gate (CRM Lookup)** | `tool_call_accuracy` | **`>= 100.0%`** | Must pass first. Triage must always query CRM before classifying. |
| **2. Primary Winner Metric** | `category_accuracy` | **`>= 90.0%`** | **Pick the version with higher accuracy.** Routes tickets to specialists. |
| **3. Tie-Breaker** | `priority_accuracy` | **`>= 85.0%`** | Desempata versiones con igual acierto de categoría. |

### 5.2 Full Pipeline & Quality Gate (`--eval --langsmith --fail-on-gate`)

| Decision Priority | Metric | Target | How to Compare Pipeline Candidates |
|---|---|---:|---|
| **1. Hard Gate (Safety & Escalation)** | `escalation_accuracy` | **`>= 95.0%`** | Must pass first. Guarantees mandatory escalations without false alerts. |
| **1b. Hard Gate (Policy Compliance)** | `mean_qa_politica` | **`>= 4.50 / 5`** | Must pass first. Enforces return windows and ownership rules. |
| **2. Primary Winner Metric** | **`pass_rate`** | **`>= 85.0%`** | **Pick version with higher pass rate** (% of end-to-end flawless tickets). |
| **3. Tie-Breaker** | `first_pass_qa_approval_rate`| **`>= 80.0%`** | % of tickets approved by QA on the first try without retries. |

### 5.3 Cost & Performance Metrics (Informative Tracking)
These metrics are compared against [data/baseline_pipeline.json](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/baseline_pipeline.json) showing percentage delta ($\Delta \%$), but do not block the gate:
* **`avg_cost_usd`**: Financial cost per ticket calculated from model input/output token pricing.
* **`avg_tokens`**: Average total tokens consumed per ticket.
* **`avg_latency_seconds`**: End-to-end elapsed time per ticket.
* **`avg_ttft_seconds`**: Pre-streaming baseline measuring elapsed time until the user sees the first token.

*(For detailed historical results across `v1` $\rightarrow$ `v2` $\rightarrow$ `v3`, see [IMPROVEMENTS_HISTORY.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/IMPROVEMENTS_HISTORY.md) and [docs/eval_history/](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/docs/eval_history/)).*

---

## 6. Output Artifacts & File Structure

| File | Purpose | Version Controlled? |
|---|---|:---:|
| `data/latest_eval_report.md` | Markdown summary rendered as a comment on GitHub PRs | ✅ Yes |
| `data/latest_eval_report.json` | Full structured evaluation output for CI validation | ✅ Yes |
| `data/baseline_pipeline.json` | Certified production baseline standard for regression checks | ✅ Yes |
| `data/eval_dataset.jsonl` | 23 golden evaluation test scenarios | ✅ Yes |
| `outputs/resultados_*.json` | Full ticket trace for interactive runs (`--mensaje`) | ❌ No (`.gitignore`) |
| `outputs/eval_*.json` | Timestamped local evaluation debug logs | ❌ No (`.gitignore`) |
