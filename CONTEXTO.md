# 📋 CONTEXTO DEL PROYECTO (léeme primero)

Este archivo existe para que **cualquier sesión nueva de IA** (sin memoria previa)
pueda continuar el proyecto sin perderse. Es la "memoria externa" del proyecto.

## Qué es

Dashboard web de **análisis de apuestas de la NFL** con datos públicos reales de
nflverse: mercado (*spread*, totales, *vig*), rendimiento ATS por equipo,
totales y clima, números clave y un **modelo de pronósticos *walk-forward***
cuyo historial completo se muestra **sin maquillar**.

**Enfoque honesto (no negociable):** la app SÍ emite *picks* del modelo, pero
enseña sus resultados reales — que son ~50% ATS y con ROI ligeramente negativo —
y hay avisos visibles de juego responsable. **Nada de promesas ni de "gana
dinero fácil": el mensaje es que el mercado es casi perfecto y la casa cobra
el *vig*.** 🔞 Solo para +18.

## Ubicación

- **Carpeta local:**
  `/Users/juanlu/Documents/Proyecto predeterminado/dashboard_futbol_americano`
- **Repositorio GitHub:**
  https://github.com/7hdkv5b6dz-arch/dashboard_futbol_americano

## Stack

- **Python 3.14** (en entorno virtual `.venv/`)
- **Streamlit** (la web) · **pandas** (datos) · **Plotly** (gráficas) · **requests** (descargas) · **NumPy** (modelo)

## Estructura de archivos

| Archivo | Qué es |
|---|---|
| `app.py` | La app de Streamlit (UI + gráficas), 8 pestañas / 23 gráficas |
| `datos.py` | Descarga, preparación, **modelo de pronósticos** (SRS walk-forward) y **precios entre casas** (The Odds API) |
| `tests/test_datos.py` | Pruebas básicas (38) de `datos.py` |
| `.streamlit/secrets.toml` | Clave de The Odds API (local, NO se sube; en `.gitignore`) |
| `data/nfl_games.csv` | Caché de partidos y líneas (se baja sola; NO se sube) |
| `data/equipos.csv` | Nombres y colores de equipos (NO se sube) |
| `data/partidos.csv` | Respaldo de ejemplo si no hay internet (sí se sube) |
| `requirements.txt` | Librerías (majors con tope para que la nube no rompa) |
| `.streamlit/config.toml` | Tema visual (oscuro) del dashboard |
| `README.md` | Instrucciones de uso y publicación |
| `PROMPT_NUEVO_CHAT.md` | Prompt listo para pegar en un chat nuevo (handoff) |
| `.gitignore` | Excluye `.venv/` y los CSV descargados |

## Cómo se corre

```sh
cd "/Users/juanlu/Documents/Proyecto predeterminado/dashboard_futbol_americano"
source .venv/bin/activate
streamlit run app.py
```

Se abre en `http://localhost:8501`. (No se corre en Thonny: es app web.)

> ⚠️ **Si editas `datos.py`, reinicia el servidor.** Streamlit recarga `app.py`
> solo, pero el módulo `datos` se queda viejo en memoria y el botón/la página
> dan `AttributeError: module 'datos' has no attribute ...`. Parar con `Ctrl+C`
> y volver a lanzar `streamlit run app.py`.

## Decisiones técnicas IMPORTANTES (no las rompas sin razón)

1. **Descargas con `requests`, NO con `urllib`.** El Python de macOS no trae
   certificados SSL; `requests` sí. Por eso se usa `requests`.
2. **Fuente de datos:** nflverse (GitHub releases). URLs en `datos.py`:
   - Juegos: `.../releases/download/schedules/games.csv`
   - Equipos: `.../releases/download/teams/teams_colors_logos.csv`
   - El botón **🔄 Actualizar líneas** de la barra lateral fuerza re-descarga,
     limpia la caché (`st.cache_data.clear()`) y muestra la fecha del CSV.
