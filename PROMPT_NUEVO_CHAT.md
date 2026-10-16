# 📨 Prompt listo para pegar en un chat nuevo

Copia todo lo que hay entre las líneas y pégalo como **primer mensaje** en un
chat nuevo (en OpenCode, otro agente o cualquier IA). Así la sesión nueva
entiende el proyecto sin que le expliques nada más.

---

Hola. Vas a continuar un proyecto que ya existe. **Antes de tocar nada, lee
completos estos dos archivos** (están en la carpeta del proyecto):

1. `CONTEXTO.md` — memoria del proyecto: qué es, decisiones técnicas que NO se
   deben romper, guía de diseño, estado actual y backlog.
2. `README.md` — qué hace la app, cómo se corre y cómo se publica.

**Carpeta del proyecto:**
`/Users/juanlu/Documents/Proyecto predeterminado/dashboard_futbol_americano`

**Repositorio:**
https://github.com/7hdkv5b6dz-arch/dashboard_futbol_americano

## Qué es el proyecto (resumen rápido)

Dashboard en **Streamlit** de **análisis de apuestas de la NFL** con datos
públicos y reales de nflverse. Hoy tiene 8 pestañas (🎯 Picks del modelo ·
📋 Registro de picks · 📈 ATS por equipo · 🎲 Totales y clima · 🧮 Números
clave · 💰 Mercado y vig · 🛒 Precios entre casas · 📊 Temporadas) y un
**modelo de pronósticos walk-forward** (estilo SRS, sin mirar el futuro) cuyo
historial se muestra tal cual: ~50.7% ATS con ROI ≈ −1.4%, ML 37.3% de
acierto y ROI −4.8% (modelo **srs-v2**). La pestaña **📋 Registro de picks** audita todos los picks (¿pegó o
no?, % de acierto y ROI por mercado), incluye el **registro fiel** (📌
congelar los picks con su línea/cuota del momento — inmutable) y la **calidad
de las probabilidades** (Brier, Log Loss y curva de calibración vs. el mercado
sin vig). La pestaña 🛒 compara el vig entre casas con The Odds API (ya hay
clave gratuita guardada en el equipo, en `.streamlit/secrets.toml`, que
**NUNCA** se sube). **Enfoque 100% honesto**: se dan picks, pero sin prometer
ganancias y con avisos de juego responsable; los resultados malos se enseñan
sin maquillar. 🔞 +18.

**Hoy (16/10/2026) el mercado es el listón y el modelo NO lo bate:** Brier
modelo/mercado → spread 0.2607/0.2501, total 0.2596/0.2501, ML 0.2254/0.2117;
en picks sigue sobreconfiado (en ML, todos los tramos dicen 11–16 pp más de lo
que pega). El **Bloque 3** acaba de subir la calibración (srs-v2: rigidez 8,
validada en holdout); el «valor esperado» serio sigue pendiente — eso es el
**Bloque 4**.

## 🎯 LA MISIÓN — el usuario quiere ESTO

El objetivo: convertir la app en un **sistema cuantitativo honesto** — calidad
predictiva real, probabilidades calibradas y edge con evidencia, sin humo. La
auditoría + línea base ya están hechas; el plan va por bloques:

