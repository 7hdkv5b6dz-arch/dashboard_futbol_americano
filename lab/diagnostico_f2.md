# Diagnóstico F2 — guardarraíles e integridad (16/10/2026)

Inspección de la arquitectura actual **antes de cambiar nada** (app.py 2.632
líneas, datos.py 1.225, calibracion.py 240, motor_ev.py 342, registro de 50
filas). Los hallazgos se listan por severidad; cada uno indica evidencia,
impacto y el arreglo previsto con su criterio de aceptación.

Regla del encargo: lo que pueda **corromper el registro** o **cambiar el EV
mostrado** se documenta aquí primero (hecho) y se corrige después con prueba
de regresión.

**Verificación final (16/10/2026)**: este documento se escribió ANTES de
tocar código (los riesgos y sus arreglos previstos quedaron fijados aquí);
al cerrar, los nueve hallazgos corregibles quedaron implementados y
comprobados — `lab/verificacion_integridad.py` →
`lab/salida_integridad_f2.txt` (**33/33 OK**, 0,45 s, sin red), suite de
pruebas **143/143 OK** y el registro real intacto (sha1 `79f7250d7a87`, el
mismo de la línea base F5). Las filas de la tabla de arriba quedan en
«Corregido» con esa evidencia.

## Qué NO cambia en F2

- Coeficientes de calibración, umbrales de selección, modelo srs-v2, motor
  ev-f5-1: intactos.
- Picks existentes y el registro fiel: no se reescriben ni recalculan.
- Ninguna prueba toca la red ni gasta créditos de APIs.

## Resumen priorizado

| # | Hallazgo | Severidad | Estado |
|---|---|---|---|
| F2-1 | La clave de The Odds API puede quedar visible en pantalla (mensaje de error con la URL) | **Crítico** | Corregido |
| F2-2 | Escritura del registro no atómica (una interrupción puede truncarlo) | **Alto** | Corregido |
| F2-3 | Sin validación estructural del registro (duplicados, filas incompletas, valores imposibles) | **Alto** | Corregido |
| F2-4 | El sello de versión no incluye el motor de EV | Medio | Corregido |
| F2-5 | El registro no congela `p_push` (el EV guardado depende de ella) | Medio | Corregido |
| F2-6 | «🧮 Reconstruido» también etiqueta picks pendientes (confunde reconstrucción con proyección viva) | Medio | Corregido |
| F2-7 | La coherencia p_ganar/p_perder/p_push no tiene alarma explícita antes de congelar | Bajo | Corregido |
| F2-8 | `registro_desde_picks` con temporada/semana vacías da un error de conversión feo | Bajo | Corregido |
| F2-9 | La suite de pruebas no bloquea la red de forma global | Bajo | Corregido |
| F2-10 | Resultado derivado con el marcador de HOY: si nflverse revisara un marcador, el resultado derivado cambiaría (el marcador no se congela) | Mejora futura | Documentado |
| F2-11 | `datetime.now()` sin zona horaria en `capturado_en` | Mejora futura | Documentado |
| F2-12 | Helpers de la app sin pruebas directas (se cubren por AST donde se puede) | Mejora futura | Documentado |

## Detalle

### F2-1 · Fuga de la clave de The Odds API (crítico) — CORREGIDO

- **Evidencia**: `datos.cargar_precios_casas` hace
  `raise ValueError(f"Sin conexión con The Odds API ({error}).")`. La
  representación de `requests.RequestException` **incluye la URL completa con
  `apiKey=…`** (verificado con una conexión local fallida: la clave aparecía
  en el texto). La app muestra ese mensaje con `st.error` en la pestaña 🛒:
  la clave podía quedar en pantalla (capturas, grabaciones).
- **Lo que NO estaba mal**: `.streamlit/secrets.toml` está ignorado por Git
  (`.gitignore`), la clave no se escribe en el registro ni se imprime en
  ningún otro sitio, y no hay claves en el código.
- **Arreglo**: `datos._redactar_secretos` tapa el propio secreto y cualquier
  `apiKey=…` en los mensajes derivados de excepción o de respuesta.
- **Aceptación**: con una excepción que contenga la clave, el `ValueError`
  resultante no la contiene; igual con un cuerpo de respuesta que la cite.

### F2-2 · Escritura no atómica (alto) — CORREGIDO

- **Evidencia**: `guardar_registro_picks` escribe con `to_csv` directo sobre
  `data/registro_picks.csv` (irremplazable). Un corte a mitad de escritura
  (crash, disco lleno, Ctrl+C) trunca o corrompe el archivo entero.
- **Arreglo**: archivo temporal en la misma carpeta + `os.replace` (atómico
  en el mismo sistema de archivos) + limpieza del temporal si algo falla.
- **Aceptación**: un fallo simulado de escritura deja el original intacto y
  sin `.tmp`; la captura normal no deja temporales.

### F2-3 · Sin validación estructural (alto) — CORREGIDO

