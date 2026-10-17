# ESTADO ACTUAL — Dashboard de Fútbol Americano

Bitácora de la etapa de mejora estadística (encargo de 7 fases, 16/10/2026).
Se actualiza al cerrar cada fase. Las decisiones fijadas aquí solo cambian
con evidencia nueva y quedando documentado el cambio.

Última actualización: 16/10/2026 (F2 completada: guardarraíles e integridad
— validación estructural del registro, escritura atómica, sello completo,
`p_push` congelada y clave de API fuera de pantalla; F5 cerrada antes).

## Reglas de trabajo vigentes

- No reescribir la app; conservar lo que funciona; cambios pequeños,
  reversibles y verificables.
- No alterar el historial de picks (solo-añadir; el registro fiel manda).
- No exponer secretos ni tocar archivos de claves; no gastar créditos de
  APIs de pago; ninguna prueba automatizada llama a la red.
- No declarar nada "rentable" sin evidencia fuera de muestra; distinguir
  siempre **medido** de **hipótesis**.
- 2018–2025 ya se usó como holdout (Bloque 3): no vuelve a presentarse como
  evaluación limpia. La selección de parámetros no se hace maximizando ROI
  histórico.

## Estado de las fases

| Fase | Qué es | Estado | Evidencia |
|---|---|---|---|
| F0 | Diagnóstico de auditoría (problemas verificados) | Completada (16/10/2026) | Hallazgos H1–H12 (abajo) |
| F1 | Instrumento de evaluación v3: mismos partidos, push estricto, segmentos, IC95% | Completada (16/10/2026) | `lab/evaluacion.py` + `lab/salida_instrumento_v3.txt` — 77/77 comprobaciones OK, 0,6 s, determinista |
| F2 | Guardarraíles e integridad (validación estructural del registro, escritura atómica, sello completo, `p_push` congelada, seguridad de la clave, suite sin red) | Completada (16/10/2026) | `lab/diagnostico_f2.md` + `lab/verificacion_integridad.py` + `lab/salida_integridad_f2.txt` — 33/33 OK; registro real intacto (sha 79f7250d…) |
| F3 | Protocolo pre-registrado + walk-forward anidado (formalización por escrito de cada experimento) | Completada (16/10/2026); se repetirá un pre-registro por experimento en las fases siguientes | Pre-registro de F4: `lab/pre_registro_calibracion.md` (sha 61617cbbc815); convenios y protocolo abajo |
| F4 | Calibración: A modelo / B mercado / C recalibrado / D mezcla, walk-forward puro | Completada (16/10/2026) | `lab/calibracion.py` + `lab/salida_calibracion.txt` — 20/20 comprobaciones OK, determinista; verificación de apoyo `lab/verificacion_calibracion.py` |
| F4b | Integración de la calibración en la app (adoptada: spread C1 · total C1 · moneyline D; versión `cal-f4-1`) | Completada (16/10/2026) | `calibracion.py` (raíz) + `tests/test_calibracion.py` + `lab/verificacion_integracion.py` + `lab/salida_integracion_f4.txt` — 14/14 OK |
| F5 | Motor de EV push-aware + probabilidad de equilibrio + estado de validación | Completada (16/10/2026) | `motor_ev.py` + `tests/test_motor_ev.py` + `lab/verificacion_motor_ev.py` + `lab/salida_motor_ev.txt` — 37/37 OK; sesgo del push medido y documentado en pantalla |
| F6 | UI de decisión (probabilidad, equilibrio, EV, incertidumbre, muestra, motivos, versión, estado) | Pendiente | — |
| F7 | Variables nuevas (descanso, viaje, clima, QB), una a una contra la línea base | Pendiente | — |
| F8 | Escalabilidad multi-deporte | Pendiente | — |

## F0 — Hallazgos verificados (16/10/2026)

