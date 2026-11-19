# Multi-Agent Customer Support System — Design & Product Specification

> **Document Purpose:** Pre-implementation specification for the TechStore Multi-Agent Customer Support System. This document defines **why the system is being built**, **what capabilities and constraints it must have**, and **how we will measure its quality** before writing production code.

---

## 1. User Intent — Why the System Exists

### 1.1 System Job Description
We need to build an **automated Tier-1 / Tier-2 customer support resolution and quality-assurance system** for an electronics e-commerce retailer (**TechStore**).

When a customer submits a support ticket, the system must act as a coordinated team of specialized AI agents that:
1. **Triage & Classify**: Identify who the customer is (loyalty tier and history), determine what kind of problem they have (return, technical issue, general inquiry, or severe complaint), assign an urgency level, and extract key entities (such as order ID or product SKU).
2. **Route Deterministically**: Direct the ticket to the right domain specialist based on the triage classification rather than relying on a single generalist prompt.
3. **Investigate & Draft a Grounded Solution**: Query internal company systems (CRM, ERP/Orders, Product Catalog, Reverse Logistics, Technical Knowledge Base, and Active Incident Board) to draft an accurate response and perform authorized actions (such as generating a return shipping label).
4. **Audit Quality Before Delivery (QA)**: Review every specialist draft against company policies, verified facts, and the customer's loyalty tier. If the draft fails quality standards, the system must either rewrite it, send it back to the specialist for correction, or escalate the ticket to a human agent.

### 1.2 Target Audience
| Audience | Needs & How They Interact with the System |
|---|---|
| **End Customers (`Estándar`, `Premium`, `VIP`)** | Submit support tickets in natural language (Spanish). They expect fast, accurate answers, immediate return labels when eligible, clear troubleshooting steps, and fair treatment aligned with their loyalty tier. |
| **Human Support Specialists (Tier-3 Escalations)** | Should only receive tickets that genuinely require human intervention (hardware replacement, unlisted technical issues, or cases that fail automated QA verification), pre-populated with triage and investigation context. |
| **Support Operations & QA Managers** | Need structured audit logs showing why a ticket was classified a certain way, which data was verified, how the response scored on quality dimensions, and whether escalation was required. |
| **AI & Platform Engineers** | Need a modular architecture where agent prompts can be versioned independently (`v1`, `v2`, ...) and where the underlying LLM provider (OpenAI initially; Anthropic or Gemini in the future) or database engine (SQLite initially; PostgreSQL in production) can be swapped without rewriting business logic. |

### 1.3 Pain Points Addressed
1. **Hallucinations in Customer Facing Replies**: Single-agent chatbots frequently invent order statuses, return eligibility, or RMA numbers. We need strict tool-based grounding plus an independent QA agent that blocks unverified claims.
2. **Inconsistent Application of Tiered Policies**: Business rules vary by customer segment (e.g., 30-day returns for Standard/Premium vs. 60-day returns for VIPs; tiered compensation coupons for delays and severe complaints). Agents often forget or mix up these rules without structured verification.
3. **Wasted Troubleshooting During Outages**: Support teams often walk customers through device resets when the real root cause is an active cloud outage or regional carrier strike. The system must check active global/regional incidents first.
4. **Permission Creep & Prompt Overload**: Giving a single agent every tool and policy leads to wrong tool calls and unstable behavior. Separating responsibilities across specialized agents enforces the principle of least privilege.

---

## 2. Capabilities — What the System Must Do, Access, and Restrict

### 2.1 Primary Functions & Multi-Agent Pipeline

The system must be built with **LangChain (`create_agent`)** using structured outputs (Pydantic schemas) at every stage and deterministic routing in Python:

