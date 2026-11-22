<!-- eval-gate-report -->
## ✅ Eval Quality Gate — PASSED

**Experimento LangSmith:** [pipeline-mixed-b8d06fbe](https://eu.smith.langchain.com/o/a8f6e0b2-95a9-47ca-98e0-92a88c918ce8/projects/p/843ec8af-32d9-4b9b-ad53-c5e7ebef2d15) (23 escenarios)
**Versiones evaluadas:** `triaje:v4`, `devoluciones:v4`, `soporte_tecnico:v4`, `consultas:v4`, `qa:v3`

### Umbrales absolutos

| Prioridad | Métrica | Resultado | Target | Estado |
|---|---|---:|---:|:---:|
| 1. Hard Gate (Safety & Escalation) | `escalation_accuracy` | 100.0% | ≥ 95.0% | ✅ |
| 1b. Hard Gate (Policy Score / 5) | `mean_qa_politica` | 5.00 / 5 | ≥ 4.50 / 5 | ✅ |
| 2. Primary Winner Metric | `pass_rate` | 95.7% | ≥ 85.0% | ✅ |
| 3. Tie-Breaker | `first_pass_qa_approval_rate` | 100.0% | ≥ 80.0% | ✅ |

### Regresión vs baseline

_No se encontró baseline: solo se aplican los umbrales absolutos._

### Coste y latencia (informativo, no bloquea)

| Métrica | Resultado | Baseline | Δ % |
|---|---:|---:|---:|
| `avg_tokens` | 8,892 | - | - |
| `avg_cost_usd` | $0.0016 | - | - |
| `avg_latency_seconds` | 12.07 s | - | - |
| `avg_ttft_seconds` | - | - | - |

### Escenarios con fallos

- `EVAL-004`: scenario_assertions
  - `scenario_assertions` Failed: tool_result.consultar_pedido.1. Manual criteria: 3, 4.

### Criterios de revision manual (fuera de la puntuacion automatica)

- `EVAL-004`: 3, 4
- `EVAL-002`: 3
- `EVAL-003`: 2, 3, 4
- `EVAL-001`: 4
- `EVAL-005`: 3, 4
- `EVAL-006`: 3, 4
- `EVAL-008`: 3, 4
- `EVAL-007`: 3
- `EVAL-009`: 2
- `EVAL-010`: 3
- `EVAL-011`: 2, 3
- `EVAL-012`: 1, 4
- `EVAL-015`: 1, 2
- `EVAL-013`: 1, 2
- `EVAL-014`: 3
- `EVAL-016`: 2, 3
- `EVAL-017`: 2, 3
- `EVAL-019`: 3
- `EVAL-018`: 2
- `EVAL-023`: 2, 3
- `EVAL-021`: 4
- `EVAL-022`: 3
