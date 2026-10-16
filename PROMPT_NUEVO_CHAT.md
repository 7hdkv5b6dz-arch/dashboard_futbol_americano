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
públicos y reales de nflverse. Hoy tiene 7 pestañas (🎯 Picks del modelo ·
📈 ATS por equipo · 🎲 Totales y clima · 🧮 Números clave · 💰 Mercado y vig ·
🛒 Precios entre casas · 📊 Temporadas) y un **modelo de pronósticos
walk-forward** (estilo SRS, sin mirar el futuro) cuyo historial se muestra tal
cual: ~50% ATS y ROI ligeramente negativo. La pestaña 🛒 compara el vig entre
casas con The Odds API (ya hay clave gratuita guardada en el equipo, en
`.streamlit/secrets.toml`, que **NUNCA** se sube). **Enfoque 100% honesto**: se
dan picks, pero sin prometer ganancias y con avisos de juego responsable; los
resultados malos se enseñan sin maquillar. 🔞 +18.

## 🎯 LA MISIÓN — el usuario quiere ESTO

El foco del proyecto ahora son **los picks** (mucho más completos) y una
**auditoría de los picks emitidos**. Dos tareas, en este orden:

### 1) Ampliar los picks del modelo (muchos más mercados)

Hoy solo hay picks de **spread** y **totales**. Añadir:

- **Moneyline (ML)**: ganador del partido con su cuota. Verifica primero qué
  trae `data/nfl_games.csv` en 2026 (p. ej. `home_moneyline`/`away_moneyline`);
  si no hay cuota real histórica, derívala del pronóstico de margen y dilo
  claro («cuota estimada», no real).
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

⚠️ **Feasibility ANTES de codificar (esto es serio, no un detalle):**

- Las **líneas reales de props** casi seguro NO están en el **plan gratuito**
  de The Odds API; además los props se piden **por partido** (cada consulta
  gasta créditos y la cuota gratis de 500/mes se agota rápido). **Verifica cómo
  está el plan en 2026** y propón opciones: (a) plan de pago, (b) otro
  proveedor con plan gratis, (c) **proyección del modelo sin cuota**,
  etiquetada como «sin línea de mercado: es la previsión del modelo, no un
  pick con valor comprobable».
- **Prohibido inventar cuotas.** Un prop sin línea real NO es una apuesta: es
  una proyección, y se marca así en la interfaz.
- Los datos de jugadores salen de **nflverse** (releases tipo `player_stats`,
  `players`, `rosters`): **inspecciona los CSV reales** antes de asumir
  formatos y añade la descarga a `datos.py` con caché local, igual que las
  demás fuentes.

### 2) Registro y auditoría de TODOS los picks (pestaña nueva)

Una pestaña dedicada, **solo de apuestas**, que responda clarísimo a:
¿cuántos picks ha dado la app?, ¿cuántos pegaron y cuántos no?, ¿qué % de
acierto tiene?

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
  2. `.venv/bin/python -m unittest discover -s tests -t .` (hoy pasan 38;
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

Hay **6 archivos modificados sin commitear** (el trabajo del 16/10, pestaña
🛒): `app.py`, `datos.py`, `tests/test_datos.py`, `README.md`, `CONTEXTO.md`
y `PROMPT_NUEVO_CHAT.md`. **Recuérdale al usuario commitearlos primero** en
GitHub Desktop para partir de una base limpia (mensaje sugerido: «Nueva
pestaña 🛒 Precios entre casas con The Odds API»).

## Estado actual

El detalle está en `CONTEXTO.md` (sección "Estado actual"). En resumen: app
**verificada** (38/38 tests, AppTest sin excepciones, Lighthouse 1.00), 7
pestañas, publicación en Streamlit Cloud **en pausa por decisión del usuario**
(16/10/2026). La pestaña 🛒 ya se verificó **en vivo** con la clave real (9
casas, vig medio 4.5% → 2.6% con el mejor precio). La clave vive en
`.streamlit/secrets.toml` (no se sube nunca).

## Pendientes (backlog)

- [ ] **LA MISIÓN de arriba** (picks ampliados + registro/auditoría):
      es la prioridad actual.
- [ ] Publicar en **Streamlit Community Cloud** (en pausa por ahora; repo ya
      subido, pasos en el README).
- [ ] Comparar **líneas de apertura vs. cierre** (necesita otra fuente).
- [x] Comparar **precios entre casas** → pestaña 🛒 con The Odds API.
- [ ] Gráficas de **rachas** y diferencia de puntos por equipo.

## Qué necesito de ti

Antes de escribir código:

1. Lee `CONTEXTO.md` y `README.md` completos y **dime en dos líneas qué hace
   la app y cuáles son las decisiones técnicas más importantes**.
2. **Investiga la viabilidad de los props** (plan de The Odds API en 2026 y
   fuentes de stats de jugadores en nflverse) y cuéntame las opciones con pros
   y contras ANTES de programar.
3. Propón un plan corto y por pasos para LA MISIÓN: qué modelo de jugador,
   qué pestaña nueva (o sección), cómo se calcula el «¿pegó?» y el %.
4. Trabaja paso a paso, verifica con lo de arriba y avísame de cualquier
   riesgo antes de romper algo.

---

## Nota para el humano (no pegar en el chat)

- Si el chat nuevo es en OpenCode: basta con pegar el bloque de arriba como
  primer mensaje, con la sesión abierta en la carpeta del proyecto.
- Si es otro agente sin acceso a archivos, adjúntale además `CONTEXTO.md` y
  `README.md`.
