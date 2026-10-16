# Pre-registro — F4: calibración de las probabilidades del modelo

Fecha: 16/10/2026. **Escrito ANTES de medir.** Este documento fija qué se
prueba, cómo se mide y qué haría adoptar o rechazar cada candidato. Una vez
ejecutado, los resultados se reportan tal cual salgan; nada se cambia "porque
habría quedado mejor".

## Pregunta

¿Existe una transformación de las probabilidades de srs-v2 — ajustada **solo
con datos anteriores** a cada temporada evaluada — que las haga más honestas
que el modelo crudo (mejor Brier y Log Loss fuera de muestra), por mercado
(spread, total, moneyline)?

## Datos y periodos

- **Universo**: era 2006+ con probabilidad del modelo, probabilidad de
  mercado sin vig y resultado decidido (push y empates fuera), la misma
  convención estricta del instrumento v3 (`lab/evaluacion.py`).
- **Ajuste**: ventana expansiva. Para evaluar la temporada S se ajusta solo
  con temporadas < S (arranca en 2006).
- **Evaluación**: temporadas 2014–2025 (12 temporadas). 2026 se muestra como
  informativo y queda fuera de las puertas.
- Sin red; solo lectura; bootstrap con semilla 20261016 (2000 remuestreos).

## Candidatos (idénticos por mercado)

- **A — modelo crudo** (referencia actual).
- **B — mercado sin vig** (referencia de techo informativo; no adoptable).
- **C1 — Platt**: `p = sigmoide(a + b·logit(p_modelo))`; a, b ajustados por
  temporada.
- **C2 — isotónica (PAVA)**: solo en temporadas cuyo ajuste disponga de
  ≥ 3000 partidos (con nuestros datos, desde 2018). Candidato solo si su
  ventana cubre ≥ 5 temporadas evaluadas.
- **D — mezcla logística**: `p = sigmoide(a + b·logit(p_modelo) + c·logit(p_mercado))`,
  ajustada por temporada.

**Regla de selección entre candidatos que pasen** (si hay varios): gana el
de mejor ΔBrier medio; si dos quedan a ≤ 0.0001, gana el de menos parámetros
(C1 antes que D; D antes que C2).

## Métricas (sobre los MISMOS partidos, por mercado)

- Brier y Log Loss en la ventana de evaluación.
- ΔBrier(candidato − A) y ΔLogLoss(candidato − A) **pareados por partido**,
  con IC95% bootstrap por percentiles; Δ < 0 ⇒ mejor que el modelo crudo.
- Consistencia por temporada: nº de temporadas evaluadas con ΔBrier < 0.
- Cobertura: proporción del universo evaluable en la que el candidato define
  probabilidad (dentro de su ventana).

## Puertas de adopción (por mercado; C1, C2 y D compiten con las mismas reglas)

- **G1**: ΔBrier ≤ −0.001 **y** extremo superior del IC95% < 0.
- **G2**: ΔLogLoss ≤ −0.001 **y** extremo superior del IC95% < 0.
- **G3**: cobertura ≥ 98 %.
- **G4** (solo D, informativa): se reporta ΔBrier(D − B) con IC; si ese IC no
  queda entero < 0, el veredicto dirá "el modelo no añade sobre el mercado"
  aunque D pase G1–G3.
- **G5**: consistencia: ΔBrier < 0 en ≥ ⌈2/3⌉ de las temporadas evaluadas
  (≥ 8 de 12; para C2, ≥ 6 de sus 8) y al menos 5 temporadas evaluadas.

Si **ningún candidato pasa** por mercado: se conserva el modelo crudo y se
documenta el resultado negativo. Si varios pasan: uno solo por mercado.

## Honestidad (compromisos)

- 2014–2025 **no es un holdout limpio**: los resultados son retrospectivos y
  contaminados en grado variable. Las puertas miden señal, no inmunidad.
- La adopción real (cablear el calibrador en la app) será un bloque aparte,
  con pruebas propias, sin reescribir el registro y con versionado explícito
  de la probabilidad («srs-v2+cal»); la confirmación limpia es prospectiva.
- **No se usa ROI en ninguna decisión de esta fase** (regla del encargo).
- Si alguna medición sale rara (cobertura inesperada, no convergencia), se
  reporta y se detiene la adopción de ese candidato.