3. **Convención del spread** (`spread_line`):
   - `spread_line > 0` → **local favorito** → **visitante es underdog**
   - `spread_line < 0` → **local underdog**
   - `push` (empate contra la línea) → devuelve el dinero y **no cuenta** como
     apuesta en los cálculos (ni en ROI ni en % acierto).
4. **Primetime** = partido **NOCTURNO** (inicio ≥ 19:00, hora del Este). En
   `datos.py` hay correcciones verificadas contra los datos reales:
   - El `"09:00"` de 2000–2005 (lunes/jueves/sábados) en realidad era 21:00:
     nflverse perdió el AM/PM. Se corrige a 21:00.
   - 1999 no trae hora: se asume nocturno solo los lunes (eran MNF).
   - Thanksgiving de día (12:30/16:30) **NO** es primetime.
5. **Modelo de pronósticos (`datos.py`, clase `_ModeloPuntos`)**:
   - Estilo **SRS**: *rating* de ataque/defensa por equipo con un sistema
     lineal (ecuaciones normales **incrementales**: al añadir un partido solo
     se actualiza lo necesario; por eso es rápido: ~0.2 s para todo el histórico).
   - **Ventana móvil de 2 temporadas** (`ventana=2`), **rigidez (ridge) 2.0**
     y **mínimo 150 partidos** en el historial antes de emitir su primer
     pronóstico (`minimo_partidos=150`).
   - Estima **margen** (spread) y **total** con dos sistemas separados
     (ataque/defensa para el total).
   - **Walk-forward estricto: sin mirar el futuro.** Cada partido se pronostica
     solo con partidos ANTERIORES; hay un test que lo demuestra (cambiar el
     resultado del último partido no altera pronósticos anteriores).
   - `pronosticos_historicos()` (para el historial) y `pronosticos_futuros()`
     (jornada pendiente, solo partidos con línea publicada).
6. **Picks:** se emiten solo cuando |pronóstico − línea| ≥ **umbral de edge**
   (control en la app: 1.0–4.0, por defecto 2.0). Cuotas **reales** de nflverse
   desde 2006; antes se asume −110. Los picks usan la línea de cierre disponible.
7. **Datos de 2026+:** el calendario incluye partidos futuros SIN resultado;
   las columnas derivadas (`jugado`, flags ATS, `over`…) usan booleanos
   *nullable* y quedan `NA` donde no aplica (p. ej. `over` es `NA` en los
   `push` de total para que las medias no cuenten los empates).
8. **Estilo de código:** español, funciones con nombres descriptivos,
   comentarios en español. (El usuario viene de ejercicios tipo `S12_01`.)
9. **Verificación obligatoria antes de dar algo por bueno** (el usuario lo pide):
   - `python -m py_compile app.py datos.py`
   - `.venv/bin/python -m unittest discover -s tests -t .` (38/38 en verde)
   - **AppTest** de Streamlit sin excepciones:
     `AppTest.from_file("app.py", default_timeout=180).run()` (con
     `at.select_slider[0].set_value(...)` para probar umbrales).
     ⚠️ Si existe `.streamlit/secrets.toml` (hoy **sí**, la clave del usuario),
     AppTest y la pestaña 🛒 **consultan de verdad** The Odds API cuando la
     caché de 15 min está fría (2–4 créditos por consulta): para verificar sin
     gastar, mueve el archivo un momento o usa `mock`.
   - Cuando se toque UI: Lighthouse con accesibilidad ≥ 0.95 (hoy 1.00) y
     captura del cambio. Ojo: si el servidor llevaba abierto desde antes de
     tocar `datos.py`, reinícialo antes de verificar (ver «Cómo se corre»).