- **Evidencia**: nada detecta ids duplicados, filas incompletas ni valores
  imposibles (probabilidad fuera de [0,1], cuota 0 o infinita, `edge`/`ev`
  no finitos). `unir_registro_fiel` deduplica en silencio: si el archivo en
  disco tuviera duplicados, la siguiente captura **reescribiría el archivo
  sin las filas repetidas** (pérdida silenciosa).
- **Arreglo**: `datos.validar_registro_picks` (errores bloquean; avisos
  informan; vacíos legítimos no son problema — no se inventa nada) +
  `capturar_registro_picks` se niega a escribir si el archivo en disco o las
  filas nuevas traen errores + aviso visible en la app.
- **Aceptación**: el registro real actual pasa limpio (verificado: 50 filas,
  0 duplicados, 0 valores fuera de rango); los casos corruptos sintéticos se
  detectan uno a uno; la captura rechaza errores sin tocar el archivo.

### F2-4 · Sello de versión incompleto (medio) — CORREGIDO

- **Evidencia**: la captura sella `srs-v2+cal-f4-1`, pero el EV congelado
  viene del motor `ev-f5-1` (app.py línea ~1241). El sello no lo dice.
- **Arreglo**: constante `VERSION_REGISTRO` =
  `srs-v2+cal-f4-1+ev-f5-1` para capturas nuevas; las filas viejas conservan
  su sello; la app muestra las versiones presentes en el registro.
- **Aceptación**: captura nueva sella los tres componentes; el histórico no
  se toca.

### F2-5 · `p_push` no congelada (medio) — CORREGIDO

- **Evidencia**: el registro guarda el EV (que depende de la probabilidad de
  push) pero no la probabilidad de push: el EV congelado no es auditable sin
  volver a ejecutar el estimador.
- **Arreglo**: columna nueva `p_push` (al final del esquema; los archivos
  viejos cargan igual, con la celda vacía — compatible) y la app la muestra
  en la tabla del registro fiel.
- **Aceptación**: ida y vuelta por CSV; filas sin dato quedan vacías; un CSV
  sin la columna sigue cargando.

### F2-6 · Etiqueta «Reconstruido» en pendientes (medio) — CORREGIDO

- **Evidencia**: en «La jornada, pick a pick» los picks pendientes salen como
  «🧮 Reconstruido» aunque todavía no tengan resultado; el texto no dice
  explícitamente que lo reconstruido NO es evidencia prospectiva.
- **Arreglo**: pendientes → «🧾 Línea de hoy» (procedencia de la fila: la
  versión congelada, si existe, está en el registro fiel); texto reforzado
  («solo lo congelado es evidencia prospectiva»).
- **Aceptación**: la tabla muestra la etiqueta correcta según `jugado`.

### F2-7 · Coherencia de la terna sin alarma (bajo) — CORREGIDO

- **Evidencia**: `motor_ev` garantiza por construcción que
  p_ganar+p_perder+p_push = 1 (probado), pero no hay verificación explícita
  antes de congelar; una regresión futura podría pasar desapercibida.
- **Arreglo**: `motor_ev.problemas_coherencia` (suma, rangos y coherencia con
  `p_estimada`) + alarma en la app que bloquea la captura si algo no cuadra.
- **Aceptación**: ternas coherentes pasan; cada violación se detecta.

### F2-8 · Temporada/semana vacías (bajo) — CORREGIDO

- **Evidencia**: `registro_desde_picks` hace `astype(int)`: un vacío lanzaría
  un error de conversión de pandas en vez de un mensaje claro.
- **Arreglo**: `ValueError` en español explicando que falta el dato.
- **Aceptación**: mensaje claro; sin filas inventadas.

### F2-9 · La suite no bloquea la red (bajo) — CORREGIDO

- **Evidencia**: las pruebas usan mocks (no tocan la red hoy), pero nada lo
  garantiza si alguien añade una prueba descuidada.
- **Arreglo**: guardia de sockets en `tests/__init__.py` (mismo patrón que
  `lab/evaluacion.GuardiaRed`): cualquier conexión falla con mensaje claro.
- **Aceptación**: la suite completa (143 pruebas) pasa con la guardia activa.

## Mejoras futuras (documentadas, no bloquean F2)

- **F2-10**: el resultado del registro fiel se deriva con el marcador actual
  de nflverse (determinista, con la línea congelada). Si la fuente revisara
  un marcador años después, el resultado derivado seguiría el cambio. Congelar
  el marcador al resolverse exigiría escrituras fuera de la emisión: se deja
  como está (la fuente es el dato oficial) y se documenta.
- **F2-11**: `capturado_en` usa la hora local sin zona; suficiente para
  auditar «¿cuándo se congeló?», pero un sello UTC sería más estricto.
- **F2-12**: los bloques de pestaña de la app no tienen pruebas directas (no
  son importables sin Streamlit); se cubren por extracción AST donde es
  razonable y por verificación visual del render.
