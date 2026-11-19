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
| `consultar_cliente` | **CRM** | Retrieves customer profile, loyalty segment (`VIP`, `Premium`, `Estándar`), registration date, spend, and ticket history. | Triage, Inquiries & Complaints |
| `consultar_pedido` | **ERP** | Retrieves order items (SKUs, names, prices), purchase/delivery dates, shipping status (`procesando`, `enviado`, `entregado`, `retrasado`), carrier, tracking code, and region. | Returns, Inquiries & Complaints |
| `verificar_devolucion` | **Reverse Logistics (Rules)** | Evaluates whether an order item can be returned based on delivery status, product returnability, and days elapsed vs. customer segment window. | Returns |
| `crear_etiqueta_devolucion` | **Reverse Logistics (RMA)** | Creates and persists an RMA record with a return label URL and carrier. Must be idempotent for the same order + SKU. | Returns |
| `buscar_knowledge_base` | **Technical KB** | Searches troubleshooting manuals by symptom keywords and product category; returns step-by-step instructions. | Tech Support |
| `verificar_incidencias` | **Incident Status Board** | Lists active service outages (`caida_servicio`) or regional logistics disruptions (`logistica`) with descriptions and ETAs. | Tech Support, Inquiries & Complaints |

**Synthetic Data Requirements for Development & Testing:**
- Realistic Spanish customer and order datasets generated with `Faker` (`es_ES` locale) using a fixed seed for reproducibility, plus deterministic golden records covering every business scenario.
- Explicit company policy definitions covering return windows (`30` days Standard/Premium, `60` days VIP), non-returnable categories (custom items, software licenses), shipping delay coupons, severe complaint compensations by segment, and required communication tone per segment.

### 2.3 Restrictions, Guardrails & Non-Functional Requirements
1. **Least-Privilege Tool Access**: No agent may access tools outside its assigned domain. In particular:
   - The Triage agent must never attempt to resolve the ticket or query orders/KB.
   - The QA agent must have **no tools**; it evaluates strictly against the verified data collected by the specialist and the official company policies.
2. **Code-Enforced Eligibility on Write Actions**: `crear_etiqueta_devolucion` must re-validate return eligibility in code before creating an RMA. Even if an agent calls the tool for an expired or non-returnable item, the tool must refuse the write and return an explicit error.
3. **Graceful Tool Failure (No Unhandled Exceptions)**: When a customer ID, order ID, or KB article is not found, tools must return a structured `"not found"` JSON message rather than crashing, so the agent can report the missing information honestly.
4. **Bounded Retry Loop & Mandatory Human Escalation**:
   - If QA rejects a draft (`veredicto == "rechazado"`), the pipeline must allow at most a configurable number of specialist retry passes (default: `1` retry) with QA's feedback injected.
   - The system must mark a ticket for **Human Escalation** (`escalado_humano = True` with an explicit reason) whenever:
     1. The specialist flags that the issue cannot be solved with available tools/KB (`requiere_escalado = True`).
     2. QA still rejects the response after the maximum retry attempts.
     3. The Triage step fails unexpectedly (falling back to the Inquiries agent while flagging human review).
5. **Extensibility Requirements**:
   - **Agent Versioning**: System prompts and model hyperparameters must live in declarative versioned files (e.g., `v1`, `v2`) decoupled from Python orchestration so teams can A/B test or roll back agent versions.
   - **Provider Agnosticism**: LLM instantiation must be encapsulated behind a factory so switching from OpenAI (`gpt-4o-mini`) to Anthropic or Google Gemini requires only configuration changes.

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

### 3.2 Quantitative Evaluation Metrics (for Benchmarking & CI/CD Evals)

When running our evaluation suite against test tickets, we will measure the system using the following metrics:

#### A. Triage & Routing Metrics
1. **Intent Classification Accuracy**:
   $$\text{Accuracy}_{\text{intent}} = \frac{\text{Tickets classified into the correct category}}{\text{Total evaluated tickets}}$$
   *Acceptance Target:* $\ge 95\%$ on the golden test suite.
2. **CRM Segment Lookup Compliance & Priority Accuracy**:
   - **Segment Accuracy**: Percentage of tickets where the triage output matches the customer's true CRM segment (*Target:* $100\%$, proving `consultar_cliente` was invoked).
   - **Urgency Recall**: Percentage of VIP severe complaints assigned `prioridad = "urgente"` (*Target:* $100\%$).
3. **Entity Extraction Precision & Recall**:
   - Accuracy of extracted `pedido_id` and `sku` fields compared to ground truth, with **zero fabricated IDs** when none are present in the ticket.

#### B. Specialist Tool-Use & Groundedness Metrics
4. **Expected Tool Trajectory Recall**:
   - Percentage of tickets where the specialist invoked the complete required sequence of tools for that scenario (e.g., `consultar_pedido` $\rightarrow$ `verificar_devolucion` $\rightarrow$ `crear_etiqueta_devolucion` for eligible returns).
