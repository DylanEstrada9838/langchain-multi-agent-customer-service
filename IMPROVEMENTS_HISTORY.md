# Project Improvements History

This document synthesizes the architectural, agent prompt, and evaluation automation improvements developed across the project lifecycle, tracking the progression from initial proof-of-concept (**`v1`**) to production-ready multi-agent system (**`v3`**).

---

## 1. Executive Summary & Evolution Overview

The multi-agent customer support system for TechStore was iteratively refined using an empirical evaluation dataset of 23 representative scenarios ([data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl)) covering happy paths, edge cases, boundary conditions, and tool invocation trajectories.

```
       v1 (Baseline PoC)               v2 (Structured Guidance)              v3 (Production Approved)
 ┌───────────────────────────┐       ┌───────────────────────────┐       ┌───────────────────────────┐
 │ Pass Rate:         65.22% │  ──>  │ Pass Rate:         86.96% │  ──>  │ Pass Rate:         95.65% │
 │ Escalation Acc:    100.0% │       │ Escalation Acc:    86.36% │       │ Escalation Acc:    95.45% │
 │ Policy Compliance: 4.68/5 │       │ Policy Compliance: 4.73/5 │       │ Policy Compliance: 5.00/5 │
 │ Gate Status:       FAILED │       │ Gate Status:       FAILED │       │ Gate Status:      APPROVED│
 └───────────────────────────┘       └───────────────────────────┘       └───────────────────────────┘
```

### Metrics Comparison Across Agent Generations

| Quality Target / Metric | Gate Threshold | `v1` PoC | `v2` Structured | `v3` Production Baseline | Net Improvement |
|:---|:---:|:---:|:---:|:---:|:---:|
| **Quality Gate Verdict** | **ALL PASS** | ❌ `NEEDS IMP.` | ❌ `NEEDS IMP.` | ✅ **`APPROVED`** | **All 4 Targets Met** |
| **1. Hard Gate: `escalation_accuracy`** | **$\ge 95.0\%$** | `100.0%` ✅ | `86.36%` ❌ | **`95.45%` (21/22)** ✅ | **+9.09 pts** vs v2 |
| **1b. Hard Gate: `mean_qa_politica`** | **$\ge 4.50 / 5$** | `4.68 / 5` ✅ | `4.73 / 5` ✅ | **`5.00 / 5.00`** ✅ | **+0.32 pts (100% adherence)** |
| **2. Primary Winner: `pass_rate`** | **$\ge 85.0\%$** | `65.22%` (15/23) ❌ | `86.96%` (20/23) ✅ | **`95.65%` (22/23)** ✅ | **+30.43 pts (+7 scenarios)** |
| **3. Tie-Breaker: `first_pass_qa_approval_rate`**| **$\ge 80.0\%$** | `95.45%` ✅ | `86.36%` ✅ | **`100.00%` (22/22)** ✅ | **+13.64 pts (Zero rework)** |
| *Diagnostic: `category_accuracy`* | - | `95.45%` | `100.00%` | **`100.00%` (22/22)** | **+4.55 pts** |
| *Diagnostic: `tool_trajectory_recall`* | - | `90.15%` | `100.00%` | **`100.00%` (23/23)** | **+9.85 pts** |
| *Diagnostic: `avg_latency_seconds`* | - | `11.88 s` | `11.77 s` | **`10.54 s`** | **-1.34 s faster** |
| *Diagnostic: `avg_tokens`* | - | `6,551` | `9,037` | **`8,584`** | **-453 tokens vs v2** |

---

## 2. Agent Prompt Improvements by Version

### 2.1 Version 1 (`v1`): Initial Proof-of-Concept & Root Cause Flaws
Evaluation of `v1` revealed 4 systematic failure modes (detailed in [src/agents/specs/v1/FLAWS_SUMMARY.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/agents/specs/v1/FLAWS_SUMMARY.md)):
1. **Omission of Sequential Tool Calling in `devoluciones`**: After checking eligibility (`verificar_devolucion -> elegible: true`), the agent drafted the response immediately without making a second tool call to `crear_etiqueta_devolucion`. It hallucinated fake RMA numbers (`RMA-123456`) or left placeholders (`[Código generado]`).
2. **Passive QA Approval**: The `qa` agent approved drafts containing invented RMA codes or unpopulated placeholders with `precision: 5` and `veredicto: aprobado`, violating grounding guarantees.
3. **Missing Logistics Checks in `consultas`**: On orders in `retrasado` status, the agent failed to query `verificar_incidencias(tipo="logistica")`, missing active carrier strikes and compensation guidelines.
4. **Vulnerability to Adversarial Injection in `triaje`**: On prompt injection attacks (`[SISTEMA ADMIN OVERRIDE]`), `triaje` misclassified operational intents as `queja_grave` instead of routing based on the underlying business action (`devolucion`).

---

