# Resumen de Evaluación y Resultados de `v3` (`APPROVED` — 22/23 Escenarios)

**Informe evaluado**: `outputs/eval_pipeline_20261119_035429.json` (23 escenarios)
**Veredicto oficial de Quality Gates**: ✅ **`APPROVED` (`quality_gate_passed: true`)**

---

## 1. Evolución de Métricas (`v1` $\rightarrow$ `v2` $\rightarrow$ `v3`)

| Prioridad / Métrica | Target Oficial | `v1` | `v2` | **`v3` (`APPROVED`)** | Mejora `v2` $\rightarrow$ `v3` |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Veredicto Global (`quality_gate_passed`)** | **ALL PASS** | ❌ `FAIL` | ❌ `FAIL` | ✅ **`PASS`** | **Supera los 4 umbrales** |
| **1. Hard Gate: `escalation_accuracy`** | **$\ge 95.0\%$** | `100.00%` ✅ | `86.36%` ❌ | **`95.45%` (21/22) ✅** | **+9.09 pts** |
| **1b. Hard Gate: `mean_qa_politica`** | **$\ge 4.50 / 5$** | `4.68 / 5` ✅ | `4.73 / 5` ✅ | **`5.00 / 5.00` ✅** | **+0.27 pts (Pleno)** |
| **2. Primary Winner: `pass_rate`** | **$\ge 85.0\%$** | `65.22%` (15/23) ❌ | `87.96%` (20/23) ✅ | **`95.65%` (22/23) ✅** | **+8.69 pts (+2 escenarios)** |
| **3. Tie-Breaker: `first_pass_qa_approval_rate`** | **$\ge 80.0\%$** | `95.45%` ✅ | `86.36%` ✅ | **`100.00%` (22/22) ✅** | **+13.64 pts (Pleno)** |
| *Diagnóstico: `category_accuracy`* | - | `95.45%` | `100.00%` | **`100.00%` (22/22)** | Mantiene 100% |
| *Diagnóstico: `tool_trajectory_recall`* | - | `90.15%` | `100.00%` | **`100.00%` (23/23)** | Mantiene 100% |
| *Diagnóstico: `mean_qa_score`* | - | `4.45 / 5.00` | `4.81 / 5.00` | **`5.00 / 5.00`** | **+0.19 pts (Pleno)** |
| *Diagnóstico: `avg_latency_seconds`* | - | `11.88 s` | `11.77 s` | **`10.54 s`** | **-1.23 s más rápido** |
| *Diagnóstico: `avg_tokens`* | - | `6551.6` | `9037.4` | **`8584.7`** | **-452.7 tokens/ticket** |

---

## 2. Fallos de `v2` Resueltos en `v3`

1. **Fin del sobre-rechazo de QA en devoluciones denegadas por política (`EVAL-012`)**:
   - En `v3`, `devoluciones` registró explícitamente `elegible=false` en `datos_verificados` al superar los 30 días del plazo Estándar (46 días transcurridos en `P9002`), y `qa` (`v3`) aprobó la denegación a la primera (`5/5` en las 4 dimensiones, `intentos_qa: 1`, `escalado_humano: false`).
2. **Fin del sobre-rechazo de QA cuando un pedido no existe en el ERP (`EVAL-017`)**:
   - En `v3`, cuando `consultar_pedido` devolvió error de pedido no encontrado para `P9999`, `consultas` (`v3`) informó con precisión a la clienta Marta Soler de que `P9999` no existe (mencionando además sus pedidos reales `P9008` y `P9003`), y `qa` (`v3`) lo aprobó en el primer intento (`5/5`, `intentos_qa: 1`, `escalado_humano: false`).
3. **Reducción de latencia y consumo de tokens**:
   - Al eliminar los falsos rechazos de QA (`first_pass_qa_approval_rate = 100%` en los 22 escenarios end-to-end, mientras sigue rechazando el borrador contradictorio de `EVAL-020`), se evitaron reintentos innecesarios, reduciendo el tiempo medio por escenario a `10.54s`.

---

## 3. Único Escenario Pendiente en `v3` (`EVAL-018`)

De los 23 escenarios, `v3` superó **22/23 (`95.65%`)**. El único escenario que no marcó `escalado_humano: true` fue **`EVAL-018`** (cafetera espresso inteligente con `error E-404`):
- **Causa técnica identificada**:
  - `soporte_tecnico` invocó `buscar_knowledge_base(consulta="error E-404 en la pantalla táctil y no calienta el agua", categoria="domotica")`.
  - Debido a que pasó `categoria="domotica"`, `SupportRepository.search_kb()` filtró artículos de la categoría `domotica` (`KB-003` de cámaras WiFi / `KB-004` de termostatos) o coincidió por palabras comunes ("no", "la", "el"), devolviendo una lista de resultados **no vacía** en lugar de `"resultados": []`.
  - Al recibir artículos de `domotica` y ver la incidencia global `INC-001` ("Cloud de cámaras y app domótica"), el agente interpretó que había guía en la KB para dispositivos domóticos y dejó `requiere_escalado: false`.
- **Oportunidad de mejora futura (`v4` / capa de búsqueda KB)**:
  - En `soporte_tecnico`: instruir que si los artículos devueltos por `buscar_knowledge_base` pertenecen a un producto distinto al consultado por el cliente (p. ej., devuelve artículos de cámaras o termostatos cuando el cliente pregunta por una cafetera espresso o un código de error específico `E-404` no mencionado en el artículo), debe tratarlo igual que un resultado vacío y activar `requiere_escalado=True`.
