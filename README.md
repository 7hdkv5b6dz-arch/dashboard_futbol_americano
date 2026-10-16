# 🏈 Apuestas NFL — dashboard de análisis con datos REALES

Dashboard de **análisis de apuestas de la NFL** con datos públicos reales de
[nflverse](https://github.com/nflverse/nflverse-data): mercado (spread,
totales, *vig*), rendimiento ATS por equipo, totales y clima, números clave y
un **modelo de pronósticos *walk-forward*** cuyo historial completo se muestra
sin maquillar.

> ⚠️ **Proyecto educativo.** Nada de esto garantiza ganar dinero: el mercado de
> la NFL es casi perfecto y la casa cobra el *vig* (la app lo demuestra con
> datos). 🔞 Solo para +18. Juega responsablemente y nunca apuestes dinero que
> no puedas permitirte perder.

## Las 7 pestañas (23 gráficas)

1. **🎯 Picks del modelo** — pronósticos de la jornada pendiente (solo donde la
   línea ya está publicada) + historial *walk-forward* desde 2006: ROI, % de
   acierto, banca acumulada y la prueba honesta de que *más edge no garantiza
   más acierto*. Puedes mover el **umbral de edge** con un control.
2. **📈 ATS por equipo** — récord contra la línea de cada equipo, **mapa de
   calor equipo × semana**, favoritos cubriendo por tamaño de línea y por
   temporada, y todos los partidos con su resultado ATS.
3. **🎲 Totales y clima** — % de *overs* por equipo, puntos reales vs. línea
   del mercado semana a semana, y el efecto del viento y la temperatura.
4. **🧮 Números clave** — por qué mandan el 3 y el 7, dónde se «clava» la línea
   (*push*), el descanso y el mito del primetime.
5. **💰 Mercado y vig** — ventaja de la casa (moneyline y spread), calibración
   del precio y la **banca a ciegas**: apostar siempre lo mismo pierde,
   temporada tras temporada.
6. **🛒 Precios entre casas** — cuotas **reales de la próxima jornada** en
   varias casas (The Odds API, plan gratuito) para comparar la comisión
   (*vig*) de cada una: quién paga mejor cada lado y cuánto cambia la misma
   apuesta de una casa a otra. Requiere una **clave gratuita** (2 minutos);
   sin ella, la pestaña solo muestra las instrucciones.
7. **📊 Temporadas** — la liga entera temporada a temporada (2020–hoy): puntos
   por partido, % de overs, % de favoritos cubriendo y ROI a ciegas año a año,
   para comprobar si las «tendencias» se repiten (casi nunca) y comparar la
   temporada en curso con las anteriores.

## El modelo (sin trampas)

- Estilo **SRS**: cada equipo tiene un *rating* que sale de un sistema lineal
  sobre los **partidos anteriores** (ventana móvil de 2 temporadas).
- **Walk-forward**: cada partido se pronostica solo con lo sucedido antes de
  él; el resultado nunca se usa para predecirse a sí mismo.
- Compara su pronóstico con la línea → el **edge**. Si supera el umbral
  elegido, emite *pick*. Los *push* devuelven el dinero y no cuentan.
- Las cuotas son las reales de nflverse (desde 2006); antes se asume −110.

## ¿Cómo se corre?

> ⚠️ No se corre dentro de Thonny (es una **app web**). Se corre desde la **terminal**.

```sh
cd dashboard_futbol_americano
source .venv/bin/activate
streamlit run app.py
```

Se abre en `http://localhost:8501`. Para detener: `Ctrl + C`.
(En macOS también puedes hacer doble clic en `Abrir Dashboard.command`.)

Si borras el `.venv/`, se recrea:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Pruebas

```sh
.venv/bin/python -m unittest discover -s tests -t .
```

Cubren cuotas/vig, la convención del spread, *push*, totales, primetime
(incluidas las correcciones de 1999–2005), el resumen por temporada, los
precios entre casas (con datos de laboratorio), el respaldo sin internet y
que el modelo **no vea el futuro**.

## Archivos

| Archivo | Qué es |
|---|---|
| `app.py` | La app de Streamlit (7 pestañas) |
| `datos.py` | Descarga, preparación y modelo de pronósticos |
| `tests/test_datos.py` | Pruebas básicas |
| `data/nfl_games.csv` | Caché de partidos y líneas (se baja sola; NO se sube) |
| `data/equipos.csv` | Nombres y colores (NO se sube) |
| `data/partidos.csv` | Respaldo de ejemplo si no hay internet (sí se sube) |
| `requirements.txt` | Librerías |
| `.streamlit/config.toml` | Tema oscuro del dashboard |
| `CONTEXTO.md` | Memoria del proyecto (léelo antes de tocarlo) |

## Publicar gratis (Streamlit Community Cloud)

1. Sube los cambios a GitHub con **GitHub Desktop**.
2. Entra en [share.streamlit.io](https://share.streamlit.io) → **Create app**
   → elige el repo `dashboard_futbol_americano`, rama `main`, archivo `app.py`.
3. En **Advanced settings**, elige Python **3.12** o **3.13** y pon un
   subdominio bonito (p. ej. `apuestas-nfl-datos`).
4. **Deploy**. La primera vez descarga los datos de nflverse solo (~5 MB).

## Notas técnicas (importantes en macOS)

- La descarga usa **`requests`** (no `urllib`) porque este Python no trae los
  certificados SSL y `requests` sí. Si falla la descarga, la app usa el
  respaldo `data/partidos.csv`.
- **Convención del spread:** `spread_line > 0` → el **local es favorito**
  (el visitante es underdog); `spread_line < 0` → local underdog.
- **Primetime** = inicio ≥ 19:00 ET, con correcciones verificadas para datos
  viejos de nflverse (2000–2005 y 1999). Thanksgiving de día NO cuenta.
- El botón **🔄 Actualizar líneas** vuelve a bajar el CSV (las líneas se mueven
  durante la semana; la app muestra cuándo se descargaron por última vez).
- **Precios entre casas** (pestaña 🛒) usa **The Odds API** con una clave
  gratuita que se guarda en `.streamlit/secrets.toml` (ese archivo NO se sube
  a GitHub); la app explica cómo conseguirla en 2 minutos.

## Próximos pasos

- [ ] Comparar **líneas de apertura vs. cierre** (necesita otra fuente).
- [x] Comparar **precios entre casas** (pestaña 🛒 con The Odds API; clave
      gratuita opcional).
- [x] Comparar varias temporadas en una sola vista (pestaña 📊).
- [ ] Rachas y diferencia de puntos por equipo.
- [x] Mapa de calor ATS por equipo y semana.
- [x] Pruebas básicas de `datos.py`.
- [x] Picks del modelo con historial walk-forward.
