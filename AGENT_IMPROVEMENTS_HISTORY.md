# Agent System Improvements History

This document details the evolutionary journey, prompt engineering refinements, and architectural progression of all agents in the TechStore multi-agent customer support system from baseline proof-of-concept (**`v1`**) to production-ready deployment (**`v3`**).

---

## 1. Executive Summary & Evolution Overview

The multi-agent customer support system was iteratively evaluated against a benchmark dataset of 23 representative scenarios ([data/eval_dataset.jsonl](data/eval_dataset.jsonl)), testing routing accuracy, tool trajectory recall, human escalation calibration, policy compliance, and adversarial resilience.

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
| *Diagnostic: `avg_cost_usd`* | - | - | - | **`$0.0019` / ticket** | **Monetary baseline** |
| *Diagnostic: `avg_ttft_seconds`* | - | - | - | **`10.20 s`** | **Pre-streaming baseline** |
| *Diagnostic: `avg_latency_seconds`* | - | `11.88 s` | `11.77 s` | **`10.54 s`** | **-1.34 s faster** |
| *Diagnostic: `avg_tokens`* | - | `6,551` | `9,037` | **`8,584`** | **-453 tokens vs v2** |

---

## 2. Agent-by-Agent Evolution & Root Cause Analysis

The system comprises 5 specialized agents collaborating via an orchestrator:

```mermaid
flowchart TD
    User([Customer Message]) --> Triaje[Agente de Triaje]
    Triaje -->|devolucion| Devoluciones[Agente de Devoluciones]
    Triaje -->|soporte_tecnico| Soporte[Agente de Soporte Técnico]
    Triaje -->|consulta_general / envio| Consultas[Agente de Consultas]
    Triaje -->|queja_grave / out_of_scope| Humano([Escalado Humano])
    
    Devoluciones --> QA[Agente de QA / Verificador]
    Soporte --> QA
    Consultas --> QA
    
    QA -->|aprobado| Approved([Respuesta al Cliente])
    QA -->|rechazado + feedback| Retry{Reintento <= 2}
    Retry -->|Sí| Devoluciones
    Retry -->|Sí| Soporte
    Retry -->|Sí| Consultas
    Retry -->|No (Excedido)| Humano
```

### 2.1 Agente de Triaje (`triaje`)

Responsible for classification, intent extraction, sentiment analysis, and routing to specialized agents or direct human escalation.

- **`v1` Flaws**:
  - Susceptible to prompt injection attacks (e.g., `[SISTEMA ADMIN OVERRIDE]`). Misclassified operational inquiries disguised with adversarial tags as `queja_grave`, causing false escalations.
  - Inconsistent SKU extraction when tickets referenced multiple historical orders.
- **`v2` Improvements**:
  - Implemented adversarial hardening instructions explicitly directing the LLM to ignore meta-tags, simulated system prompts, or override prefixes.
  - Reinforced CRM lookups (`pedidos_recientes`) to correlate ticket context with customer history.
- **`v3` Production Baseline**:
  - Achieved **`100.00%`** category classification accuracy across all 23 evaluation scenarios.
  - Decoupled into [src/agents/specs/triaje/v3.yaml](src/agents/specs/triaje/v3.yaml).

---

### 2.2 Agente de Devoluciones (`devoluciones`)

Handles return eligibility verification, warranty lookups, and prepaid return label generation according to TechStore return policies.

- **`v1` Flaws**:
  - **Omission of Sequential Tool Calling**: After calling `verificar_devolucion` and receiving `elegible: true`, the agent drafted customer replies without invoking `crear_etiqueta_devolucion`. It hallucinated placeholder return numbers (`RMA-123456`, `[Código generado]`), violating grounding rules.
- **`v2` Improvements**:
  - Enforced a strict **Two-Phase Return Process**:
    - *Phase 1 (Verification)*: Call `verificar_devolucion`.
    - *Phase 2 (Action)*: If eligible, mandatory invocation of `crear_etiqueta_devolucion` prior to drafting any customer communication.
- **`v3` Production Baseline**:
  - Flawless tool sequence execution: achieved **`100.00%`** `tool_trajectory_recall`.
  - Proper explanation of ineligible returns (e.g., expired 30-day window) citing policy without attempting unauthorized label creation.
  - Decoupled into [src/agents/specs/devoluciones/v3.yaml](src/agents/specs/devoluciones/v3.yaml).

---

### 2.3 Agente de Consultas (`consultas`)

Addresses shipping tracking, order status, carrier logistics, and general store policy inquiries.

- **`v1` Flaws**:
  - **Missing Logistics Checks**: On delayed shipments (`retrasado`), the agent checked ERP status via `consultar_pedido` but failed to query active carrier incidents (`verificar_incidencias(tipo="logistica")`). As a result, customers were not informed of transport strikes or applicable compensation.
- **`v2` Improvements**:
  - Enforced mandatory logistical check whenever `estado == "retrasado"`.
- **`v3` Production Baseline**:
  - Handles edge cases cleanly: when an order does not exist in the ERP, provides immediate clarification without triggering spurious carrier searches.
  - Achieved `100.00%` trajectory recall and `5.00/5.00` policy adherence.
  - Decoupled into [src/agents/specs/consultas/v3.yaml](src/agents/specs/consultas/v3.yaml).

---

### 2.4 Agente de Soporte Técnico (`soporte_tecnico`)