| # | Hallazgo | Gravedad | Estado tras F1 |
|---|---|---|---|
| H1 | Calibración: el mercado bate al modelo en los 3 mercados | Alta | Medido con IC en F1 |
| H2 | No queda holdout virgen (2018–2025 consumido; 2006–2017 usado en selección) | Alta | Mitigado con protocolo (abajo) |
| H3 | Moneyline: única señal clara negativa (ROI≈−5%, t≈−2) | Alta | Medido con IC en F1 |
| H4 | Comparaciones modelo vs mercado con n distintos (5511 vs 5375; tabla Brier de la app igual) | Media | Corregido en el instrumento (conjunto estricto) |
| H5 | Postemporada mezclada con temporada regular (232 partidos, 4,2%) | Media | Separada en el instrumento (muestra pequeña aparte) |
| H6 | Línea del backtest = línea de cierre de nflverse, no la del momento de emisión; sin CLV | Media | Pendiente (fase CLV / F5) |
| H7 | EV push-blind y sin probabilidad de equilibrio | Media | Resuelto en F5: `motor_ev.py` (push explícito, equilibrio, estados, banda del calibrado); sesgo del push medido 2006–2025 |
| H8 | 2026 (temporada en curso) entraba sin etiqueta en los agregados | Media-baja | Etiquetada como informativa en el instrumento |
| H9 | Empates ML con doble criterio; etiquetas "push fuera"/"empates fuera" del reporte inexactas a nivel de todos los partidos (push/empate contados como 0 en spread/ML; el total sí los excluía) | Baja | Cuantificado con sensibilidad en el instrumento (Δ apenas cambia) |
| H10 | Cobertura de cuotas irregular 2006–2009; −110 por defecto cuando falta cuota (~2,5% de picks) | Baja | Documentado; % de cuota real impreso junto al ROI |
| H11 | Deuda técnica: helpers de la app sin tests, conversión de cuota duplicada, escritura del registro no atómica, laboratorio fuera del repo | Baja | Resuelto en F2: escritura atómica + validación estructural; lab versionado en F1; helpers cubiertos por pruebas/AST donde aplica (resto: F2-12) |
| H12 | Etiquetas "Nivel: Muy alta/Alta" basadas solo en el tamaño del edge | Baja | Pendiente (F6) |

## F1 — Instrumento de evaluación v3

**Qué es**: la herramienta única para medir el modelo y compararlo con el
mercado. Solo lectura, sin red (bloquea sockets), determinista (semilla
20261016) y autoverificable: reproduce la línea base congelada y devuelve
código 1 si algo no cuadra.

**Cómo se ejecuta**: `cd dashboard_futbol_americano && .venv/bin/python -B lab/evaluacion.py`

**Resultado de la ejecución oficial (16/10/2026)**:

- Verificación: **77/77 comprobaciones OK** (62 de reproducción de la línea
  base al medio dígito impreso + 15 internas: particiones, réplica de
  Brier/LogLoss contra las funciones de producción con error ≤ 1e-12,
  0 intentos de red, 0,62 s de ejecución).
- Salida congelada: `lab/salida_instrumento_v3.txt`. Dos ejecuciones dan
  resultados idénticos (solo varía la línea de tiempo).

**Resultados nuevos medidos** (16/10/2026, conjunto estricto: pronóstico del
modelo **y** probabilidad de mercado **y** resultado decidido, sobre los
mismos partidos; Δ = Brier modelo − Brier mercado, > 0 ⇒ peor el modelo):

| Mercado | n | Brier mod | Brier mer | Δ | IC95% Δ |
|---|---|---|---|---|---|
| Spread | 5236 | 0.2605 | 0.2501 | +0.0104 | [+0.0074, +0.0133] |
| Total | 5296 | 0.2594 | 0.2501 | +0.0093 | [+0.0064, +0.0121] |
| Moneyline | 5360 | 0.2251 | 0.2114 | +0.0137 | [+0.0111, +0.0167] |

- **Temporada regular** (los 3 mercados): el modelo es peor que el mercado
  **con evidencia** (IC95% entero > 0). **Postemporada** (224–230 partidos):
  sin diferencia clara (IC contiene 0) — muestra pequeña, no decide.