### 2.2 Version 2 (`v2`): Few-Shot Guidance & Over-Rejection Challenge
`v2` addressed all 4 structural flaws (detailed in [src/agents/specs/v2/FLAWS_SUMMARY.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/agents/specs/v2/FLAWS_SUMMARY.md)):
1. **Two-Phase Return Process**: Explicitly separated `devoluciones` into Phase 1 (Verification) and Phase 2 (Mandatory Label Generation) before drafting.
2. **Mandatory Incidents Lookup**: Forced `consultas` to verify logistical incidents whenever shipment delays occurred.
3. **Adversarial Resilience**: Hardened `triaje` to ignore meta-tags (`[SISTEMA...]`, `[ADMIN OVERRIDE]`) and extract order SKU from CRM `pedidos_recientes`.
4. **Emergence of QA Over-Rejection**: Overly aggressive QA rejection rules caused 3 false escalations (`EVAL-012`, `EVAL-017`, `EVAL-018`):
   - Rejecting valid policy-based return denials (out-of-window requests).
   - Rejecting accurate notifications that an order does not exist in the ERP.
   - Dropping `escalation_accuracy` to `86.36%`, which violated the Hard Gate ($\ge 95\%$).

---

### 2.3 Version 3 (`v3`): Production Baseline (`APPROVED`)
`v3` resolved the QA boundary issues, achieving full compliance with all Core Quality Targets (detailed in [src/agents/specs/v3/FLAWS_SUMMARY.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/agents/specs/v3/FLAWS_SUMMARY.md)):
1. **Calibrated QA Grounding**:
   - Taught QA that legitimate denials (`elegible: false`) with recorded reasons must be approved with `5/5` policy score and no label creation required.
   - Approved non-existent order notifications as 100% accurate without requiring carrier lookups.
2. **Flawless Policy Enforcement**: Achieved `5.00 / 5.00` mean policy adherence across all 23 scenarios.
3. **Zero-Rework Efficiency**: `first_pass_qa_approval_rate` reached `100.0%` on end-to-end scenarios, eliminating retry latency.
4. **Verified 4-Pillar Baseline**: Certified for production deployment across Quality, Cost, Performance, and Safety pillars.

---

## 3. Infrastructure & Evaluation Automation Improvements

In addition to agent prompt engineering, significant software engineering improvements were introduced to make evaluations repeatable, transparent, and scalable:

### 3.1 Live Telemetry & Progress Logging
- **Flushed Stdout Execution**: Added real-time scenario logging in [src/pipeline/evaluator.py](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/pipeline/evaluator.py) (`flush=True`), preventing silent freezing and PowerShell QuickEdit deadlocks.
- **Per-Agent Token and Latency Tracking**: Instrumented each agent step (`AgentStepMetrics`) with input/output token counts and elapsed time.

### 3.2 LangSmith Dataset Synchronization
- **Idempotent Sync Module**: Built [src/pipeline/langsmith_eval.py](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/src/pipeline/langsmith_eval.py) with deterministic UUIDv5 generation (`sync_dataset_to_langsmith()`). Re-running updates examples in place without duplicates.
- **CLI Sync Command**: Exposed `python main.py --sync-dataset [--dataset-name <name>]`.

### 3.3 Target Wrapping & Evaluator Portability
- **Reusable Pipeline Target**: Created `make_pipeline_target()` wrapping `procesar_ticket()` for direct consumption by `langsmith.evaluate()`, formatting output schemas for both full pipeline and QA-isolated stages.

### 3.4 Deterministic Client-Side Code Evaluators
Implemented 5 deterministic evaluators in Python replicating the local quality checks:
1. `categoria_match`: Validates predicted routing against reference category.
2. `especialista_match`: Validates assigned specialist agent.
3. `escalado_match`: Validates human escalation decision.
4. `tool_trajectory_match`: Verifies full sequence and parameters of tool invocations.
5. `qa_quality_gate`: Validates QA verdict, rewrite acceptance, and adversarial draft rejections.

### 3.5 Automated Concurrent Experiment Runner
- **Command**: Added `python main.py --eval --langsmith [--version <ver>] [--max-concurrency <N>]`.
- **Parallel Execution**: Speeds up full 23-scenario evaluation runs via configurable concurrency while tracking experiments and feedback directly in LangSmith.

---

## 4. Pending Horizons & Future Roadmap (`v4`)

| Scenario | Component | Current Behavior | Recommended Fix for `v4` |
|:---|:---|:---|:---|
| **`EVAL-018`** | `soporte_tecnico` | Queries KB with query `"error E-404..."` and category `"domotica"`. Returns articles for unrelated devices (smart cameras / thermostats) due to broad keyword matching, preventing mandatory escalation for uncatalogued hardware errors. | Add semantic relevance check: if returned KB articles do not match the customer's specific product or exact error code, treat as empty results (`"resultados": []`) and set `requiere_escalado=True`. |