Provides device diagnostics, knowledge base (KB) troubleshooting steps, and warranty-based hardware escalation.

- **`v1` Flaws**:
  - Queried knowledge base with overly broad search terms, occasionally providing generic advice without checking specific device category.
- **`v2` Improvements**:
  - Added structured diagnostic protocols requiring model identification and error code matching before prescribing repairs.
- **`v3` Production Baseline**:
  - Strong diagnostic workflows for catalogued device errors (audio, smartphones, connectivity).
  - Decoupled into [src/agents/specs/soporte_tecnico/v3.yaml](src/agents/specs/soporte_tecnico/v3.yaml).
- **Known Remaining Edge Case (`EVAL-018`)**:
  - When querying uncatalogued home automation error codes (e.g., `"error E-404"` on smart bulb), broad KB search retrieves articles for smart cameras/thermostats, causing the agent to attempt generic advice instead of immediate escalation. (See Section 4 for the v4 fix).

---

### 2.5 Agente de QA / Verificador (`qa`)

Acts as the final safeguard before any customer message is dispatched, auditing factual grounding, policy compliance, tone, and hallucinated data.

- **`v1` Flaws**:
  - **Passive Approval**: Approved drafts with invented RMA numbers or unpopulated placeholders with `veredicto: aprobado` and `precision: 5`, completely missing factual hallucinations.
- **`v2` Flaws (The Over-Rejection Challenge)**:
  - Overcorrected with overly aggressive rejection criteria, triggering 3 false rejections and unnecessary human escalations (`EVAL-012`, `EVAL-017`, `EVAL-018`):
    1. Rejected legitimate policy-based return denials (out-of-window requests).
    2. Rejected accurate notifications that an order does not exist in the ERP.
  - Dropped `escalation_accuracy` to **`86.36%`**, failing the Hard Gate ($\ge 95\%$).
- **`v3` Production Baseline (`APPROVED`)**:
  - **Calibrated QA Grounding**: Taught QA that legitimate denials (`elegible: false`) and non-existent orders are fully valid business conclusions requiring `5/5` policy score and no label creation.
  - Achieved **`100.00%` first-pass QA approval rate** on end-to-end scenarios, eliminating retry latency.
  - Mean policy compliance reached a perfect **`5.00 / 5.00`**.
  - Decoupled into [src/agents/specs/qa/v3.yaml](src/agents/specs/qa/v3.yaml).

---

## 3. Deep-Dive Flaw Summaries by Generation

Detailed post-mortem and forensic analysis for each generation can be consulted in the evaluation history archive:

- [docs/eval_history/v1_FLAWS_SUMMARY.md](docs/eval_history/v1_FLAWS_SUMMARY.md): Comprehensive review of v1 failures (passive QA, missing tool calls, prompt injection susceptibility).
- [docs/eval_history/v2_FLAWS_SUMMARY.md](docs/eval_history/v2_FLAWS_SUMMARY.md): Analysis of v2 improvements and the QA over-rejection boundary dilemma.
- [docs/eval_history/v3_FLAWS_SUMMARY.md](docs/eval_history/v3_FLAWS_SUMMARY.md): Final certification report detailing the calibration that achieved the Approved Production Baseline.

---

## 4. Baseline history

| Status | Agent versions | Full-suite result | Evidence |
|---|---|---|---|
| Current approved baseline | All five agents on `v3` | 22/23 (95.65%) | [JSON snapshot](data/baselines/001-v3-original-checks.json) · [LangSmith run](https://eu.smith.langchain.com/o/a8f6e0b2-95a9-47ca-98e0-92a88c918ce8/projects/p/b97bf224-299f-4d83-92e5-1a0baa098a69) |
| Candidate passed the absolute gate | `triaje`, `devoluciones`, `soporte_tecnico`, and `consultas` on `v4`; `qa` on `v3` | 21/23 (91.30%). Remaining failures are `EVAL-004` and `EVAL-015`. | [Candidate JSON snapshot](data/baselines/002-v4-scenario-assertions-candidate.json) · [LangSmith run](https://eu.smith.langchain.com/o/a8f6e0b2-95a9-47ca-98e0-92a88c918ce8/projects/p/381a6b5c-8c45-4fa4-9755-bc68fcf81100) |

The two results used different checks and fixture dates. To measure the effect of prompt updates alone, evaluate both version sets with the same dataset, assertions, fixture date, and code revision. See [evaluation comparability](INFRASTRUCTURE_IMPROVEMENTS_HISTORY.md#evaluation-comparability).

### v4 prompt changes

- Triage assigns urgent priority to severe complaints that combine an explicit account-cancellation threat with a demand for immediate action. It leaves order and SKU fields empty for requests unrelated to store orders or products.
- Inquiries names the return exclusions, includes verified shipping details, and skips order lookups for entirely out-of-scope requests.
- Returns identifies the verified items in the order when the requested SKU is absent and asks the customer to confirm the intended item or order.
- Technical support checks whether the device, symptoms, error code, and affected service match the evidence. It escalates when no relevant guidance applies.

## 5. Future roadmap

| Scenario | Component | Current Behavior | Recommended Fix for `v4` |
|:---|:---|:---|:---|
| **Edge Returns** | `devoluciones` | Return request for damaged in-transit goods currently routes through standard 30-day window check. | Add expedited RMA path for carrier-damaged deliveries (`tipo: "dano_transporte"`) bypassing standard customer-remorse evaluation. |
