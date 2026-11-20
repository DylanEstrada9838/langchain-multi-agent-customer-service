# Evaluation Dataset Coverage Matrix

This document maps every requirement, agent capability, tool contract, and guardrail from [SPECIFICATIONS.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/SPECIFICATIONS.md) to the corresponding test scenarios in [eval_dataset.jsonl](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/data/eval_dataset.jsonl) (`EVAL-001` through `EVAL-023`).

---

## 1. Category Breakdown

| Dataset Category | Count | Scenario IDs |
|---|---|---|
| `happy_path` | 6 | `EVAL-001`, `EVAL-002`, `EVAL-003`, `EVAL-004`, `EVAL-005`, `EVAL-006` |
| `edge_case` | 8 | `EVAL-007`, `EVAL-008`, `EVAL-009`, `EVAL-010`, `EVAL-011`, `EVAL-021`, `EVAL-022`, `EVAL-023` |
| `boundary_testing` | 5 | `EVAL-012`, `EVAL-013`, `EVAL-014`, `EVAL-015`, `EVAL-016` |
| `tool_invocation` | 4 | `EVAL-017`, `EVAL-018`, `EVAL-019`, `EVAL-020` |
| **Total** | **23** | `EVAL-001`..`EVAL-023` |

---

## 2. PRD Requirements & Capabilities Coverage Matrix