> ✅ **HECHO — Auditoría (16/10/2026)**: revisión completa del código, línea
> base reproducible (`base_actual.py` en el laboratorio, fuera del repo) y
> diagnóstico P1–P8 (registro no congelado, probabilidades miscalibradas,
> compresión, sesgo underdog, σ sin total, micro-fuga del σ…).
>
> ✅ **HECHO — Bloque 1+2 (16/10/2026)**: **registro fiel** (📌 congelar en 📋:
> solo-añadir, dedupe por id, resultado con la línea CONGELADA, sin cuota no
> hay EV inventado; los viejos van como 🧮 Reconstruido) + **métricas de
> probabilidad** (Brier/LogLoss/calibración vs mercado en 📋) + **fix de la
> micro-fuga del σ** (congelado al empezar cada jornada + `sigma_total_modelo`
> + `sigma_actual()` para la pendiente). 60 tests (62 con el Bloque 3); AppTest probando el botón
> real contra un registro temporal; Lighthouse 1.00.
>
> ✅ **HECHO — Bloque 3 (16/10/2026) — modelo srs-v2**: comparación de
> ventana × rigidez + σ con protocolo fijado ANTES (selección 2006–2017;
> holdout 2018–2025 evaluado UNA vez). Instrumento corregido tras detectar
> que «ventana=1» ganaba solo por NO pronosticar las semanas 1–10 (mismo
> conjunto de partidos para todas; sin pronóstico = moneda al aire; cobertura
> ≥ 98% obligatoria). Ganó **rigidez 8** (ventana 2 y σ 500 se quedan;
> `VERSION_MODELO = "srs-v2"`): Δ Brier medio −0.0022, IC95 % [−0.0029,
> −0.0014], mejora en 8/8 temporadas del holdout, ROI de picks sin alarma,
> AppTest 0 excepciones. El modelo sigue sin batir al mercado.
>
> ⏭️ **LO SIGUIENTE (en orden)**:
> 1. **Bloque 4 — filtros/EV**: dos objetivos SEPARADOS (probabilidad alta vs.
>    EV+ con break-even 1/d, push-aware, sin-vig documentado); permitir **cero
>    picks** si no hay ventaja.
> 2. **Bloque 5 — UI final por pick**: mercado/selección, línea+cuota real,
>    prob. estimada, break-even, EV, edge, incertidumbre (muestra), motivos,
>    hora y versión del modelo; 4 estados (prob. alta / EV+ / ambos / sin
>    ventaja). Nunca «seguro»/«garantizado».
> 3. Después: **Fase 2/3** (props de jugadores + líneas reales bajo demanda).
>    (Opcional futuro: explorar rigidez 16/32 — el ganador quedó en el borde
>    de la rejilla; recordar que más compresión = más «eco» del mercado.)
>
> 📏 **Números de la línea base (srs-v2, 16/10/2026)** (reproducibles con el
> laboratorio): spread 2.0 → n=3230, 50.7%, ROI −1.4% (t=−0.83); total 2.0 →
> n=3207, 51.4%, −0.1% (t=−0.04); ML 4pp → n=3858, 37.3%, −4.8% (t=−2.09; más
> underdogs). Brier (todos los partidos desde 2006): modelo
> 0.2607/0.2596/0.2254 vs mercado 0.2501/0.2501/0.2117 (spread/total/ML). El
> mercado sin vig calibra ±3 pp: es el rival y hoy gana en los tres mercados.
> Escalera de edge invertida en ML (15+ pp → 33.7% de acierto). Cuotas: una
> sola línea por partido, sin open/close → **CLV imposible** con los datos
> actuales (documentado).

### 1) Ampliar los picks del modelo (muchos más mercados)

Hoy hay spread, totales y ✅ **moneyline**. Falta lo grande: los **props**, y
todo lo del plan de bloques de arriba.

- ✅ **Moneyline (ML)** — HECHO (16/10/2026): probabilidad del modelo desde el
  margen (normal con σ walk-forward ≈ 13.4, congelado por jornada) contra la
  cuota real del mercado sin *vig*; umbral en puntos de probabilidad (defecto
  4). Funciones: `datos.probabilidades_ml` y `datos.evaluar_picks_ml`.
  Resultado sin maquillar (srs-v2): **37.3 % de acierto, ROI −4.8 %** desde
  2006 (mayormente underdogs).
- **Props de jugadores** (todo walk-forward, sin mirar el futuro, y con
  backtest honesto por mercado):
  - **Anytime TD**: ¿anota el jugador? (RB/WR/TE; QB si corre).
  - **Yardas por tierra** (rushing yards).
  - **Pases de touchdown** (passing TDs).
  - **Yardas de pase del QB por aire** (passing yards).
  - *Extra si da tiempo:* recepciones y yardas por recepción.
- Un modelo de jugador razonable: medias por partido con ventana móvil y
  encogimiento para muestras pequeñas, Poisson para conteos (TD)… mismo
  estándar que el modelo actual: rápido, incremental y probado.

⚠️ **Viabilidad YA verificada en vivo (16/10/2026) — parte de aquí:**

- ✅ **El plan gratuito SÍ incluye props de jugadores en 2026**: prueba real de
  `player_pass_tds` del HOU@JAX (6 casas, C.J. Stroud, Trevor Lawrence…),
  costó **1 crédito**.
- 💰 **Costes** (presupuesto hoy: **484 créditos**): los props van por el
  endpoint **por partido** → `mercados × regiones` créditos por partido
  (p. ej. 3 mercados × 1 partido = 3). `/sports` y `/events` son **gratis**;
  las respuestas vacías **no cuestan**. Una pasada de 4 mercados × 14 partidos
  = 56 créditos (≈ 8 pasadas/mes): **diseña el uso con cuidado** (pocos
  mercados, caché larga, o bajo demanda por partido).
- 🧮 Mercados de props disponibles (catálogo oficial): `player_anytime_td`,
  `player_pass_tds`, `player_pass_yds`, `player_rush_yds`, `player_rush_tds`,
  `player_receptions`, `player_reception_yds`, `player_reception_tds`,
  `player_pass_interceptions`… (cubre todo lo que pidió el usuario).