- **Sin 2026**: conclusiones idénticas (el 2026, 80 partidos, no mueve nada).
- **ROI con bootstrap** (picks por defecto): spread −1,4% IC95% [−4,6, +2,0]
  → sin evidencia de rentabilidad; total −0,1% [−3,3, +3,3] → sin evidencia;
  moneyline −4,8% [−9,1, −0,5] → **pérdida con evidencia** bajo el umbral actual.
- **Sensibilidad a pushes**: con la convención del reporte anterior el ΔBrier
  apenas cambia (spread +0.0108 vs +0.0104; ML +0.0136 vs +0.0137), pero los
  n sí (5375 → 5236/5360). Las etiquetas eran inexactas; los resultados no.

**Interpretación (medido, no hipótesis)**: con los datos actuales, el mercado
sin vig es mejor estimador que el modelo en los tres mercados durante la
temporada regular, y no hay evidencia de rentabilidad en spread/total. El
moneyline, con el umbral actual, pierde dinero con evidencia estadística.
Todo lo anterior es **retrospectivo y contaminado en grado variable** (ver
historial de uso de datos): sirve para descartar, no para confirmar.

**Archivos nuevos de F1**: `lab/evaluacion.py`, `lab/README.md`,
`lab/salida_instrumento_v3.txt`, `ESTADO_ACTUAL.md`. Ningún archivo existente
fue modificado; el registro de picks sigue intacto (sha 79f7250d…).

## F3 — Pre-registro del experimento de calibración (16/10/2026)

`lab/pre_registro_calibracion.md` fija, **antes de medir**, la pregunta, los
candidatos, el protocolo y las puertas:

- Candidatos (por mercado): **A** modelo crudo · **B** mercado sin vig
  (referencia) · **C1** Platt (logística) · **C2** isotónica (PAVA; solo con
  ≥3000 partidos de ajuste y ventana ≥5 temporadas) · **D** mezcla logística
  (modelo + mercado).
- Protocolo: ventana expansiva (la temporada S se evalúa con ajuste solo en
  temporadas < S); evaluación 2014–2025; 2026 informativo; nada de ROI para
  seleccionar; bootstrap semilla 20261016.
- Puertas: G1 ΔBrier ≤ −0.001 con IC95% entero < 0; G2 lo mismo en LogLoss;
  G3 cobertura ≥ 98%; G5 mejora en ≥ 2/3 de las temporadas (y ≥ 5 temporadas);
  G4 informativa Δ(D − B). Desempate: mejor ΔBrier; a ≤ 0.0001, menos
  parámetros.

## F4 — Calibración walk-forward (16/10/2026)

**Ejecución**: `lab/calibracion.py` — solo lectura, sin red, determinista;
**20/20 comprobaciones internas OK** (0,68 s); dos ejecuciones idénticas;
salida congelada en `lab/salida_calibracion.txt` (sha del pre-registro en la
cabecera). Verificación de apoyo: `lab/verificacion_calibracion.py` →
`lab/salida_verificacion_f4.txt`.

**Brier en la ventana de evaluación** (2014–2025; n del candidato entre
paréntesis):

| Mercado | A crudo | B mercado | C1 Platt | C2 isótona | D mezcla |
|---|---|---|---|---|---|
| Spread | 0.2607 (3213) | 0.2500 | 0.2499 | 0.2515 (1917)\* | 0.2499 |
| Total | 0.2621 (3263) | 0.2500 | 0.2507 | 0.2517 (2205)\* | 0.2508 |
| Moneyline | 0.2253 (3283) | 0.2118 | 0.2254 | 0.2281 (2219)\* | 0.2118 |

(\* La isótona solo existe desde que el ajuste acumula ≥3000 partidos:
spread 2019–2025; total y moneyline 2018–2025.)

**ΔBrier de cada candidato vs A (IC95% pareado)**:

- Spread: C1 −0.0108 [−0.0144, −0.0072] (11/12 temporadas mejor) · C2 −0.0119
  [−0.0162, −0.0076] (7/7) · D −0.0107 [−0.0143, −0.0073] (11/12).
- Total: C1 −0.0114 [−0.0146, −0.0082] (12/12) · C2 −0.0096 (falla G2) ·
  D −0.0113 [−0.0148, −0.0080] (12/12).
