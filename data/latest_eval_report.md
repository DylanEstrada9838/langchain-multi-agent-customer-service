<!-- eval-gate-report -->
## ✅ Eval Quality Gate — PASSED

**Experimento LangSmith:** [pipeline-v3-5c56e0e6](https://eu.smith.langchain.com/o/a8f6e0b2-95a9-47ca-98e0-92a88c918ce8/projects/p/b97bf224-299f-4d83-92e5-1a0baa098a69) (23 escenarios)
**Versiones evaluadas:** `triaje:v3`, `devoluciones:v3`, `soporte_tecnico:v3`, `consultas:v3`, `qa:v3`

### Umbrales absolutos

| Prioridad | Métrica | Resultado | Target | Estado |
|---|---|---:|---:|:---:|
| 1. Hard Gate (Safety & Escalation) | `escalation_accuracy` | 95.5% | ≥ 95.0% | ✅ |
| 1b. Hard Gate (Policy Score / 5) | `mean_qa_politica` | 5.00 / 5 | ≥ 4.50 / 5 | ✅ |
| 2. Primary Winner Metric | `pass_rate` | 95.7% | ≥ 85.0% | ✅ |
| 3. Tie-Breaker | `first_pass_qa_approval_rate` | 100.0% | ≥ 80.0% | ✅ |

### Regresión vs baseline

| Métrica | Resultado | Baseline | Δ | Tolerancia | Estado |
|---|---:|---:|---:|---:|:---:|
| `pass_rate` | 95.7% | 95.7% | 0 | ±0.05 | ✅ |
| `escalation_accuracy` | 95.5% | 95.5% | 0 | ±0.05 | ✅ |
| `first_pass_qa_approval_rate` | 100.0% | 100.0% | 0 | ±0.05 | ✅ |
| `mean_qa_politica` | 5.00 / 5 | 5.00 / 5 | 0 | ±0.25 | ✅ |

### Coste y latencia (informativo, no bloquea)

| Métrica | Resultado | Baseline | Δ % |
|---|---:|---:|---:|
| `avg_tokens` | 8,565 | 8,565 | 0.0% |
| `avg_cost_usd` | $0.0019 | $0.0019 | 0.0% |
| `avg_latency_seconds` | 10.20 s | 10.20 s | 0.0% |
| `avg_ttft_seconds` | 10.20 s | 10.20 s | 0.0% |

### Escenarios con fallos

- `EVAL-018`: escalado_match