```mermaid
flowchart LR
    IN["Incoming Ticket<br/>+ Customer Context"] --> T["1. Triage Agent<br/>(Classification & Priority)"]
    T --> R{"Deterministic<br/>Router"}
    R -->|devolucion| D["2a. Returns Specialist"]
    R -->|soporte_tecnico| S["2b. Tech Support Specialist"]
    R -->|consulta / queja_grave| C["2c. Inquiries & Complaints Specialist"]
    D --> QA["3. QA Agent<br/>(4-Dimension Audit)"]
    S --> QA
    C --> QA
    QA -->|Approved / Rewritten| OUT["Final Response to Customer"]
    QA -->|Rejected (Retry Available)| RETRY["Specialist Re-Investigation<br/>with QA Feedback"]
    RETRY --> QA
    QA -->|Rejected after Retries<br/>or Escalation Flagged| HUM["🚨 Escalate to Human Agent"]
```

1. **Triage & Classification Agent**:
   - **Role**: First point of contact.
   - **Function**: Consults the CRM to identify the customer's segment (`VIP`, `Premium`, `Estándar`), classifies the ticket into one of four categories (`devolucion`, `soporte_tecnico`, `consulta`, `queja_grave`), assigns priority (`baja`, `media`, `alta`, `urgente`), and extracts referenced order/product IDs.
2. **Returns Specialist Agent**:
   - **Role**: Reverse logistics handler for `devolucion` tickets.
   - **Function**: Checks the order details, verifies return eligibility against business rules, and—only if eligible—generates a return shipping label (RMA). If ineligible, explains the exact reason and suggests alternatives (e.g., warranty or technical support).
3. **Technical Support Specialist Agent**:
   - **Role**: Product troubleshooting specialist for `soporte_tecnico` tickets.
   - **Function**: Checks whether an active service outage affects the customer's product and searches the technical Knowledge Base for official step-by-step solutions. Flags the ticket for human escalation if no documented solution exists or physical repair is required.
4. **Inquiries & Complaints Specialist Agent**:
   - **Role**: General service and retention specialist for `consulta` and `queja_grave` tickets.
   - **Function**: Answers shipping and policy questions using real order/incident data. For severe complaints (`queja_grave`), de-escalates the situation with empathy, explains the verified cause of the issue (e.g., regional logistics incident), and offers the exact compensation defined by company policy for that customer's segment.
5. **Quality Assurance (QA) Agent**:
   - **Role**: Final auditor before any message reaches the customer.
   - **Function**: Evaluates the specialist's draft from `1` to `5` across four dimensions (**Accuracy**, **Policy Compliance**, **Tone**, and **Completeness**). Outputs a verdict (`aprobado`, `reescrito`, or `rechazado`) and the final customer-ready response.

### 2.2 Required Tools and Data Access

To avoid hallucinations, agents must query persistent data stores through typed tools (`@tool` with Pydantic input schemas). Data must be persisted in a relational database (**SQLite** for local development, abstracted behind a repository layer so it can be switched to **PostgreSQL** via configuration).

| Tool Name | System Simulated | Purpose & Output | Authorized Agents |
|---|---|---|---|
| `consultar_cliente` | **CRM** | Retrieves customer profile, loyalty segment (`VIP`, `Premium`, `Estándar`), registration date, spend, ticket history, and recent orders (`pedidos_recientes` with `pedido_id`, date, status, and SKUs). | Triage, Inquiries & Complaints |
| `consultar_pedido` | **ERP** | Retrieves order items (SKUs, names, prices), purchase/delivery dates, shipping status (`procesando`, `enviado`, `entregado`, `retrasado`), carrier, tracking code, and region. Enforces customer ownership when `cliente_id` is provided. | Returns, Inquiries & Complaints |
| `verificar_devolucion` | **Reverse Logistics (Rules)** | Evaluates whether an order item can be returned based on customer ownership, delivery status (including pre-shipment cancellation guidance for `procesando` and in-transit guidance for `enviado`/`retrasado`), product returnability, and days elapsed vs. customer segment window. | Returns |
| `crear_etiqueta_devolucion` | **Reverse Logistics (RMA)** | Creates and persists an RMA record with a return label URL and carrier. Enforces customer ownership and eligibility; idempotent for the same order + SKU. | Returns |
| `buscar_knowledge_base` | **Technical KB** | Searches troubleshooting manuals by symptom keywords and product category; returns step-by-step instructions. | Tech Support |
| `verificar_incidencias` | **Incident Status Board** | Lists active service outages (`caida_servicio`) or regional logistics disruptions (`logistica`) with descriptions and ETAs. | Tech Support, Inquiries & Complaints |