10. **Precios entre casas (The Odds API, pestaña 🛒):** funciones en `datos.py`
    (`cargar_precios_casas`, `parsear_precios_casas`, `analizar_precios_casas`).
    La clave se pega **en la propia pestaña** y se guarda en
    `.streamlit/secrets.toml` (local, **en `.gitignore`: jamás subirla**) y en
    `session_state`; `app.py` la busca con `clave_odds_api()`. La descarga va
    **cacheada 15 min** (`st.cache_data(ttl=900)`) + botón de refresco manual:
    cada descarga gasta **créditos** de la cuenta gratuita (1 región = 2
    créditos; la cuota es 500/mes). Sin clave, la pestaña muestra instrucciones
    y **NO descarga nada**. El análisis compara el **vig** de cada casa y cuánto
    se paga por $100 con la mejor vs. la peor línea (comprar precio reduce el
    vig pagado; **no crea edge**).
11. **Tema visual:** oscuro, definido en `.streamlit/config.toml`; los detalles
    (CSS, chips, tablas) están en `app.py`. Las gráficas se muestran con
    `theme=None` para conservar el estilo propio (si no, Streamlit las repinta).
12. **La pestaña de apuestas SÍ da picks, pero con transparencia total:**
    - Aviso visible en la pestaña 🎯 y nota de juego responsable en el pie
      (EE. UU. **1-800-522-4700** · España **900 200 225**).
    - Se muestra el historial completo walk-forward (ROI, acierto, banca):
      *spread* ~50% ATS con ROI ≈ −2% a −3.6% según umbral (mejor que
      apostar a ciegas al favorito, −5.4%, pero aún negativo); totales ~51%
      con ROI ≈ −0.7%.
    - Se enseña explícitamente que **más edge NO garantiza más acierto**.
    - Prohibido: prometer ganancias, ocultar resultados, "picks infalibles".

## 🎨 Guía de diseño (que cualquier IA lea esto antes de tocar la vista)

Tema: oscuro, tipo "noche de estadio". Lo fija `.streamlit/config.toml`.

### Paleta (no inventar colores fuera de esto)
| Uso | Color |
|---|---|
| Fondo | `#0B1220` |
| Tarjetas / barra lateral | `#151E2E` |
| Texto | `#E7EBF3` |
| Verde césped (principal) | `#00C46A` |
| Azul | `#4C9AFF` |
| Amarillo luna | `#F2C14E` |
| Coral | `#FF6B6B` |
| Lila | `#B48EFF` |
| Enlaces | `#8AE6B9` (contraste ya verificado) |

### Reglas de estilo
- **Toda gráfica** pasa por `estilo_grafica()` / `mostrar_grafica()` del
  `app.py`: fondo transparente, sin barra de herramientas, títulos y ejes en
  español. `st.plotly_chart` se llama con `theme=None` (si no, Streamlit
  repinta la figura y rompe la paleta).
- Números grandes → `st.metric(border=True)` con un `help=` que enseñe algo.
- Tablas → encabezados en español y `column_config` para formatos.
- Móvil: nada de anchos fijos (usar `width="stretch"`), las columnas de
  Streamlit se apilan solas y hay media queries en `ESTILO_CSS`.
- En gráficas Plotly con varios trazos, construir el `custom_data` a partir de
  un DataFrame (no listas sueltas) para que los tooltips no se rompan.

### Cómo pedirle diseño a una IA (funciona bien)
1. **Adjunta referencias**: 1–2 capturas de "así quiero que se vea" y, si hay,
   una de "así NO".
