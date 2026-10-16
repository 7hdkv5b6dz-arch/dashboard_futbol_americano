# Pre-registro — F5: motor de EV con push explícito (16/10/2026)

Fijado **antes de medir nada**. Si algo se cambia tras ver resultados, se
documenta como desviación y el experimento se repite con el protocolo nuevo.

## Pregunta

¿El valor esperado de cada apuesta se calcula de forma matemáticamente
correcta y honesta (probabilidad calibrada + momio disponible + push
explícito), y la interfaz lo muestra sin clasificar nada como «validado»?

## Qué NO hace F5 (puertas de alcance)

- **NO cambia umbrales ni criterios de selección** de picks (eso exige su
  propio pre-registro; hoy la selección de spread/totales sigue siendo por
  puntos y la de moneyline por probabilidad calibrada).
- **NO usa ROI histórico** para elegir nada.
- **NO toca el registro fiel existente** (solo-añadir): los picks históricos y
  sus probabilidades/EV congelados no se recalculan con el motor nuevo.
- **NO declara rentabilidad**: calcular bien un EV no valida ninguna apuesta.

## Procedimiento de evaluación (criterios de aceptación, fijados aquí)

1. **Corrección matemática** por pruebas unitarias con casos a mano:
   - Cuota −110 → pago neto 10/11; probabilidad de equilibrio 110/210.
   - Cuota +130 → pago neto 1.3; probabilidad de equilibrio 100/230.
   - EV sin push: p=0.5 con −110 → −0.045454…; p=0.6 con −110 → +0.145454…
   - EV con push: escala por (1−p_push); en p = probabilidad de equilibrio el
     EV es 0 **exactamente**, para cualquier p_push.
   - Coherencia: p_ganar + p_perder + p_push = 1 (±1e-12), con
     p_ganar = (1−p_push)·p_condicional.
   - Vacíos: sin cuota o sin probabilidad → EV vacío (no se inventa −110).
2. **Regresión**: las conversiones nuevas coinciden con las existentes
   (`datos._prob_implicita`, `datos._pago_por_dolar`) a 1e-12 en una rejilla
   de cuotas, y todos los tests actuales del proyecto siguen verdes.
3. **Push**: p_push = 0 EXACTO en líneas .5 (aritmético: el marcador es
   entero y nunca cae en x.5); estimado con la normal discretizada en líneas
   enteras y en empates (moneyline). Verificación empírica agregada
   (2006–2025, partidos jugados): |media estimada − frecuencia observada|
   ≤ 0.015 por mercado (spread, total, moneyline). Si falla, el estimador no
   se adopta sin documentar la limitación en pantalla.
4. **Incertidumbre**: IC95% del calibrado por error de estimación de los
   coeficientes (delta method con la covarianza del ajuste congelado; la
   covarianza se verifica por re-ajuste igual que los coeficientes).
   Cubre SOLO error de estimación: **no** incluye cambio de régimen ni error
   de modelo (se documenta en la interfaz y aquí).
5. **Estados**: ninguna etiqueta dice «validada». EV ≤ 0 → «Sin EV»; EV > 0
   con el IC95% tocando 0 → «EV+ en el ruido»; EV > 0 con IC95% entero > 0 →
   «EV+ sin validar». La validación de la estrategia es **prospectiva**
   (registro fiel) y hoy no existe muestra limpia: 2018–2025 ya se consumió
   con srs-v2 y 2006–2017 con la rejilla; 2026 es anecdótico/contaminado.

## Periodos de datos ya utilizados (registro de contaminación)

- 2006–2017: selección de la rejilla del modelo → contaminado.
- 2018–2025: holdout de srs-v2 (una vez) + evaluación walk-forward F4 →
  consumido.
- 2026: mirado anecdóticamente → informativo.

F5 **no selecciona parámetros con datos**: los coeficientes de calibración
están congelados (`cal-f4-1`) y la covarianza se congela del MISMO ajuste
2006–2025. La verificación empírica del push usa 2006–2025 solo como control
de magnitud (no elige nada).

## Evidencia exigida al cierre

- `tests/test_motor_ev.py` (+ ampliación de `test_calibracion.py`) verdes;
  suite completa verde; sin red; registro intacto.
- `lab/verificacion_motor_ev.py` → salida congelada `lab/salida_motor_ev.txt`
  (determinista; imprime el sha1 de este pre-registro).
- Informe de limitaciones: qué NO cubre la incertidumbre, push basado en
  modelo, selección sin cambios.
