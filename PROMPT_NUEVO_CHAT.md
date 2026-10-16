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
historial se muestra tal cual: ~50% ATS, ML 42.3% de acierto y ROI negativo.
La pestaña **📋 Registro de picks** audita todos los picks (¿pegó o no?, % de
acierto y ROI por mercado). La pestaña 🛒 compara el vig entre
casas con The Odds API (ya hay clave gratuita guardada en el equipo, en
`.streamlit/secrets.toml`, que **NUNCA** se sube). **Enfoque 100% honesto**: se
dan picks, pero sin prometer ganancias y con avisos de juego responsable; los
resultados malos se enseñan sin maquillar. 🔞 +18.

## 🎯 LA MISIÓN — el usuario quiere ESTO

El foco del proyecto ahora son **los picks** (mucho más completos) y una
**auditoría de los picks emitidos**. Dos tareas, en este orden:

> ✅ **FASE 1 HECHA (16/10/2026)**: picks de **moneyline** + pestaña
> **📋 Registro de picks** (estado por pick, marcador, % de acierto y ROI por
> mercado, acumulado e histórico con filtros) funcionando y verificados
> (49 tests, AppTest sin excepciones). **Lo que queda de LA MISIÓN son los
> props de jugadores** (tarea 1b) y su integración en el registro.

### 1) Ampliar los picks del modelo (muchos más mercados)

Hoy hay spread, totales y ✅ **moneyline**. Falta lo grande: los **props**.

- ✅ **Moneyline (ML)** — HECHO (16/10/2026): probabilidad del modelo desde el
  margen (normal con sigma walk-forward ≈ 13.5) contra la cuota real del
  mercado sin *vig*; umbral en puntos de probabilidad (defecto 4). Funciones:
  `datos.probabilidades_ml` y `datos.evaluar_picks_ml`. Resultado sin
  maquillar: **42.3 % de acierto, ROI −5.2 %** desde 2006 (mayormente
  underdogs).
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

### 2) Registro y auditoría de TODOS los picks — ✅ HECHA para spread/total/ML

Una pestaña dedicada, **solo de apuestas** (📋 Registro de picks, con el estado
de cada pick, marcador, % de acierto y ROI por mercado), que responde
clarísimo a: ¿cuántos picks ha dado la app?, ¿cuántos pegaron y cuántos no?,
¿qué % de acierto tiene? **Falta integrar los props cuando existan.**

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
  2. `.venv/bin/python -m unittest discover -s tests -t .` (hoy pasan 49;
     añade pruebas de todo lo nuevo: modelo de props, cálculo de «¿pegó?»,
     % de aciertos, sin fuga de futuro también en props).
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

Hay cambios sin commitear (16/10/2026): pestaña **📋 Registro de picks +
picks de moneyline** en `app.py`, `datos.py`, `tests/test_datos.py`,
`README.md`, `CONTEXTO.md` y `PROMPT_NUEVO_CHAT.md` (si la pestaña 🛒 aún no
se ha commiteado, va todo junto en el mismo commit). **Recuérdale al usuario
commitear primero** en GitHub Desktop para partir de una base limpia (mensaje
sugerido: «Pestaña 📋 Registro de picks + picks de moneyline»).

## Estado actual

El detalle está en `CONTEXTO.md` (sección "Estado actual"). En resumen: app
**verificada** (49/49 tests, AppTest sin excepciones, Lighthouse 1.00), **8
pestañas** (nueva: 📋 Registro de picks con el estado real de cada pick y %
de acierto/ROI por mercado), publicación en Streamlit Cloud **en pausa por
decisión del usuario** (16/10/2026). La clave de The Odds API vive en
`.streamlit/secrets.toml` (no se sube nunca); quedan ~484 créditos.

## Pendientes (backlog)

- [ ] **LA MISIÓN de arriba** — ✅ Fase 1 (ML + registro). Prioridad actual:
      **props de jugadores** (Fase 2: modelo walk-forward de jugadores) y
      **líneas reales bajo demanda por partido** (Fase 3) + su registro.
- [ ] Publicar en **Streamlit Community Cloud** (en pausa por ahora; repo ya
      subido, pasos en el README).
- [ ] Comparar **líneas de apertura vs. cierre** (necesita otra fuente).
- [x] Comparar **precios entre casas** → pestaña 🛒 con The Odds API.
- [ ] Gráficas de **rachas** y diferencia de puntos por equipo.

## Qué necesito de ti

Antes de escribir código:

1. Lee `CONTEXTO.md` y `README.md` completos y **dime en dos líneas qué hace
   la app y cuáles son las decisiones técnicas más importantes**.
2. El enfoque de props **ya está decidido** (16/10/2026 por el usuario):
   **líneas reales bajo demanda por partido** (1 crédito por mercado y partido)
   y **proyección del modelo** etiquetada como tal cuando no haya línea.
   Revisa los hallazgos de viabilidad de arriba y confírmame el plan.
3. Propón un plan corto y por pasos para los **props**: qué modelo de jugador,
   dónde vive en la UI (sección nueva o pestaña), cómo se registra el «¿pegó?»
   (solo con línea real) y qué se muestra cuando solo hay proyección.
4. Trabaja paso a paso, verifica con lo de arriba y avísame de cualquier
   riesgo antes de romper algo.

---

## Nota para el humano (no pegar en el chat)

- Si el chat nuevo es en OpenCode: basta con pegar el bloque de arriba como
  primer mensaje, con la sesión abierta en la carpeta del proyecto.
- Si es otro agente sin acceso a archivos, adjúntale además `CONTEXTO.md` y
  `README.md`.
