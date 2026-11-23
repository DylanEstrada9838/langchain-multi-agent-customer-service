# Evaluation Results and Remaining Flaw in `v3`

**Evaluated report** — `outputs/eval_pipeline_20261119_035429.json` (23 scenarios).
**Quality gate** — Approved (`quality_gate_passed: true`).

## 1. Metric changes

| Metric | Target | `v1` | `v2` | `v3` | Change from `v2` |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality gate | All thresholds | Failed | Failed | Passed | All four thresholds passed |
| Escalation accuracy | ≥ 95.0% | 100.00% | 86.36% | 95.45% (21/22) | +9.09 points |
| Mean QA policy score | ≥ 4.50 / 5 | 4.68 / 5 | 4.73 / 5 | 5.00 / 5 | +0.27 |
| Pass rate | ≥ 85.0% | 65.22% (15/23) | 86.96% (20/23) | 95.65% (22/23) | +8.69 points |
| First-pass QA approval | ≥ 80.0% | 95.45% | 86.36% | 100.00% (22/22) | +13.64 points |
| Category accuracy | — | 95.45% | 100.00% | 100.00% (22/22) | Stable |
| Tool trajectory recall | — | 90.15% | 100.00% | 100.00% (23/23) | Stable |
| Mean QA score | — | 4.45 / 5 | 4.81 / 5 | 5.00 / 5 | +0.19 |
| Average latency | — | 11.88 s | 11.77 s | 10.54 s | −1.23 s |
| Average tokens | — | 6,551.6 | 9,037.4 | 8,584.7 | −452.7 per ticket |

## 2. Fixes from `v2`

- **Expired return (`EVAL-012`).** Returns recorded `elegible=false` for `P9002` because 46 days had elapsed and the standard window was 30 days. QA accepted the denial on the first attempt with 5/5 in all four dimensions and no human escalation.
- **Missing order (`EVAL-017`).** Inquiries correctly explained that `P9999` was missing and also mentioned the customer's orders `P9008` and `P9003`. QA approved the first draft with 5/5 and no human escalation.
- **Fewer retries.** QA approved all 22 end-to-end scenarios on the first attempt and still rejected the contradictory draft in the QA-only scenario `EVAL-020`. Average latency fell to 10.54 seconds.

## 3. Remaining failure in `v3` (`EVAL-018`)

Technical Support missed a required escalation for a smart espresso machine displaying `E-404`. The agent searched `buscar_knowledge_base` with `categoria="domotica"`. `SupportRepository.search_kb()` returned unrelated camera and thermostat articles (`KB-003` and `KB-004`) through category filtering or matches on common words. Those results and the general smart-home incident `INC-001` led the agent to leave `requiere_escalado: false`.

**Proposed change for `v4`** — Treat articles about a different product or articles that lack the reported error code as an empty result, and set `requiere_escalado=True` when relevant guidance is unavailable.