**Synthetic Data Requirements for Development & Testing:**
- Realistic Spanish customer and order datasets generated with `Faker` (`es_ES` locale) using a fixed seed for reproducibility, plus deterministic golden records covering every business scenario.
- Explicit company policy definitions covering return windows (`30` days Standard/Premium, `60` days VIP), non-returnable categories (custom items, software licenses), shipping delay coupons, severe complaint compensations by segment, and required communication tone per segment.

### 2.3 Restrictions, Guardrails & Non-Functional Requirements
1. **Least-Privilege Tool Access**: No agent may access tools outside its assigned domain. In particular:
   - The Triage agent must never attempt to resolve the ticket or query orders/KB directly (though it can resolve omitted order IDs from the customer's `pedidos_recientes` summary in CRM).
   - The QA agent must have **no tools**; it evaluates strictly against the verified data collected by the specialist and the official company policies.
2. **Customer Order Ownership & PII Isolation**:
   - `consultar_pedido`, `verificar_devolucion`, and `crear_etiqueta_devolucion` must verify that `pedido.cliente_id == ticket.cliente_id`. Cross-customer order lookups, third-party PII requests, or return attempts on another customer's order must be denied at the repository/tool layer (`Acceso denegado`).
3. **Multi-Intent Routing Precedence**:
   - When a ticket contains multiple intents, Triage must apply deterministic precedence:
     1. `queja_grave` takes top precedence if there is extreme anger, compensation demands, or cancellation threats.
     2. An undelivered order inquiry combined with a question about future returns/exchanges routes to `consulta`.
     3. A product defect where the customer explicitly requests a return/refund routes to `devolucion`; if they request troubleshooting/repair steps, it routes to `soporte_tecnico`.
     4. All secondary questions must be recorded in `ClasificacionTicket.resumen` and answered by the specialist.
4. **Code-Enforced Eligibility & Pre-Delivery Cancellation Rules**:
   - `crear_etiqueta_devolucion` must re-validate return eligibility and ownership in code before creating an RMA.
   - If an order is not yet delivered (`estado_envio != "entregado"`):
     - If `estado_envio == "procesando"`, no RMA is issued, and the specialist must escalate to a human (`requiere_escalado = True`) to stop warehouse shipment.
     - If `estado_envio` is `enviado` or `retrasado`, no RMA can be issued until delivery (or the customer may refuse delivery with the carrier).
5. **Graceful Tool Failure (No Unhandled Exceptions)**: When a customer ID, order ID, or KB article is not found, tools must return a structured `"not found"` JSON message rather than crashing, so the agent can report the missing information honestly.
6. **Bounded Retry Loop & Mandatory Human Escalation**:
   - If QA rejects a draft (`veredicto == "rechazado"`), the pipeline must allow at most a configurable number of specialist retry passes (default: `1` retry) with QA's feedback injected.
   - The system must mark a ticket for **Human Escalation** (`escalado_humano = True` with an explicit reason) whenever:
     1. The specialist flags that the issue cannot be solved with available tools/KB (`requiere_escalado = True`, including physical hardware damage or pre-shipment order cancellation in `procesando` status).
     2. QA still rejects the response after the maximum retry attempts.
     3. The Triage step fails unexpectedly (falling back to the Inquiries agent while flagging human review).
7. **Extensibility Requirements**:
   - **Agent Versioning**: System prompts and model hyperparameters must live in declarative versioned files (`v1`, `v2`, `v3`) decoupled from Python orchestration so teams can A/B test or roll back agent versions independently or across the full pipeline (`--version` / `--versions`), with per-version evaluation post-mortems (`FLAWS_SUMMARY.md`).
   - **Provider Agnosticism**: LLM instantiation must be encapsulated behind a factory so switching from OpenAI (`gpt-4o-mini`) to Anthropic or Google Gemini requires only configuration changes.
   - **LangSmith Dataset Sync & Observability**: The 23-scenario golden dataset (`data/eval_dataset.jsonl`) can be synchronized idempotently with LangSmith Datasets (`--sync-dataset`, dataset `techstore-support-golden-v1`).

---

## 3. Evaluation — How We Will Judge Quality

Before building and deploying the system, we establish both **online quality gates** (enforced on every ticket at runtime) and **offline evaluation metrics** (used to benchmark agent versions and model providers).

### 3.1 Online Quality Gate (The 4 QA Dimensions)
Every specialist draft is graded from `1` to `5` on four criteria before the response is finalized:

| Dimension | Definition | Passing Threshold | Action if Below Threshold |
|---|---|---|---|
| **1. Precisión (Accuracy)** | Every factual claim (order status, dates, SKUs, RMA codes, incident ETAs) comes directly from tool outputs with zero fabrication. | $\ge 4$ | If hallucinated data is detected $\rightarrow$ **`rechazado`** (triggers specialist retry or human escalation). |
| **2. Política (Policy Compliance)** | Decisions respect return deadlines by segment, product exclusions, refund timelines, and exact compensation rules. | $\ge 4$ | If a prohibited promise is made $\rightarrow$ **`rechazado`**; if policy explanation is incomplete $\rightarrow$ **`reescrito`**. |
| **3. Tono (Segment Tone)** | Tone matches the customer's CRM tier (`VIP`: formal *usted*, loyalty acknowledgment, priority treatment; `Premium`: warm & professional; `Estándar`: clear & polite). | $\ge 4$ | If tone is inappropriate for the segment (e.g., casual tone with an angry VIP) $\rightarrow$ **`reescrito`** by QA. |
| **4. Completitud (Completeness)** | All questions and requests in the customer's original message are answered with clear next steps. | $\ge 4$ | If a question was skipped but data is available $\rightarrow$ **`reescrito`**; if tool data is missing $\rightarrow$ **`rechazado`**. |

### 3.2 Offline Benchmark Quality Targets & Production Baseline (`v3`)

Offline evaluations against the 23-scenario golden dataset ([data/eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl), mapped in [data/eval_coverage.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_coverage.md)) are gated by our **Core Quality Targets** (execution instructions in [EVALUATION_GUIDE.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/EVALUATION_GUIDE.md)):
1. **Hard Gates (Safety & Policy)**: `escalation_accuracy >= 95.0%` and `mean_qa_politica >= 4.50 / 5.00` (with `tool_call_accuracy = 100.0%` for Triage CRM lookups).
2. **Primary Winner Metric**: `pass_rate >= 85.0%` (percentage of scenarios passing category, routing, tool trajectory, escalation, and QA together).
3. **Tie-Breaker**: `first_pass_qa_approval_rate >= 80.0%` (approved by QA on attempt 1 without retry).

#### Verified Production Baseline (`v3` on `gpt-4o-mini`)
Following iterative evaluation (`v1` $\rightarrow$ `v2` $\rightarrow$ `v3`, detailed in [docs/eval_history/v3_FLAWS_SUMMARY.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/docs/eval_history/v3_FLAWS_SUMMARY.md)), **`v3`** is our approved production baseline:
- **Quality**: The pipeline achieves a **95.65% end-to-end pass rate** (22/23 scenarios), with **100% routing and tool-call accuracy**, a **100% first-pass QA approval rate**, and a **5.00 / 5.00 mean QA score** across accuracy, policy, tone, and completeness.
- **Cost**: Each ticket consumes an average of **8,585 total tokens** across the 3-stage pipeline (Triage $\rightarrow$ Specialist $\rightarrow$ QA), representing roughly **\$0.002–\$0.003 per resolved ticket** on `gpt-4o-mini` with zero wasted QA retry loops.
- **Performance**: End-to-end resolution averages **10.54 seconds per ticket** across all 3 sequential agent invocations and SQLite tool queries.
- **Safety**: The system maintains a **95.45% human-escalation accuracy** and a **5.00 / 5.00 policy compliance score**, blocking 100% of cross-customer PII leaks (`EVAL-010`, `EVAL-016`), prompt-injection attacks (`EVAL-014`), out-of-scope requests (`EVAL-015`), and contradictory/hallucinated drafts (`EVAL-020`).