- 📊 Stats de jugadores: release **nflverse `stats_player`** →
  `stats_player_week_AAAA.csv` (2026 ya existe, se actualiza semanal). Columnas
  clave verificadas: `player_display_name`, `position`, `opponent_team`,
  `passing_yards`, `passing_tds`, `passing_air_yards`, `attempts`,
  `completions`, `carries`, `rushing_yards`, `rushing_tds`, `receptions`,
  `targets`, `receiving_yards`, `receiving_tds`. Además `players.csv` y
  `roster_2026.csv` (nombres, posición, equipo) en el mismo repo.
- 🏈 **Moneyline**: `nfl_games.csv` ya trae `home_moneyline`/`away_moneyline`
  (~100 % desde 2007; la jornada en curso también). La cobertura parcial de
  2026 es solo porque los partidos lejanos aún no tienen cuota publicada.
- **Prohibido inventar cuotas.** Un prop sin línea real se marca como
  **proyección**, nunca como apuesta con valor.

### 2) Registro y auditoría de TODOS los picks — ✅ HECHA (+ registro fiel)

Una pestaña dedicada, **solo de apuestas** (📋 Registro de picks, con el estado
de cada pick, marcador, % de acierto y ROI por mercado), que responde
clarísimo a: ¿cuántos picks ha dado la app?, ¿cuántos pegaron y cuántos no?,
¿qué % de acierto tiene? **Falta integrar los props cuando existan.**

- ✅ **Registro fiel (16/10/2026)**: botón **«📌 Congelar»** que guarda los
  picks pendientes con su línea/cuota/probabilidad del momento en
  `data/registro_picks.csv` (solo-añadir; resultado derivado al leer con la
  línea congelada; sin cuota → sin EV inventado). Los picks anteriores van
  marcados **🧮 Reconstruido**. El CSV **SÍ se sube** (no está en
  `.gitignore`): es la memoria del proyecto.
- ✅ **Calidad de probabilidades (16/10/2026)**: tabla Brier/Log Loss + curva
  de calibración (modelo vs mercado sin vig, con selector de mercado).

- **Semana en curso (vista por defecto)**: todos los picks de la jornada
  actual (spread, total, ML y props), cada uno con su estado —
  **Pendiente · Pegó · No pegó · Push** — más el resumen: emitidos, resueltos,
  pendientes, marcador (p. ej. 7–4), **% de aciertos** y ROI cuando haya cuota.
- **Acumulado**: temporada en curso e **histórico completo** (el modelo ya es
  walk-forward, así que el historial de picks se puede reconstruir entero).
  Por mercado (spread / total / ML / cada prop): cantidad, aciertos, % y ROI.
  Con filtros por semana, equipo y mercado.
- El «¿pegó?» sale de los **resultados reales** de nflverse: al pulsar
  «🔄 Actualizar líneas» con la jornada ya jugada, los pendientes se resuelven
  (o los resuelve el modelo sin mirar el futuro, con cuidado de no usar
  información futura para picks pasados).
- Nada maquillado: si el % baja, se enseña igual. El valor didáctico es ver
  que batir al mercado es dificilísimo.

## Cómo se corre

```sh
cd "/Users/juanlu/Documents/Proyecto predeterminado/dashboard_futbol_americano"
source .venv/bin/activate
streamlit run app.py
```

Se abre en `http://localhost:8501`. No se usa Thonny (es app web).
⚠️ Si editas `datos.py`, **reinicia el servidor** (Ctrl+C y volver a lanzar):
Streamlit recarga `app.py` solo, pero el módulo `datos` se queda viejo en
memoria y verás un `AttributeError`.

## Reglas del proyecto (obligatorias)

- **Código y textos en español**, siguiendo el estilo ya existente.
- Usa el entorno virtual `.venv` (ya tiene todo instalado).
- **NO subas** `.venv/`, los CSV descargados de `data/` ni
  `.streamlit/secrets.toml` (todos en `.gitignore`; la clave de The Odds API
  es privada del usuario).
- **Enfoque honesto**: picks sí, humo no. Nunca ocultes malos resultados,
  nunca prometas ganancias, mantén los avisos +18 / juego responsable.
- **Props sin línea real = proyección etiquetada como tal** (jamás como pick
  con valor), y **nunca cuotas inventadas**.
- **Verificación antes de dar algo por bueno:**
  1. `python -m py_compile app.py datos.py`
  2. `.venv/bin/python -m unittest discover -s tests -t .` (hoy pasan 62;
     añade pruebas de todo lo nuevo: modelo de props, cálculo de «¿pegó?»,
     % de aciertos, sin fuga de futuro también en props, y mantén verdes las
     de σ congelado por jornada, Brier/LogLoss/calibración y registro fiel).
  3. AppTest de Streamlit sin excepciones:
     `from streamlit.testing.v1 import AppTest` y
     `AppTest.from_file("app.py", default_timeout=180).run()`.
     ⚠️ Con `.streamlit/secrets.toml` presente (hoy SÍ existe), AppTest y la
     pestaña 🛒 hacen consultas reales a The Odds API con caché fría (2–4
     créditos): para verificar sin gastar, mueve el archivo un momento o usa
     `mock`.
  4. Si tocas la interfaz: Lighthouse con **accesibilidad ≥ 0.95** (hoy 1.00)
     y capturas de pantalla (si la ventana del navegador lo permite).