- Moneyline: D −0.0135 [−0.0171, −0.0098] (12/12) · C1 +0.0001 (falla) ·
  C2 +0.0010 (falla).

**Veredictos de las puertas**: Spread → C1, C2 y D pasan. Total → C1 y D
pasan; C2 cae en G2. Moneyline → solo D pasa.

**Elección** (regla pre-registrada): Total → **C1** (empate a 0.0001 con D en
ΔBrier → menos parámetros). Moneyline → **D**. Spread → **matiz
documentado**: la regla literal elige C2, pero comparaba ventanas distintas
(C2 solo existe 2019–2025, donde el modelo crudo es peor y todo Δ parece
mayor). En la **ventana común (2019–2025)**: C1 y D = 0.2501 (Δ −0.0133)
frente a C2 = 0.2515 (Δ −0.0119); contra el mercado: C1 empata (+0.0005
[−0.0005, +0.0016]), D empata (−0.0001 [−0.0009, +0.0007]), C2 queda detrás
(+0.0020 [+0.0001, +0.0039]). → **Adoptado el 16/10/2026: C1 (Platt) para
spread** (ver F4b).

**Verificación de apoyo** (rejilla de verosimilitud, ajuste 2006–2025): el
óptimo de Platt es b≈0.066 en spread y b≈0.059 en total — la variación de
las probabilidades del modelo en esos mercados **no aporta señal** (colapsa
hacia ~49–51%); en moneyline b≈0.956 (informativas, pero menos que el
mercado). Benchmark sin información (constante 50 %): Brier ≈ 0.2500 en los
tres mercados.

**Interpretación (medido)**: la recalibración elimina la falsa confianza del
modelo (mejoras grandes y consistentes vs A, IC entero < 0) pero **no crea
señal nueva**: tras calibrar, nada bate al mercado sin vig — spread y
moneyline empatan estadísticamente (IC contiene 0) y total queda una pizca
detrás (+0.0007 para C1 y +0.0008 para D, IC apenas > 0). En moneyline la
mezcla D da al modelo un peso ≈ 0.006: **no aporta nada sobre el mercado**.
En 2026 (informativo, n=74–80) los calibrados también mejoran (ΔBrier ≈
−0.009 a −0.017, salvo C1 en moneyline ≈ 0), pero la muestra es minúscula y
la temporada está contaminada; no decide. **Consecuencia directa**: los
edges de 8 %+ con que se generaban picks (y las etiquetas «Nivel») eran en su
mayoría falsa confianza; con probabilidades honestas aparecerán muy pocos
EV+ y el eje real de búsqueda pasa a ser el precio/CLV (H6), no la
«información propia».

**Contaminación**: 2014–2025 es retrospectivo (2018–2025 consumido por
srs-v2; 2006–2017 usado en la rejilla). Estas puertas miden señal, no
inmunidad; valen para descartar; la confirmación limpia es prospectiva.

**Archivos nuevos de F3–F4**: `lab/pre_registro_calibracion.md`,
`lab/calibracion.py`, `lab/salida_calibracion.txt`,
`lab/verificacion_calibracion.py`, `lab/salida_verificacion_f4.txt`. Ningún
archivo de la app fue modificado; el registro de picks sigue intacto; las
62/62 pruebas del proyecto siguen verdes.

## F4b — Integración de la calibración en la app (16/10/2026)

**Adoptado** (tras aprobar la recomendación de F4): spread → **C1 (Platt)** ·
total → **C1 (Platt)** · moneyline → **D (mezcla)**. Versión de probabilidad
**`cal-f4-1`**; el registro fiel sella los picks nuevos como
**`srs-v2+cal-f4-1`**. Coeficientes congelados (ajuste 2006–2025, universo
estricto) en `calibracion.py` (sha aee60d2b5fc7), con el procedimiento de
refit documentado en su cabecera: no se editan "a ojo".

**Qué cambia en la app** (mínimo, reversible, sin tocar el historial):

