# 🏈 Dashboard de Fútbol Americano (datos REALES)

Proyecto **educativo** de análisis de datos deportivos con **datos reales de la
NFL** (vía [nflverse](https://github.com/nflverse/nflverse-data)). Analiza
tendencias —incluidos los *underdogs* y el *primetime*— y explica por qué el
sistema de apuestas está diseñado para que el apostador pierda.
**No predice apuestas ni promete ganarle al casino.**

## ¿Qué trae?

- `app.py` — la web (Streamlit). 8 gráficas + pestaña de tendencias.
- `datos.py` — descarga y prepara los datos reales.
- `data/nfl_games.csv` — caché de los partidos (se descarga solo la 1ª vez).
- `data/equipos.csv` — nombres y colores de los equipos.
- `data/partidos.csv` — respaldo de ejemplo si no hay internet.
- `requirements.txt` — librerías.
- `.venv/` — entorno virtual ya creado con todo instalado.

## ¿Qué analiza?

1. **Equipos**: victorias, puntos a favor/contra, distribución de márgenes.
2. **Tendencias**: puntos por semana, % de underdogs que ganan por semana.
3. **Underdogs**: récord general, en **primetime vs. resto**, y por equipo.
4. **Educación**: margen de la casa (vig), valor esperado, y por qué las
   "tendencias" con pocos datos engañan (apofenia / azar).

## ¿Cómo se corre?

> ⚠️ No se corre dentro de Thonny (es una **app web**). Se corre desde la **terminal**.

```sh
cd dashboard_futbol_americano
source .venv/bin/activate
streamlit run app.py
```

Se abre en `http://localhost:8501`. Para detener: `Ctrl + C`.

Si borras el `.venv/`, se recrea:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Nota técnica (importante en macOS)

Este Python no trae los certificados SSL, por eso la descarga usa **`requests`**
(incluye sus propios certificados) en lugar de `urllib`. Si algún día falla la
descarga, la app usa el respaldo `data/partidos.csv`.

## Próximos pasos

- [ ] Publicar gratis en **Streamlit Community Cloud**.
- [ ] Subir a **GitHub** (respaldo + control de versiones).
- [ ] Comparar varias temporadas en una sola vista.
- [ ] Mapa de calor de aciertos por equipo y semana.
