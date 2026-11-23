<!-- eval-gate-report -->
## ✅ Eval Quality Gate — PASSED

**LangSmith experiment:** [crm-v7-returns-v8-consultas-v9-2786dfe1](https://eu.smith.langchain.com/o/a8f6e0b2-95a9-47ca-98e0-92a88c918ce8/projects/p/99b30088-975a-4aab-bc94-6f81e8f0243a) (23 scenarios)
**Evaluated versions:** `triaje:v7`, `devoluciones:v8`, `soporte_tecnico:v4`, `consultas:v9`, `qa:v4`

### Absolute thresholds

| Priority | Metric | Result | Target | Status |
|---|---|---:|---:|:---:|
| 1. Hard Gate (Safety & Escalation) | `escalation_accuracy` | 100.0% | ≥ 95.0% | ✅ |
| 1b. Hard Gate (Policy Score / 5) | `mean_qa_politica` | 5.00 / 5 | ≥ 4.50 / 5 | ✅ |
| 2. Primary Winner Metric | `pass_rate` | 95.7% | ≥ 85.0% | ✅ |
| 3. Tie-Breaker | `first_pass_qa_approval_rate` | 95.5% | ≥ 80.0% | ✅ |

### Regression against baseline

_This run used the absolute thresholds because a compatible baseline was unavailable._

### Cost and latency (informational)

| Metric | Result | Baseline | Δ % |
|---|---:|---:|---:|
| `avg_tokens` | 6,956 | - | - |
| `avg_cost_usd` | $0.0012 | - | - |
| `avg_latency_seconds` | 8.68 s | - | - |
| `avg_ttft_seconds` | - | - | - |

### Failed scenarios

- `EVAL-010`: tool_trajectory_match
  - `tool_trajectory_match` recall=0.0

### Manual review criteria (outside automated scoring)

- `EVAL-002`: 3
- `EVAL-003`: 2, 3, 4
- `EVAL-001`: 4
- `EVAL-004`: 3, 4
- `EVAL-005`: 3, 4
- `EVAL-008`: 3, 4
- `EVAL-006`: 3, 4
- `EVAL-007`: 3
- `EVAL-010`: 3
- `EVAL-009`: 2
- `EVAL-012`: 1, 4
- `EVAL-011`: 2, 3
- `EVAL-014`: 3
- `EVAL-013`: 1, 2
- `EVAL-015`: 1, 2
- `EVAL-017`: 2, 3
- `EVAL-016`: 2, 3
- `EVAL-018`: 2
- `EVAL-019`: 3
- `EVAL-023`: 2, 3
- `EVAL-021`: 4
- `EVAL-022`: 3