- La probabilidad que se **congela** en el registro fiel (jornada pendiente)
  pasa a ser la calibrada: `evaluar_spread`/`evaluar_totales` (app.py) y
  `evaluar_picks_ml` (datos.py) ganan un modo `calibrado=True` que solo usa la
  ruta de la jornada pendiente; las vistas históricas conservan sus
  probabilidades brutas (nada se reescribe).
- La selección de spread/totales (edge en **puntos**) no cambia. La de
  moneyline usa la probabilidad, así que con la mezcla (peso del modelo
  ≈ 0.006, sigue al mercado) los edges calibrados ≈ 0 y **moneyline queda sin
  picks**: es el resultado medido en F4, no un fallo.
- El EV del registro se calcula con la probabilidad calibrada (deja de estar
  inflado por la falsa confianza).

**Evidencia** (`lab/verificacion_integracion.py` →
`lab/salida_integracion_f4.txt`; **14/14 OK**, determinista, sin red; ejecuta
las funciones REALES de `app.py` extraídas por AST, sin Streamlit):

- Muestra determinista de 300 partidos: spread 190 picks con selección
  idéntica bruto vs calibrado; |p−0.5| medio 0.1385 → 0.0109. Total: 170
  picks; 0.1290 → 0.0080.
- Moneyline en la misma muestra: 217 picks brutos → **0 calibrados**.
- Jornada pendiente real (n=26 partidos con líneas): spread 14 y total 13
  picks congelables; moneyline 14 brutos → 0. Ejemplo de EV congelado:
  MIN @ CLE (−110): p bruta 0.6265 (EV +0.196) → p calibrada 0.5193
  (EV −0.009 $ por $1).
- Registro de picks intacto (sha 79f7250d…).

**Pruebas**: `tests/test_calibracion.py` — 16 pruebas nuevas (fórmula
independiente, anclajes congelados, monotonía, vacíos, contrato de moneyline,
versión del registro y **re-ajuste real** del universo 2006–2025 del CSV que
reproduce los coeficientes congelados al 1e-9). Total del proyecto: **78/78**
verdes; `py_compile` OK; ninguna prueba usa red.

**Limitaciones de este bloque**: la confirmación de la calibración es
prospectiva (los picks nuevos son los primeros sellados con `cal-f4-1`); lo
retrospectivo sigue contaminado. La selección de spread/totales sigue siendo
por puntos hasta que F5 la sustituya por EV push-aware; hasta entonces el
registro mostrará EV ≈ negativo en esos picks (honesto: es la realidad
medida hoy). Refit solo con el procedimiento de `calibracion.py`.

## F5 — Motor de EV con push explícito (16/10/2026)

**Pre-registro**: `lab/pre_registro_motor_ev.md` (sha 0731404155e6), fijado
antes de medir. Regla clave que se aplicó al pie de la letra: si la
verificación empírica del push falla la tolerancia (0.015), el estimador «no
se adopta sin documentar la limitación en pantalla».

**Qué se adoptó**:

- `motor_ev.py` (nuevo, autónomo: numpy/pandas + `calibracion`): momio
  americano → pago neto y probabilidad implícita; **probabilidad de
  equilibrio** = 1/(1+pago neto) (el valor de p_condicional que hace EV = 0;
  el push no mueve el umbral: devuelve el importe); **push explícito** (0
  exacto en líneas x.5 — aritmético, no supuesto; normal discretizada en
  líneas enteras; empate = línea 0 en moneyline); **EV por $1** =
  (1−p_push)·(p_cond·pago − (1−p_cond)); descomposición coherente
  p_ganar+p_perder+p_push = 1; **banda del calibrado** (delta method con la
  covarianza H⁻¹ congelada del ajuste 2006–2025 — solo error de estimación).
- Estados en la interfaz (ninguno dice «validada»): «Sin EV» (EV ≤ 0),
  «EV+ en el ruido» (EV > 0 con el IC95% tocando 0), «EV+ sin validar»
  (IC95% entero > 0). Validación de estrategia = prospectiva, hoy inexistente.
