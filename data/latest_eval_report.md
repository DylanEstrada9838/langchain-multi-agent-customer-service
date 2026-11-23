<!-- eval-gate-report -->
## ✅ Eval Quality Gate — PASSED

**LangSmith experiment:** [private-holdout-dev-ci-0d3da73d](https://eu.smith.langchain.com/o/a8f6e0b2-95a9-47ca-98e0-92a88c918ce8/projects/p/d0d188c5-4c2d-436e-afab-8533dc17ce5a) (23 scenarios)
**Evaluated versions:** `triaje:v7`, `devoluciones:v8`, `soporte_tecnico:v4`, `consultas:v9`, `qa:v4`
**Dataset:** `techstore-support-golden-v1` (dev)

### Absolute thresholds

| Priority | Metric | Result | Target | Status |
|---|---|---:|---:|:---:|
| 1. Hard Gate (Safety & Escalation) | `escalation_accuracy` | 100.0% | ≥ 95.0% | ✅ |
| 1b. Hard Gate (Policy Score / 5) | `mean_qa_politica` | 5.00 / 5 | ≥ 4.50 / 5 | ✅ |
| 2. Primary Winner Metric | `pass_rate` | 100.0% | ≥ 85.0% | ✅ |
| 3. Tie-Breaker | `first_pass_qa_approval_rate` | 100.0% | ≥ 80.0% | ✅ |

### Baseline comparison at run time

| Metric | Result | Baseline | Δ | Tolerance | Status |
|---|---:|---:|---:|---:|:---:|
| `pass_rate` | 100.0% | 95.7% | +0.0435 | ±0.05 | ✅ |
| `escalation_accuracy` | 100.0% | 100.0% | 0 | ±0.05 | ✅ |
| `first_pass_qa_approval_rate` | 100.0% | 95.5% | +0.0455 | ±0.05 | ✅ |
| `mean_qa_politica` | 5.00 / 5 | 5.00 / 5 | 0 | ±0.25 | ✅ |

### Cost and latency (informational)

| Metric | Result | Baseline | Δ % |
|---|---:|---:|---:|
| `avg_tokens` | 6,638 | 6,956 | -4.6% |
| `avg_cost_usd` | $0.0012 | $0.0012 | -4.6% |
| `avg_latency_seconds` | 7.46 s | 8.68 s | -14.1% |
| `avg_ttft_seconds` | - | - | - |

### Manual review criteria (outside automated scoring)

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
- `EVAL-018`: 2
- `EVAL-019`: 3
- `EVAL-021`: 4
- `EVAL-023`: 2, 3
- `EVAL-022`: 3
