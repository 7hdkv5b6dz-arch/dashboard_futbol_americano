# Laboratorio de evaluación (`lab/`)

Instrumental de medición del proyecto, **versionado dentro del repo** para que
los experimentos sean reproducibles desde git (hasta el 16/10/2026 vivían
fuera, en una carpeta temporal).

## Archivos

- `evaluacion.py` — **Instrumento de evaluación v3**. Mide el modelo srs-v2 y
  lo compara con el mercado sin vig. Solo lectura, sin red, determinista.
- `salida_instrumento_v3.txt` — Salida congelada de referencia del instrumento.
- `pre_registro_calibracion.md` — Pre-registro del experimento F4 (escrito
  antes de medir; su sha1 queda impreso en la cabecera de la salida de F4).
- `calibracion.py` — Experimento F4: calibración walk-forward por mercado
  (A crudo / B mercado / C1 Platt / C2 isótona / D mezcla) con las puertas de
  adopción pre-registradas. Solo lectura, sin red, determinista.
- `salida_calibracion.txt` — Salida congelada de F4 (20/20 comprobaciones).
- `verificacion_calibracion.py` — Verificación de apoyo de F4 (ventana común
  entre candidatos, Δ vs mercado, rejilla de verosimilitud del óptimo Platt).
- `salida_verificacion_f4.txt` — Salida congelada de la verificación de apoyo.
- `verificacion_integracion.py` — Verificación de la **integración** de la
  calibración (F4b): ejecuta las funciones reales de `app.py` extraídas por
  AST (sin Streamlit) y comprueba selección, probabilidad congelada, EV,
  moneyline y versión del registro.
- `salida_integracion_f4.txt` — Salida congelada de la integración (14/14).
- `pre_registro_motor_ev.md` — Pre-registro de F5 (motor de EV con push
  explícito), escrito antes de medir; su sha1 queda impreso en la cabecera de
  la salida de F5.
- `verificacion_motor_ev.py` — Verificación de F5: matemáticas del motor,
  jornada pendiente real (funciones de `app.py` por AST), push empírico
  2006–2025 contra lo observado, regresión contra `datos` y contrato `ev_num`.
- `salida_motor_ev.txt` — Salida congelada de F5 (37/37 comprobaciones).

La calibración **adoptada** (producción) vive fuera del laboratorio, en
`calibracion.py` (raíz del proyecto), con coeficientes y covarianzas congelados
y pruebas propias (`tests/test_calibracion.py`); el laboratorio es lo que
produjo la evidencia. Lo mismo para el motor de EV **adoptado**: `motor_ev.py`
(raíz), con pruebas propias en `tests/test_motor_ev.py`.

## Cómo se ejecuta

```bash
cd dashboard_futbol_americano
.venv/bin/python -B lab/evaluacion.py
.venv/bin/python -B lab/calibracion.py            # F4
.venv/bin/python -B lab/verificacion_calibracion.py  # apoyo de F4
.venv/bin/python -B lab/verificacion_integracion.py  # integración (F4b)
.venv/bin/python -B lab/verificacion_motor_ev.py     # motor de EV (F5)
```

No escribe ningún archivo del proyecto, no usa red (bloquea sockets durante el
cálculo) y no consume créditos de ninguna API. Tarda unos segundos.

## Qué mide

1. **Reproducción de la línea base** (16/10/2026): picks por defecto
   (spread/total umbral 2.0, moneyline 4 pp), Brier/LogLoss y sigmas. Si algo
   no cuadra al medio dígito impreso, el instrumento falla con código 1 y no
   debe usarse para decidir.
2. **Mismos partidos (conjunto estricto)**: Brier/LogLoss de modelo vs mercado
   sobre exactamente los mismos partidos, con push y empates fuera para ambos
   lados, y IC95% del ΔBrier por bootstrap pareado.
3. **Segmentos separados**: temporada regular vs postemporada, y con/sin la
   temporada en curso (2026), que queda marcada como informativa.
4. **Robustez**: IC95% bootstrap del ROI (semilla fija), sensibilidad a la
   convención de push del reporte anterior, y verificación interna de
   particiones y de la réplica contra las funciones de producción de
   `datos.py`.

## Convenios (fijados en la auditoría del 16/10/2026)

- Era de evaluación: temporada 2006+ (antes no hay cuotas reales).
- Conjunto estricto: pronóstico del modelo **y** probabilidad de mercado
  **y** resultado decidido; push (spread/total) y empate (moneyline) fuera.
- ΔBrier = Brier(modelo) − Brier(mercado) sobre los mismos partidos;
  Δ > 0 ⇒ el modelo es peor.
- El ROI de picks usa la cuota real del CSV; sin cuota se asume −110
  (igual que la app).
- Los resultados retrospectivos están contaminados en grado variable
  (ver `ESTADO_ACTUAL.md`): el holdout 2018–2025 se usó una vez para elegir
  srs-v2 y 2006–2017 se usó para seleccionar la rejilla.
- Calibración (F4): walk-forward puro (la temporada evaluada nunca informa su
  propio ajuste); ventana de evaluación 2014–2025; las puertas G1–G5 están
  fijadas en `pre_registro_calibracion.md` y no se cambian tras ver resultados.
- Motor de EV (F5): push explícito (0 exacto en líneas x.5 — aritmético;
  normal discretizada en enteras y empates) con **sesgo medido** contra
  2006–2025 (tolerancia pre-registrada 0.015 por mercado: total y spread
  agregado dentro; el empate de moneyline queda fuera y se documenta en
  pantalla, como fija `pre_registro_motor_ev.md`). La banda del EV cubre solo
  el error de estimación de los coeficientes de calibración (delta method con
  la covarianza congelada).

## Reglas de uso para las fases siguientes

- Toda comparación modelo vs mercado se hace con este instrumento (o con su
  misma lógica) sobre el conjunto estricto.
- Si se cambia una convención de medición, se actualiza aquí, se regenera
  `salida_instrumento_v3.txt` y se anota en `ESTADO_ACTUAL.md`.
- El instrumento no decide estrategias: mide. Las decisiones (umbrales,
  calibración, EV) van con su propia puerta de aceptación pre-fijada.