- La app (🎯 y 📋) muestra por pick: momio, **P. eq.**, **P. est.**,
  **P. push**, **EV $1** y **Estado**, con las notas de alcance (la
  incertidumbre no cubre cambio de régimen ni error de modelo; el sesgo del
  push está medido; nada se «valida»). **La selección no cambia** (F5 no toca
  umbrales). Los picks nuevos congelan el EV del motor (columna `ev_num` en
  `registro_desde_picks`); los históricos **no se recalculan** (fallback
  exacto a la fórmula anterior, con prueba).
- Versión del motor: `ev-f5-1` (el registro sigue sellando `srs-v2+cal-f4-1`:
  aún no se ha capturado ninguna fila nueva).

**Evidencia** (`lab/verificacion_motor_ev.py` → `lab/salida_motor_ev.txt`;
**37/37 OK**, determinista salvo la línea de reloj, sin red, 0,4 s):

- Matemáticas con casos a mano: −110 → pago 10/11 y equilibrio 110/210;
  EV(p=0.5) → −1/22; EV = 0 exacto en el equilibrio con cualquier push
  (5e-17); coherencia ±0; push = 0 exacto en x.5.
- Jornada pendiente real (funciones de `app.py` extraídas por AST, n=26
  partidos): spread 14 picks · total 13 · moneyline 0 (heredado de F4b); EV
  recalculado de forma independiente (±0); ev_lo ≤ EV ≤ ev_hi; estados
  válidos. Hoy: 25 «Sin EV» y 2 «EV+ en el ruido» (LAC @ KC −105 y LA @ LV
  −105, ambos con el IC tocando 0) — **ninguna apuesta recomendable** y
  ninguna marcada como validada.
- Push empírico 2006–2025 (5.511 partidos jugados): spread Δ −1.06 pp
  (dentro de tolerancia; detalle: −1.96 pp en líneas enteras), total
  Δ −0.09 pp, **moneyline Δ +2.38 pp → FUERA de tolerancia** (el empate real
  es más raro que la normal: 0.27% observado vs 2.65% estimado). Ruta
  pre-registrada aplicada: sesgo medido y **documentado en pantalla**
  (`NOTA_PUSH` en el caption del 🎯); el único mercado afectado (moneyline)
  hoy emite 0 picks.
- Regresión contra lo existente (pago neto, implícita, probabilidad bruta) a
  1e-12; el registro guarda `ev_num` tal cual y conserva la fórmula aproximada
  cuando no viene.
- Verificación visual de la interfaz: cazó un bug de la integración F5 (no
  del motor) — la tabla de totales del 🎯 construía `Cuota` (mayúscula) y sin
  `al_over`, columnas que `decorar` exige; la verificación por AST no lo veía
  porque ejecuta `evaluar_totales` (que sí las produce). Corregido y
  re-verificado: 🎯 y 📋 renderizan completas y sus números coinciden con esta
  salida congelada.

**Pruebas**: 42 pruebas nuevas (`tests/test_motor_ev.py` 33 + ampliación de
`test_calibracion.py` 6 — covarianzas reproducidas por re-ajuste y banda — +
3 de `ev_num` en `test_datos.py`). Total del proyecto: **120/120** verdes;
`py_compile` OK; sin red; registro intacto (sha 79f7250d…).

**Limitaciones de este bloque**:

- La banda del EV cubre SOLO el error de estimación de los coeficientes de
  calibración; no cubre cambio de régimen, error de modelo ni la
  incertidumbre del push (estimado con el modelo, con el sesgo medido).
- Un EV+ no es validación: los 2 EV+ de hoy están «en el ruido»; la
  confirmación limpia es prospectiva (registro fiel).
- El sesgo del push sesga el EV mostrado: en líneas enteras de spread
  subestima ~2 pp el push ⇒ infla ~2% el |EV| de esas líneas; en moneyline
  sobreestima +2.4 pp el empate ⇒ desinfla el EV de picks ML (hoy 0).
- `datos._pago_por_dolar` sigue asumiendo −110 en el ROI histórico; el motor
  **no rellena nada** (diferencia deliberada, con prueba de regresión).

## F2 — Guardarraíles e integridad (16/10/2026)