5. **Unauthorized Action Rate (Safety Metric)**:
   - Percentage of ineligible return tickets where an RMA label is generated or promised in the text (*Acceptance Target:* **$0\%$**).
6. **Hallucination / Ungrounded Claim Rate**:
   - Percentage of final responses containing any ID, tracking code, URL, timeframe, or EUR compensation amount not present in the tool outputs or company policy table (*Acceptance Target:* **$0\%$**).

#### C. QA, Self-Correction & Escalation Metrics
7. **First-Pass QA Approval Rate (FPAR)**:
   $$\text{FPAR} = \frac{\text{Tickets approved on the first QA pass (no rewrite or retry needed)}}{\text{Total tickets}}$$
   *Use case:* Primary metric to compare whether prompt version `v2` of a specialist improves over `v1`.
8. **Mean QA Rubric Score per Dimension**:
   - Average score (`1–5`) across `precision`, `politica`, `tono`, and `completitud` (*Acceptance Target:* $\ge 4.5$ average per dimension).
9. **Self-Correction Recovery Rate**:
   $$\text{Recovery Rate} = \frac{\text{Tickets rejected on QA Pass 1 that pass on QA Pass 2}}{\text{Tickets rejected on QA Pass 1}}$$
   *Use case:* Measures how effectively the specialist uses QA feedback during the retry loop.
10. **Escalation Precision & Recall**:
    - **Escalation Recall**: Percentage of unresolvable or persistently failing tickets correctly flagged with `escalado_humano = True` (*Target:* $100\%$).
    - **False Escalation Rate**: Percentage of standard resolvable tickets unnecessarily escalated to humans (*Target:* $< 5\%$).

#### D. Operational Metrics
11. **End-to-End Latency (`p50` / `p95` seconds per ticket)** and **Token Cost per Resolved Ticket**:
    - Tracked across single-pass and retry-pass executions to ensure fast customer response times (`p50 < 12s`, `p95 < 25s`).

---

### 3.3 Core Acceptance Scenarios (Golden Test Suite)

To consider the system ready, it must pass a deterministic benchmark covering at least these 8 canonical scenarios:

| Scenario | Customer Tier | Input Summary | Expected Routing & Tool Behavior | Expected Final Outcome |
|---|---|---|---|---|
| **1. Eligible VIP Return** | `VIP` | Wants to return a delivered smartwatch purchased 14 days ago. | Route to **Returns** $\rightarrow$ check order $\rightarrow$ verify eligibility (within 60d VIP window) $\rightarrow$ generate RMA label. | Approved response with persisted RMA code and label URL in formal VIP tone. |
| **2. Expired Window Return** | `Estándar` | Wants to return a keyboard delivered 45 days ago. | Route to **Returns** $\rightarrow$ check order $\rightarrow$ verify eligibility (exceeds 30d Standard window) $\rightarrow$ **do not** create label. | Polite refusal explaining the 30-day policy and days elapsed; zero RMA created. |
| **3. Non-Returnable Item** | `Estándar` | Wants to return a custom phone case delivered 6 days ago. | Route to **Returns** $\rightarrow$ check order $\rightarrow$ verify eligibility (`devolvible=False`) $\rightarrow$ **do not** create label. | Explains that custom products are excluded from returns per company policy. |
| **4. Standard Tech Support (KB Match)** | `Estándar` | Bluetooth headphones won't pair with phone. | Route to **Tech Support** $\rightarrow$ check active incidents (none for audio) $\rightarrow$ search KB for Bluetooth pairing. | Clear numbered troubleshooting steps from the official KB manual. |
| **5. Tech Support During Active Outage** | `Premium` | WiFi security camera won't sync with the cloud app. | Route to **Tech Support** $\rightarrow$ check active incidents (finds active cloud outage + ETA) $\rightarrow$ search KB. | Informs customer of the active cloud outage and its ETA alongside KB recommendations. |
| **6. Delayed Order Inquiry** | `Premium` | Asks where a delayed order is and when it will arrive. | Route to **Inquiries** $\rightarrow$ check order $\rightarrow$ check customer $\rightarrow$ check regional logistics incidents. | Provides tracking details, explains regional carrier delay/ETA, and offers the policy delay coupon. |
| **7. General Policy Inquiry** | `Estándar` | Asks how many days they have to return an item and refund timing. | Route to **Inquiries** $\rightarrow$ check customer segment $\rightarrow$ answer from official return policy. | Accurately states the 30-day return window and 5–7 business day refund timeframe. |
| **8. Severe VIP Complaint** | `VIP` | Furious about a delayed laptop; threatens to cancel account. | Triage marks `queja_grave` + `urgente` $\rightarrow$ route to **Inquiries** $\rightarrow$ check order, customer, and regional incidents. | Formal VIP apology (*usted*), explains root cause, and offers full VIP compensation package. |