2. **Da los códigos exactos** (los de la tabla de arriba) y di qué NO tocar.
3. **Pide cambios pequeños y verificables** ("cambia la cabecera a X y muéstrame
   captura en escritorio y móvil"), no "hazlo bonito".
4. **Exige verificación**: que la IA compare antes/después con capturas y
   Lighthouse, y que deje escrito aquí lo que aprendió.
5. Las IAs nuevas deben **leer esta guía y CONTEXTO.md entero** antes de
   proponer cambios de diseño.

## Estado actual (hecho)

- ✅ Conexión a datos reales de nflverse (con caché local y respaldo sin internet).
- ✅ **Modelo walk-forward** de spread y totales (SRS) sin fuga de futuro,
  con historial completo desde 2006 y picks de la jornada pendiente.
- ✅ **ML + registro (16/10/2026)**: picks de **moneyline** (probabilidad del
  modelo desde el margen con sigma walk-forward ≈ 13.5; edge vs. probabilidad
  sin *vig* del mercado) y pestaña **📋 Registro de picks**: estado de cada
  pick (✅ Pegó / ❌ No pegó / ➖ Push / ⏳ Pendiente), marcador de la jornada,
  **% de acierto y ROI por mercado**, acumulado de la temporada 2026 y del
  histórico desde 2006, con filtros por temporada, equipo y mercado. Resultado
  honesto inicial: **ML 42.3 % de acierto y ROI −5.2 %** (3 861 picks desde
  2006) — el modelo tampoco le gana al mercado.
- ✅ **8 pestañas / 23 gráficas**: 🎯 Picks del modelo · 📋 Registro de picks ·
  📈 ATS por equipo · 🎲 Totales y clima · 🧮 Números clave · 💰 Mercado y vig ·
  🛒 Precios entre casas · 📊 Temporadas.
- ✅ Vista **📊 Temporadas comparadas (2020–hoy)** en una sola vista: puntos por
  partido, % de overs, % de favoritos cubriendo y ROI a ciegas año a año
  (la prueba del vig temporada a temporada).
- ✅ Pestaña **🛒 Precios entre casas (The Odds API)**: vig de cada casa y
  pago por $100 con la mejor vs. la peor línea. Necesita **clave gratuita
  propia** (se pega en la pestaña; sin clave solo muestra instrucciones).
- ✅ La clave del usuario ya está guardada en `.streamlit/secrets.toml`
  (16/10/2026) y la pestaña 🛒 queda **verificada en vivo**: consulta real con
  9 casas de EE. UU., vig medio 4.5% → **2.6% con el mejor precio**, consola
  del navegador sin errores y 0 excepciones.
- ✅ Mapa de calor ATS equipo × semana, ATS por tamaño de línea, totales por
  equipo y efecto del viento/temperatura.
- ✅ Botón **🔄 Actualizar líneas** con fecha de última descarga.
- ✅ **49 tests** en `tests/test_datos.py` (cuotas/vig, spread, push, totales,
  primetime 1999–2005, resumen por temporada, respaldo offline, **no fuga de
  futuro** del modelo, **precios entre casas** con `mock` y los nuevos: sigma
  walk-forward del margen, probabilidades y picks de **moneyline**, estado de
  los picks (¿pegó?/push/pendiente, incluido el empate en ML) y la aritmética
  del **registro** (% de acierto, ROI, pendientes)).
- ✅ Verificado con **AppTest** (0 excepciones, incluidos cambios de umbral;
  16/10/2026: 8 pestañas y el registro con 0 excepciones) y **Lighthouse con
  accesibilidad 1.00**; consola del navegador sin errores y captura de la
  pestaña 📋 tomada.
- ✅ README reescrito (enfoque apuestas + pasos de publicación) y CONTEXTO al día.
- ✅ Subido a GitHub. La publicación en **Streamlit Cloud queda EN PAUSA por
  decisión del usuario** (16/10/2026): el código y los pasos del README están
  listos para cuando quiera retomarla.

**Hallazgos honestos que la app muestra:** favoritos cubren ~48.7% y overs
~49.5% (el mercado es casi perfecto); *vig* del moneyline ~2.75%; apostar a
ciegas al favorito pierde ~5.4% por apuesta; los picks del modelo (~50% ATS,
ROI algo negativo) **no** son una máquina de ganar: muestran que batir al
mercado es dificilísimo. En primetime 2026 los underdogs ganaron ~62% (10/16)
vs ~35% en la temporada completa: buena lección de muestras pequeñas.

## Backlog (pendiente) — ideas para seguir optimizando

- [ ] **NUEVO FOCO (pedido del usuario, 16/10/2026) — LA MISIÓN actual:**
      detalle en `PROMPT_NUEVO_CHAT.md` (sección «LA MISIÓN»).
      - [x] **Fase 1 (16/10/2026): ML + pestaña 📋 Registro/auditoría de
        picks** (spread, totales y moneyline; 49 tests; AppTest 0 excepciones).
      - [ ] **Fase 2: props de jugadores** walk-forward (anytime TD, yardas por
        tierra, pases de TD, yardas de pase del QB, recepciones/yardas de
        recepción; ventana móvil + encogimiento, Poisson para los TDs).
      - [ ] **Fase 3: líneas reales de props** de The Odds API **bajo demanda
        por partido** (decisión del usuario, 16/10/2026), integradas al registro.
      ✅ **Viabilidad verificada en vivo (16/10/2026)**: el plan gratis **SÍ
      incluye props** (prueba real `player_pass_tds`, 1 crédito; 484
      restantes). Coste props = mercados × regiones por partido; `/sports` y
      `/events` gratis. Stats de jugadores: release nflverse `stats_player`
      (`stats_player_week_2026.csv` existe). ML real en `nfl_games.csv`
      (`home_moneyline`/`away_moneyline`, ~100 % desde 2007). Sin línea real,
      un prop se marca como **proyección**.
- [ ] Publicar gratis en **Streamlit Community Cloud** (link compartible).
      **EN PAUSA por decisión del usuario** (16/10/2026). Repo ya subido;
      pasos en `README.md` (sección "Publicar gratis").
- [ ] **Comparar líneas de apertura vs. cierre** (necesita otra fuente
      histórica multi-casa; candidata: dataset `flancast90/sportsbookreview-scraper`
      con open/close 2011–2021, una sola casa).
- [x] **Comparar precios entre casas** → pestaña 🛒 con The Odds API (gratis,
      500 créditos/mes; el mejor precio reduce el vig pagado).
- [x] **Comparar varias temporadas** en una sola vista (2020–2026)
      → pestaña 📊 Temporadas (2020–hoy).
- [ ] Gráficas de **rachas** y **diferencia de puntos** por equipo.
- [x] Mejorar el diseño/colores y hacerlo responsive.
- [x] Añadir pruebas (tests) básicas → 38 tests, incluido "sin fuga de futuro".
- [x] Verificar que `primetime` capture bien todos los casos.
      (Único pendiente: los jueves de 1999, que en la fuente no traen hora.)
- [x] Mapa de calor de aciertos por equipo/semana.
- [x] Picks del modelo con historial walk-forward.

## Reglas para la IA que continúe

- Mantén el **código y los textos en español** y el estilo existente.
- Usa el `.venv` (ya tiene streamlit, pandas, plotly, requests, numpy).
- **No subas** `.venv/` ni los CSV descargados (están en `.gitignore`).
- Se **pueden** añadir *picks* y funciones de análisis de apuestas, pero siempre
  con el **enfoque honesto**: mostrar resultados reales sin maquillar, avisos de
  juego responsable y cero promesas. Si un cambio "vende humo", no va.
- Tras cambios: **verifica** (py_compile + tests + AppTest + Lighthouse si toca
  UI) y recuérdale **commitear** con GitHub Desktop.
- **Al terminar cada bloque de trabajo, actualiza `PROMPT_NUEVO_CHAT.md**
  (regla del usuario: «siempre haz otro prompt para otro chat»): que refleje
  el estado real y los pendientes del momento.
- Para datos nuevos o dudas de la fuente, inspecciona `data/nfl_games.csv` real
  antes de asumir formatos; nflverse cambia detalles entre temporadas.