**Qué es**: la capa de confiabilidad operativa del registro y de los datos,
sin tocar el modelo, la calibración, los umbrales ni los picks. Diagnóstico
previo con la lista priorizada de riesgos en `lab/diagnostico_f2.md` (escrito
**antes** de corregir: primero se documenta, después se arregla con prueba).

**Qué se corrigió** (nueve hallazgos; detalle y evidencia por hallazgo en el
diagnóstico):

- **F2-1 (crítico, seguridad)**: el mensaje de error de The Odds API podía
  mostrar la clave en pantalla (la excepción de `requests` incluye la URL con
  `apiKey=…`; reproducido en local con una conexión fallida). Ahora todo
  mensaje derivado de excepción o respuesta pasa por `datos._redactar_secretos`
  (tapa el propio secreto y cualquier `apiKey=…`). El archivo de secretos no
  se toca y `.streamlit/secrets.toml` sigue ignorado por Git.
- **F2-2 (alto)**: la escritura del registro fiel es **atómica** (temporal en
  la misma carpeta + `os.replace`): una interrupción a mitad de escritura deja
  intacto el registro anterior, que es irremplazable.
- **F2-3 (alto)**: **validación estructural** antes de capturar
  (`datos.validar_registro_picks`: ids duplicados o vacíos, probabilidades
  fuera de [0,1], cuota 0 o infinita, edge/ev no finitos, mercado/lado
  incoherentes, temporada/semana no enteras…). Errores → **no se escribe
  nada** (falla cerrada, con mensaje claro); avisos → se muestran en pantalla;
  los vacíos legítimos NO son errores (no se inventa nada). También bloquea la
  captura si el archivo en disco ya trae errores (antes, `drop_duplicates`
  podía reescribirlo en silencio).
- **F2-4 (medio)**: la captura nueva sella `srs-v2+cal-f4-1+ev-f5-1` (modelo +
  calibración + motor de EV) en vez del sello parcial; la app muestra las
  versiones presentes en el registro.
- **F2-5 (medio)**: la captura congela `p_push` (el EV guardado pasa a ser
  auditable sin re-ejecutar el estimador); la tabla del registro fiel la
  muestra. Las filas viejas quedan con la celda vacía (compatible).
- **F2-6 (medio)**: los pendientes de la jornada se etiquetan «🧾 Línea de
  hoy» (antes decían «Reconstruido» sin tener resultado; y «Sin congelar»
  confundía con el aviso de que la jornada ya está capturada); el texto aclara
  que solo lo congelado es evidencia prospectiva y que la versión congelada,
  si existe, vive en el registro fiel.
- **F2-7 (bajo)**: alarma de coherencia de la terna p_ganar/p_perder/p_push
  (`motor_ev.problemas_coherencia`: suma 1 ±1e-9, rangos y coherencia con
  `p_estimada`) revisada antes de congelar; si no cuadra, no se captura.
- **F2-8 (bajo)**: temporada/semana vacías dan un `ValueError` en español
  (antes: error de conversión de pandas).
- **F2-9 (bajo)**: la suite bloquea la red (`tests/__init__.py`): ninguna
  prueba puede tocar servicios externos ni gastar créditos, aunque alguien
  añada una prueba descuidada.

**Evidencia** (`lab/verificacion_integridad.py` → `lab/salida_integridad_f2.txt`;
**33/33 OK**, 0,45 s, sin red, determinista salvo la línea de reloj):

- El registro real pasa limpio (50 filas, 0 duplicados, 0 valores imposibles)
  y queda **intacto**: sha1 `79f7250d7a87` idéntico antes y después (el mismo
  de la línea base F5). La verificación trabaja sobre copias temporales.
- Captura de prueba sobre una copia: solo añade; las filas viejas quedan
  idénticas (`assert_frame_equal` fila a fila); recapturar no cambia un byte;
  una línea movida no reescribe lo congelado; el sello y `p_push`/EV quedan
  congelados tal cual.
- Fallo de escritura simulado → original intacto y sin `.tmp`. Fila imposible
  (p=1.5) o archivo con ids duplicados → rechazo con mensaje, sin escribir.
