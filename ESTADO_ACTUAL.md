# ESTADO ACTUAL — Dashboard de Fútbol Americano

Bitácora de la etapa de mejora estadística (encargo de 7 fases, 16/10/2026).
Se actualiza al cerrar cada fase. Las decisiones fijadas aquí solo cambian
con evidencia nueva y quedando documentado el cambio.

Última actualización: 16/10/2026 (F4 completada).

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
| F2 | Guardarraíles de código (tests de `evaluar_spread`/`evaluar_totales`, conversión de cuota única, escritura atómica del registro) | Pendiente | — |
| F3 | Protocolo pre-registrado + walk-forward anidado (formalización por escrito de cada experimento) | Completada (16/10/2026); se repetirá un pre-registro por experimento en las fases siguientes | Pre-registro de F4: `lab/pre_registro_calibracion.md` (sha 61617cbbc815); convenios y protocolo abajo |
| F4 | Calibración: A modelo / B mercado / C recalibrado / D mezcla, walk-forward puro | Completada (16/10/2026) | `lab/calibracion.py` + `lab/salida_calibracion.txt` — 20/20 comprobaciones OK, determinista; verificación de apoyo `lab/verificacion_calibracion.py` |
| F5 | Motor de EV push-aware + probabilidad de equilibrio + estado de validación | Pendiente | — |
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
| H7 | EV push-blind y sin probabilidad de equilibrio | Media | Pendiente (F5) |
| H8 | 2026 (temporada en curso) entraba sin etiqueta en los agregados | Media-baja | Etiquetada como informativa en el instrumento |
| H9 | Empates ML con doble criterio; etiquetas "push fuera"/"empates fuera" del reporte inexactas a nivel de todos los partidos (push/empate contados como 0 en spread/ML; el total sí los excluía) | Baja | Cuantificado con sensibilidad en el instrumento (Δ apenas cambia) |
| H10 | Cobertura de cuotas irregular 2006–2009; −110 por defecto cuando falta cuota (~2,5% de picks) | Baja | Documentado; % de cuota real impreso junto al ROI |
| H11 | Deuda técnica: helpers de la app sin tests, conversión de cuota duplicada, escritura del registro no atómica, laboratorio fuera del repo | Baja | Lab ya versionado en F1; resto → F2 |
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
(+0.0020 [+0.0001, +0.0039]). → Recomendación: **C1 (Platt) para spread**;
decisión final del usuario al aprobar la integración.

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

**Decisión de integración de la calibración** (bloque aparte, pendiente de
OK): candidatos por mercado — Spread: C1 (Platt) recomendado (la elección
literal a favor de C2 dependía de comparar ventanas distintas; en la ventana
común C1 gana y C2 queda detrás del mercado) · Total: C1 (Platt) · Moneyline:
D (mezcla), el único que pasa; nota: D ≈ mercado y con peso del modelo ≈ 0
(alternativa de producto: usar directamente la probabilidad sin vig del
mercado en moneyline). Requisitos de la integración: probabilidad calibrada
versionada en el registro (p. ej. «srs-v2+cal»), sin reescribir historial y
con pruebas propias. Después: **F5** (EV push-aware + probabilidad de
equilibrio) y **F6** (UI de decisión) sobre esas probabilidades.
**F2 (guardarraíles)** sigue disponible; no cambia resultados, solo reduce
riesgo técnico.