- Al terminar, recuérdale al usuario **commitear con GitHub Desktop** (él no
  usa la terminal para git). El git embebido está en
  `/Applications/GitHub Desktop.app/Contents/Resources/app/git/bin/git`.
- **Regla permanente del usuario**: al terminar cada bloque de trabajo,
  actualiza `CONTEXTO.md` y este `PROMPT_NUEVO_CHAT.md` con el estado real
  («siempre haz otro prompt para otro chat»).

## ⚠️ Al empezar: commit pendiente del usuario

El Bloque 1+2 ya está commiteado (`97f461c`, con 46 picks srs-v1 congelados).
El 16/10/2026 (10:59) el usuario **pulsó «📌 Congelar» con el srs-v2 activo**:
el registro pasó a **50 picks** (46 srs-v1 intactos + 4 nuevos srs-v2; los
valores congelados no cambiaron — verificado). **Pendiente de commitear
(16/10/2026, Bloque 3)**: `datos.py` (rigidez 2.0 → 8.0 y
`VERSION_MODELO = "srs-v2"`), `tests/test_datos.py` (62 tests: +2 del modelo
validado), `data/registro_picks.csv` (los 4 picks nuevos), `CONTEXTO.md`,
`PROMPT_NUEVO_CHAT.md` y `README.md`. **Recuérdale al usuario commitear con
GitHub Desktop** (mensaje sugerido: «Auditoría Bloque 3: modelo srs-v2
(rigidez 8, validada con holdout)»).

## Estado actual

El detalle está en `CONTEXTO.md` (sección "Estado actual"). En resumen: app
**verificada** (62/62 tests, AppTest sin excepciones —incluido el botón 📌 de
congelar contra un registro temporal, también con srs-v2—, Lighthouse 1.00,
consola sin errores), **8 pestañas**, con el **registro fiel** y la **calidad
de probabilidades** (Brier/LogLoss/calibración) en 📋, y el modelo **srs-v2**
(rigidez 8, validada con holdout en el Bloque 3) ya activo. Series de
apuestas: ~50.7% ATS (ROI ≈ −1.4%), totales ~51.4% (ROI ≈ −0.1%) y ML 37.3%
(ROI −4.8%) — sin maquillar. La publicación en Streamlit Cloud sigue **en
pausa por decisión del usuario** (16/10/2026). La clave de The Odds API vive
en `.streamlit/secrets.toml` (no se sube nunca); quedan ~484 créditos y la
auditoría no gastó ninguno.

## Pendientes (backlog)

- [ ] **LA MISIÓN** — auditoría en curso: ✅ auditoría+línea base, ✅ Bloque
      1+2 (registro fiel + métricas + σ), ✅ Bloque 3 (holdout → srs-v2).
      **Siguiente: Bloque 4 (filtros/EV), Bloque 5 (UI final por pick)**;
      después Fase 2/3 (props de jugadores + líneas reales).
- [ ] Publicar en **Streamlit Community Cloud** (en pausa por ahora; repo ya
      subido, pasos en el README).
- [ ] Comparar **líneas de apertura vs. cierre** (necesita otra fuente).
- [x] Comparar **precios entre casas** → pestaña 🛒 con The Odds API.
- [ ] Gráficas de **rachas** y diferencia de puntos por equipo.

## Qué necesito de ti

Antes de escribir código:

1. Lee `CONTEXTO.md` y `README.md` completos y **dime en dos líneas qué hace
   la app y cuáles son las decisiones técnicas más importantes**.
2. El plan de la auditoría ya está decidido (arriba): Bloque 3 HECHO (srs-v2);
   lo siguiente es el **Bloque 4 — filtros/EV**, luego el Bloque 5. Confírmame
   el plan con tus palabras antes de tocar nada.
3. Reglas no negociables: **sin fuga de datos** (los picks solo usan lo
   disponible al emitirse; sin resultados futuros), **sin tuning sobre las
   temporadas de evaluación**, dos objetivos separados (probabilidad alta vs.
   EV+ con break-even 1/d, push-aware) y **cero promesas**.
4. Trabaja paso a paso, verifica con lo de arriba y avísame de cualquier
   riesgo antes de romper algo. Si algo no funciona, no se queda.

---

## Nota para el humano (no pegar en el chat)

- Si el chat nuevo es en OpenCode: basta con pegar el bloque de arriba como
  primer mensaje, con la sesión abierta en la carpeta del proyecto.
- Si es otro agente sin acceso a archivos, adjúntale además `CONTEXTO.md` y
  `README.md`.
