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
reales de nflverse. Tiene 6 pestañas: 🎯 Picks del modelo · 📈 ATS por equipo ·
🎲 Totales y clima · 🧮 Números clave · 💰 Mercado y vig · 📊 Temporadas
(comparadas 2020–hoy). Incluye un **modelo de pronósticos *walk-forward***
(estilo SRS, sin mirar el futuro) cuyo historial se muestra tal cual: ~50% ATS
y ROI ligeramente negativo. El enfoque es
**honesto**: se pueden añadir *picks*, pero sin prometer ganancias y con avisos
de juego responsable.

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
- **NO subas** `.venv/` ni los CSV descargados de `data/` (están en
  `.gitignore`).
- **Enfoque honesto**: los *picks* están permitidos, pero nunca ocultes malos
  resultados, nunca prometas ganancias y mantén los avisos de juego responsable.
- **Verificación antes de dar algo por bueno:**
  1. `python -m py_compile app.py datos.py`
  2. `.venv/bin/python -m unittest discover -s tests -t .` (deben pasar los 29)
  3. AppTest de Streamlit sin excepciones:
     `from streamlit.testing.v1 import AppTest` y
     `AppTest.from_file("app.py", default_timeout=180).run()`.
  4. Si tocas la interfaz: Lighthouse con **accesibilidad ≥ 0.95** (hoy está
     en 1.00) y capturas de pantalla en escritorio y móvil.
- Al terminar, recuérdale al usuario **commitear con GitHub Desktop** (él no
  usa la terminal para git). El git embebido de GitHub Desktop está en
  `/Applications/GitHub Desktop.app/Contents/Resources/app/git/bin/git`.
- **Regla permanente del usuario**: al terminar cada bloque de trabajo,
  actualiza `CONTEXTO.md` y este `PROMPT_NUEVO_CHAT.md` con el estado real
  («siempre haz otro prompt para otro chat»).

## Estado actual

Todo lo del estado actual está en `CONTEXTO.md` (sección "Estado actual").
En resumen: la app está **terminada y verificada** (29/29 tests, AppTest sin
excepciones, Lighthouse 1.00), con 6 pestañas, y lista para publicar en
Streamlit Community Cloud (los pasos están en el README; lo único pendiente
es iniciar sesión en share.streamlit.io).

## Pendientes (backlog)

Están en `CONTEXTO.md`, sección "Backlog". Los principales:

- [ ] Publicar en **Streamlit Community Cloud** (repo ya subido; falta solo el login).
- [ ] Comparar **líneas de apertura vs. cierre** (necesita otra fuente).
- [ ] Comparar **precios entre casas** (necesita otra fuente).
- [ ] Gráficas de **rachas** y diferencia de puntos por equipo.

## Qué necesito de ti

Antes de escribir código:

1. Lee `CONTEXTO.md` y `README.md` completos y **dime en dos líneas qué hace
   la app y cuáles son las decisiones técnicas más importantes**, para que yo
   compruebe que lo entendiste.
2. Propón un plan corto para la tarea que te pida después.
3. A partir de ahí, trabaja paso a paso, verifica con lo de arriba y avísame
   de cualquier riesgo antes de romper algo.

---

## Nota para el humano (no pegar en el chat)

- Si el chat nuevo es en OpenCode: basta con pegar el bloque de arriba como
  primer mensaje, con la sesión abierta en la carpeta del proyecto.
- Si es otro agente sin acceso a archivos, adjúntale además `CONTEXTO.md` y
  `README.md`.