- La jornada real mantiene los picks de la línea base F5 (spread 14 / total
  13 / moneyline 0) y 0 incoherencias de la terna.
- Seguridad: el redactado tapa la clave en los dos caminos de error; la app
  está cableada a `VERSION_REGISTRO`, la validación, la coherencia y la
  columna `p_push` (comprobado por AST/fuente).

**Pruebas**: 23 nuevas (4 de redactado de claves, 12 de integridad del
registro, 6 de coherencia de la terna, 1 de la guardia de red). Total del
proyecto: **143/143** verdes; `py_compile` OK.

**Cambios visibles en el dashboard** (solo en el registro): aviso ✓/⚠️/🛑 de
validación del registro fiel; columna «P. push» en su tabla; etiqueta «🧾
Línea de hoy» en los pendientes; pie con las versiones congeladas; textos
actualizados. El modelo, la calibración, los umbrales y los picks no cambian.

**Limitaciones de este bloque**:

- La validación es estructural, no semántica: detecta lo imposible, no lo
  legal-pero-erróneo (p. ej., una cuota válida que no era la del momento).
- El resultado del registro fiel se sigue derivando del marcador actual de
  nflverse (determinista, con la línea congelada); el marcador no se congela
  (F2-10, mejora futura documentada).
- `capturado_en` sigue en hora local sin zona (F2-11).
- Los bloques de pestaña no tienen pruebas directas (F2-12: se cubren por
  extracción AST y verificación visual del render).

## Protocolo anti-contaminación (fijado el 16/10/2026)

Historial de uso de los datos:

- 1999–2005: fuera de la era de evaluación (sin cuotas reales).
- 2006–2017: usado para seleccionar la rejilla del modelo → contaminado
  para cualquier selección nueva.
- 2018–2025: holdout usado UNA vez para elegir srs-v2 → **consumido**.
- 2026 (en curso): mirado anecdóticamente en el Bloque 3 → contaminado para
  conclusiones; solo informativo.

Reglas para las fases siguientes:

1. Toda comparación modelo vs mercado se mide con el instrumento v3 (o su
   misma lógica): mismos partidos, push estricto, IC95%.
2. Las selecciones nuevas (umbrales, calibradores, features) usan
   **walk-forward anidado**: ningún periodo informa la evaluación de sí
   mismo. Nada se elige maximizando ROI.
3. La **confirmación limpia es prospectiva**: cuenta solo lo decidido y
   sellado hacia adelante (el registro fiel ya sella los picks emitidos).
4. Todo resultado retrospectivo se etiqueta como contaminado en grado
   variable; si no permite conclusión fiable, se dice explícitamente.

## Limitaciones permanentes (hoy)

- No existe fuente histórica de cuotas de apertura/cierre fiable para CLV.
- Las líneas del backtest son la línea única de nflverse (no el precio de
  ejecución real del momento de emitir).
- Cobertura de cuotas parcial en 2006–2009; −110 asumido cuando falta cuota.
- Postemporada y 2026: muestras pequeñas; no deciden nada por sí solas.
- El modelo (srs-v2) fue elegido con datos ya consumidos; cualquier mejora
  futura arrastra esa contaminación si se mide en el mismo periodo.

## Próximo paso

F5 y F2 están **cerradas**. F5: el EV se calcula con push explícito,
probabilidad de equilibrio, banda del calibrado y estado; el sesgo del push
está medido y documentado en pantalla, y ningún estado «valida» nada. F2: el
registro fiel está validado, se escribe de forma atómica, sella
`srs-v2+cal-f4-1+ev-f5-1` con `p_push` congelada, y la clave de la API no
puede aparecer en pantalla (33/33 OK; registro intacto). Siguiente: **F6**
(UI de decisión: muestra, motivos, incertidumbre visible, revisión de las
etiquetas «Nivel» — H12 — y de la presentación de los estados). Después,
**F7** (variables nuevas, una a una contra la línea base). El eje de búsqueda
de EV+ sigue siendo el precio/CLV (H6), no la «información propia»; la
confirmación de cualquier estrategia es prospectiva (registro fiel).