| PRD Item / Requirement ([SPECIFICATIONS.md](file:///c:/Users/dylan/Documents/Python/langchain-multiagent/SPECIFICATIONS.md)) | Category | Covered by Scenario ID(s) |
|---|---|---|
| **Agent 1 (`triaje`)**: CRM segment lookup & intent classification (`devolucion`, `soporte_tecnico`, `consulta`, `queja_grave`) | Agents & Routing | `EVAL-001`..`EVAL-019`, `EVAL-021`..`EVAL-023` (all 22 end-to-end scenarios) |
| **Agent 1 (`triaje`)**: Priority assignment (`urgente` for VIP `queja_grave`, `alta`, `media`, `baja`) | Agents & Routing | `EVAL-005`/`015` (`baja`), `EVAL-001`/`004`/`021`/`022` (`media`), `EVAL-003`/`008`/`018` (`alta`), `EVAL-006` (`urgente`) |
| **Agent 1 (`triaje`)**: Entity extraction (`pedido_id`, `sku`) without fabricating missing IDs | Agents & Routing | `EVAL-001`, `EVAL-005` (`pedido_id=null`), `EVAL-007` (resolved from `pedidos_recientes`), `EVAL-019`, `EVAL-023` (both `null` when `pedidos_recientes=[]`) |
| **Agent 1 (`triaje`)**: Multi-intent routing precedence rules (#1 `queja_grave` > #2 undelivered + future return `consulta` > #3 defect + explicit refund `devolucion` vs. repair `soporte_tecnico`) | Agents & Routing | `EVAL-006` (Rule #1), `EVAL-009` (Rule #2), `EVAL-022` (Rule #3: defect $\rightarrow$ `devolucion`), `EVAL-002` (Rule #3: defect $\rightarrow$ `soporte_tecnico`) |
| **Agent 2a (`devoluciones`)**: Eligible return flow $\rightarrow$ RMA creation & SQLite persistence | Agents & Tools | `EVAL-001` (explicit `P9001`), `EVAL-007` (resolved via CRM `pedidos_recientes`), `EVAL-022` (defective item within 30d window) |
| **Agent 2b (`soporte_tecnico`)**: KB troubleshooting + active service outage check | Agents & Tools | `EVAL-002` (KB match), `EVAL-003` (active outage `INC-001` + KB), `EVAL-008` (hardware/water damage escalation), `EVAL-018` (empty KB escalation) |
| **Agent 2c (`consultas`)**: Shipping inquiries, policy questions & severe complaint de-escalation | Agents & Tools | `EVAL-004` (delayed order + `INC-002`), `EVAL-005` (return policy), `EVAL-006` (VIP severe complaint compensation), `EVAL-009` (secondary policy question) |
| **Agent 3 (`qa`)**: 4-dimension rubric (`precision`, `politica`, `tono`, `completitud`), `expected_tool_calls: "none"`, rejection retry loop | QA & Guardrails | `EVAL-001`, `EVAL-006`, `EVAL-009`, `EVAL-020` (explicit QA `rechazado` + retry trigger + `"none"` tool calls) |
| **Tool `consultar_cliente`**: Profile, segment, `pedidos_recientes` list, and Not-Found (`error`) handling | Tool Invocation | `EVAL-001`..`006` (found), `EVAL-007` (`pedidos_recientes` resolution), `EVAL-010` (`C999` not found), `EVAL-023` (`C906` with empty `pedidos_recientes`) |
| **Tool `consultar_pedido`**: Order details, Not-Found (`error`) handling, and `cliente_id` ownership verification | Tool Invocation & Security | `EVAL-001`, `EVAL-004` (owner match), `EVAL-010`/`016` (cross-customer ownership denied), `EVAL-017` (`P9999` not found) |
| **Tool `verificar_devolucion`**: Window check (`30d` vs `60d` VIP), `devolvible=False`, `estado_envio != entregado` (`procesando` vs `retrasado`), SKU mismatch, and ownership check | Tool Invocation & Boundaries | `EVAL-001` (VIP 60d ok), `EVAL-011` (`retrasado` in-transit rule), `EVAL-012` (45d > 30d), `EVAL-013` (`devolvible=False`), `EVAL-019` (SKU mismatch), `EVAL-021` (`procesando` cancellation rule) |
| **Tool `crear_etiqueta_devolucion`**: Hard eligibility + ownership code gate & idempotence | Tool Invocation & Boundaries | `EVAL-001`, `EVAL-007`, `EVAL-022` (allowed), `EVAL-011`..`014`, `EVAL-016`, `EVAL-019`, `EVAL-021` (blocked) |
| **Tool `buscar_knowledge_base`**: Keyword/category match vs. empty results (`Sin artículos relevantes`) | Tool Invocation | `EVAL-002`, `EVAL-003` (match), `EVAL-008`, `EVAL-018` (empty results) |
| **Tool `verificar_incidencias`**: `caida_servicio` (Global) vs. `logistica` (Regional: Cataluña) | Tool Invocation | `EVAL-002` (none for audio), `EVAL-003` (`INC-001` global cloud), `EVAL-004`/`006`/`009` (`INC-002` Cataluña logistics) |
| **Boundary: Customer Order Ownership & PII Isolation** | Boundary & Security | `EVAL-010` (`C999` querying `C904`'s order `P9005`), `EVAL-016` (`C901` requesting PII/RMA on `C900`'s order `P9001`) |
| **Boundary: Pre-Delivery Cancellation (`procesando`) vs. In-Transit Return (`enviado`/`retrasado`)** | Policy & Escalation | `EVAL-011` (`P9004` in `retrasado` $\rightarrow$ wait for delivery or refuse package), `EVAL-021` (`P9008` in `procesando` $\rightarrow$ `escalado_humano=True` to stop warehouse shipment) |
| **Boundary: Out-of-scope & adversarial prompt injection** | Boundary Testing | `EVAL-014` (admin override / 500 EUR coupon & VIP spoofing), `EVAL-015` (Python scraping & weather) |
| **Escalation (`escalado_humano=True`)**: Hardware/physical damage, missing KB article, pre-shipment cancellation (`procesando`), or persistent QA rejection | Escalation | `EVAL-008` (water/burning damage), `EVAL-018` (unlisted product/error `E-404`), `EVAL-020` (QA rejection), `EVAL-021` (pre-shipment order cancellation) |


## Executable assertions and manual review

Local and LangSmith runs apply the same deterministic scenario assertions. A passing
automated check establishes the fields and reply patterns listed below. Review the
numbered criteria still marked as manual when certifying a scenario. The numbers refer
to the original 1-based order of `pass_fail_criteria` in the scenario.

| Scenario | Additional automated coverage | Criteria requiring full or partial manual review |
|---|---|---|
| EVAL-001 | VIP tier, ordered return workflow, RMA ID and URL from tool result, score floors and verdict | 4 (formal tone) |
| EVAL-002 | KB article, troubleshooting text markers, specialist escalation flag | 3 |
| EVAL-003 | KB and incident IDs, ETA and troubleshooting text markers | 2, 3, 4 |
| EVAL-004 | Verified order status, exact carrier and tracking, incident ID, ETA and amount markers | 3, 4 |
| EVAL-005 | No order ID or order lookup, policy text markers | 3, 4 |
| EVAL-006 | Urgency, incident ID, ETA and compensation markers | 3, 4 |
| EVAL-007 | Extracted order and SKU, ordered return workflow, exact RMA ID and URL | 3 (formal tone) |
| EVAL-008 | Specialist escalation flag | 3, 4 |
| EVAL-009 | Delayed order result, return-window markers, no RMA call, completeness score | 2 |
| EVAL-010 | Denial in order tool result | 3 |
| EVAL-011 | Ineligible and in transit, no RMA call | 2, 3 |
| EVAL-012 | Ineligible and elapsed days versus policy window, no RMA call or RMA ID/URL in reply | 1, 4 |
| EVAL-013 | Ineligible due to customization, no RMA call, customization marker | 1, 2 |
| EVAL-014 | Standard tier, denied as out of window, no RMA call, forbidden coupon and RMA text | 3 (reply wording) |
| EVAL-015 | No order or returns calls | 1, 2 |
| EVAL-016 | Denial in order tool result | 2, 3 |
| EVAL-017 | Missing order result, order ID in reply, forbidden tracking pattern | 2, 3 |
| EVAL-018 | Empty KB result and specialist escalation flag | 2 |
| EVAL-019 | SKU mismatch in eligibility result, no RMA call, expected product and SKU in reply | 3 |
| EVAL-020 | QA-only rejection, maximum precision and policy scores of 2, no tool calls | None |
| EVAL-021 | Ineligible before dispatch, cancellation guidance in tool result, no RMA call, specialist escalation flag | 4 |
| EVAL-022 | Ordered return workflow, exact RMA ID and URL, refund timeframe marker | 3 (business-day wording) |
| EVAL-023 | Null order ID and SKU, no order or returns calls | 2, 3 |

The matcher consumes each expected call once and checks its agent, tool, and declared
arguments. Free-form search queries and return reasons allow agent-generated wording.
Ordering is enabled for scenarios with an explicitly sequenced return workflow.
The no-RMA assertion checks that the RMA creation tool was never invoked. That tool
is the pipeline's RMA write path. Successful RMA assertions use the persisted ID and
URL returned by that tool.

Retry and final rejection handling for QA are covered by the pipeline unit tests.
Sync the dataset with `--sync-dataset` before running the updated LangSmith evaluation.
Historical reports remain tied to the checks that generated them.
