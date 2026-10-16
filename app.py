"""
Dashboard de Apuestas NFL — análisis con datos REALES
======================================================

Análisis de apuestas deportivas con datos reales de nflverse: mercado
(spread, totales, vig), rendimiento ATS por equipo, totales y clima,
números clave y un MODELO de pronósticos walk-forward (entrena solo con
el pasado, nunca con el resultado que intenta predecir) cuyo historial
completo se muestra sin maquillar. Los picks (spread, totales y moneyline)
llevan su REGISTRO de auditoría: qué pegó, qué no, % de acierto y ROI.

Aviso honesto: el mercado de la NFL es casi perfecto y la casa cobra el
vig. Nada de lo que hay aquí garantiza ganar dinero. +18. Juego responsable.

Cómo se corre (NO dentro de Thonny, es una app web):
    source .venv/bin/activate
    streamlit run app.py

Diseño: el tema oscuro (fondo azul noche + verde césped) está en
`.streamlit/config.toml`; los detalles finos (tipografía, chips, tarjetas,
pestañas y ajustes para móvil) están en ESTILO_CSS, y las gráficas comparten
el estilo de `estilo_grafica()` para verse consistentes.
"""

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import calibracion
import datos
import motor_ev

# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Apuestas NFL — datos reales",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos propios. El tema base está en .streamlit/config.toml; aquí van los
# detalles: encabezado, "chips" informativos, tarjetas de métricas, tablas,
# pestañas y un ajuste especial para pantallas angostas (móvil).
ESTILO_CSS = """
<style>
/* --- Ajustes generales --- */
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; }
h1 { letter-spacing: -0.02em; font-size: clamp(1.7rem, 4vw, 2.5rem) !important; }
h2, h3 { letter-spacing: -0.01em; }
[data-testid="stCaptionContainer"] { opacity: 0.8; }

/* --- Chips informativos del encabezado --- */
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.15rem 0 0.6rem; }
.chips span {
  background: rgba(0, 196, 106, 0.10);
  border: 1px solid rgba(0, 196, 106, 0.28);
  color: #A9EFC9;
  border-radius: 999px;
  padding: 0.12rem 0.65rem;
  font-size: 0.78rem;
  white-space: nowrap;
}

/* --- Tarjetas de métricas --- */
[data-testid="stMetricValue"] { font-size: clamp(1.25rem, 3vw, 1.85rem); }

/* --- Pestañas --- */
.stTabs [data-baseweb="tab-list"] { gap: 0.3rem; }
.stTabs [data-baseweb="tab"] { padding: 0.45rem 0.9rem; border-radius: 10px 10px 0 0; }
.stTabs [aria-selected="true"] { background: rgba(0, 196, 106, 0.10); }

/* --- Tablas --- */
[data-testid="stDataFrame"] {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  overflow: hidden;
}

/* --- Avisos --- */
[data-testid="stAlert"] { border-radius: 12px; }

/* --- Móvil: menos relleno y letras legibles en pantallas angostas --- */
@media (max-width: 640px) {
  .block-container { padding-left: 0.9rem; padding-right: 0.9rem; }
  [data-testid="stMetricValue"] { font-size: 1.30rem; }
  .stTabs [data-baseweb="tab"] { padding: 0.4rem 0.55rem; font-size: 0.85rem; }
  .chips span { font-size: 0.72rem; }
}
</style>
"""
st.markdown(ESTILO_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Gráficas: estilo común
# ---------------------------------------------------------------------------
def estilo_grafica(fig, alto=430):
    """Aplica el estilo visual común: fondo transparente, fuente y márgenes.

    `mostrar_grafica()` usa theme=None para que Streamlit NO pise estos
    ajustes (si no, cada gráfica saldría con colores distintos).
    """
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=alto,
        margin=dict(l=12, r=12, t=58, b=12),
        title=dict(x=0.01, xanchor="left", font=dict(size=16)),
        font=dict(size=13),
        hoverlabel=dict(font_size=13),
        # Paleta base: verde césped, azul, amarillo luna, coral y lila
        colorway=["#00C46A", "#4C9AFF", "#F2C14E", "#FF6B6B", "#B48EFF"],
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,.07)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(255,255,255,.07)", zeroline=False)
    return fig


def mostrar_grafica(fig, alto=430):
    """Estiliza la figura y la dibuja (sin barra de herramientas: mejor en móvil)."""
    st.plotly_chart(
        estilo_grafica(fig, alto),
        width="stretch",
        theme=None,
        config={"displayModeBar": False, "responsive": True},
    )


# ---------------------------------------------------------------------------
# Apuestas: pequeños cálculos compartidos
# ---------------------------------------------------------------------------
def cuota_a_pago(cuotas):
    """Cuota americana (-110, +145...) → pago por cada $1 (sin devolver el $)."""
    c = pd.to_numeric(cuotas, errors="coerce").fillna(-110)
    return (c / 100).where(c > 0, 100 / -c)


def ganancia_apuesta(cuotas, gano):
    """$ ganados/perdidos por cada $1 apostado, según la cuota americana.

    Donde no hay cuota (antes de 2006) se asume la cuota estándar -110.
    Quien llama ya debe haber quitado los push (apuesta nula, devuelve $).
    """
    gano_f = pd.Series(gano, index=pd.Series(cuotas).index).astype("boolean").fillna(False)
    return cuota_a_pago(cuotas).where(gano_f.astype(bool), -1.0)


def evaluar_spread(df, umbral, calibrado=False):
    """Picks del modelo contra el spread, ya calificados.

    Elige el lado (local con `edge > 0`, visitante con `edge < 0`) cuando la
    ventaja estimada llega al `umbral`. Los push quedan como apuesta nula
    (ganancia $0, no cuentan como acierto). Añade `prob_modelo` y
    `prob_mercado` DEL LADO DEL PICK (el mercado sin vig, como referencia).

    Con `calibrado=True` (jornada pendiente) `prob_modelo` es la probabilidad
    CALIBRADA (F4, `calibracion.py`); con el valor por defecto (histórico) se
    conserva la probabilidad bruta con la que se emitió aquel pick.
    """
    d = df[df["margen_modelo"].notna() & df["spread_line"].notna()].copy()
    d["edge"] = d["margen_modelo"] - d["spread_line"]
    d = d[d["edge"].abs() >= umbral].copy()
    d["al_local"] = d["edge"] > 0
    d["pick"] = d["home_team"].where(d["al_local"], d["away_team"])
    d["linea_pick"] = np.where(d["al_local"], -d["spread_line"], d["spread_line"])
    d["gano"] = d["cubre_local"].where(d["al_local"], d["cubre_visitante"])
    d["gano"] = d["gano"].mask(d["push_spread"].fillna(False))  # push: sin juicio
    d["cuota"] = d["home_spread_odds"].where(d["al_local"], d["away_spread_odds"])
    d["ganancia"] = ganancia_apuesta(d["cuota"], d["gano"]).where(d["gano"].notna(), 0.0)
    if "sigma_modelo" in d.columns:
        p_cubre_local = datos.probabilidad_supera(
            d["margen_modelo"], d["spread_line"], d["sigma_modelo"])
        if calibrado:
            p_cubre_local = calibracion.calibrar("spread", p_cubre_local)
        d["prob_modelo"] = p_cubre_local.where(d["al_local"], 1.0 - p_cubre_local)
        p_merc = d["prob_local_spread_sin_vig"]
        d["prob_mercado"] = p_merc.where(d["al_local"], 1.0 - p_merc)
    return d


def evaluar_totales(df, umbral, calibrado=False):
    """Picks del modelo en el total (más/menos), ya calificados.

    Añade `prob_modelo` (probabilidad normal del lado elegido) y
    `prob_mercado` (el sin vig del mercado), ambas del lado del pick.

    Con `calibrado=True` (jornada pendiente) `prob_modelo` es la probabilidad
    CALIBRADA (F4, `calibracion.py`); por defecto se conserva la bruta del
    histórico.
    """
    d = df[df["total_modelo"].notna() & df["total_line"].notna()].copy()
    d["edge"] = d["total_modelo"] - d["total_line"]
    d = d[d["edge"].abs() >= umbral].copy()
    d["al_over"] = d["edge"] > 0
    d["pick"] = np.where(d["al_over"], "Más de " + d["total_line"].astype(str),
                         "Menos de " + d["total_line"].astype(str))
    d["gano"] = d["over"].where(d["al_over"], ~d["over"])
    d["cuota"] = d["over_odds"].where(d["al_over"], d["under_odds"])
    d["ganancia"] = ganancia_apuesta(d["cuota"], d["gano"]).where(d["gano"].notna(), 0.0)
    if "sigma_total_modelo" in d.columns:
        p_over = datos.probabilidad_supera(
            d["total_modelo"], d["total_line"], d["sigma_total_modelo"])
        if calibrado:
            p_over = calibracion.calibrar("total", p_over)
        d["prob_modelo"] = p_over.where(d["al_over"], 1.0 - p_over)
        po = datos._prob_implicita(d["over_odds"])
        pu = datos._prob_implicita(d["under_odds"])
        p_merc = po / (po + pu)
        d["prob_mercado"] = p_merc.where(d["al_over"], 1.0 - p_merc)
    return d


def metricas_picks(picks):
    """(nº de apuestas, % de acierto sin push, ROI % por $1)."""
    if not len(picks):
        return 0, float("nan"), float("nan")
    acierto = picks["gano"].mean()  # mean ya descarta los push (NA)
    acierto = float(acierto) if pd.notna(acierto) else float("nan")
    roi = float(picks["ganancia"].mean()) * 100
    return len(picks), acierto * 100, roi


def etiqueta_pick(equipo, linea):
    """«Chiefs -3.5» — la línea desde el punto de vista del equipo elegido."""
    return f"{APODOS.get(equipo, equipo)} {linea:+.1f}"


def nivel_confianza(edge_abs):
    """Etiqueta informativa por tamaño del edge (no es una promesa)."""
    if edge_abs >= 4.5:
        return "Muy alta"
    if edge_abs >= 3.0:
        return "Alta"
    return "Normal"


def registros_ats(df):
    """Récord ATS por equipo (desde la perspectiva de su propia línea)."""
    d = df[df["spread_line"].notna() & df["margen"].notna()]
    filas = []
    for local, visitante, margen, linea in d[
        ["home_team", "away_team", "margen", "spread_line"]
    ].itertuples(index=False, name=None):
        if margen > linea:
            filas += [(local, 1), (visitante, -1)]
        elif margen < linea:
            filas += [(local, -1), (visitante, 1)]
        else:
            filas += [(local, 0), (visitante, 0)]
    t = pd.DataFrame(filas, columns=["equipo", "valor"])
    res = t.groupby("equipo")["valor"].agg(
        cubiertas=lambda s: int((s == 1).sum()),
        falladas=lambda s: int((s == -1).sum()),
        pushes=lambda s: int((s == 0).sum()),
    ).reset_index()
    res["decididas"] = res["cubiertas"] + res["falladas"]
    res["pct"] = (res["cubiertas"] / res["decididas"].replace(0, np.nan) * 100).round(1)
    res["apodo"] = res["equipo"].map(lambda e: APODOS.get(e, e))
    return res


def matriz_ats(df):
    """Matriz equipo × semana para el mapa de calor ATS.

    Valor: +1 cubrió, 0 push, -1 no cubrió (NaN = no jugó). Devuelve además
    el texto de cada celda (rival y marcador) para el hover.
    """
    d = df[df["spread_line"].notna() & df["margen"].notna()]
    valores, textos = [], []
    for semana, local, visitante, margen, linea in d[
        ["week", "home_team", "away_team", "margen", "spread_line"]
    ].itertuples(index=False, name=None):
        marcador = f"{int(margen):+d}"
        if margen > linea:
            vl, vv = 1, -1
        elif margen < linea:
            vl, vv = -1, 1
        else:
            vl, vv = 0, 0
        valores += [(local, semana, vl), (visitante, semana, vv)]
        textos += [
            (local, semana, f"vs {APODOS.get(visitante, visitante)} · {marcador}"),
            (visitante, semana, f"en {APODOS.get(local, local)} · {-int(margen):+d}"),
        ]
    zv = (pd.DataFrame(valores, columns=["equipo", "semana", "valor"])
          .pivot_table(index="equipo", columns="semana", values="valor", aggfunc="first"))
    zt = (pd.DataFrame(textos, columns=["equipo", "semana", "texto"])
          .pivot_table(index="equipo", columns="semana", values="texto", aggfunc="first"))
    return zv, zt


def totales_por_equipo(df):
    """% de overs de cada equipo (sin contar push ni partidos sin línea)."""
    d = df[df["over"].notna()]
    filas = []
    for local, visitante, over in d[
        ["home_team", "away_team", "over"]
    ].itertuples(index=False, name=None):
        filas += [(local, bool(over)), (visitante, bool(over))]
    t = pd.DataFrame(filas, columns=["equipo", "over"])
    res = t.groupby("equipo")["over"].agg(overs="sum", n="size").reset_index()
    res["pct"] = (res["overs"] / res["n"] * 100).round(1)
    res["apodo"] = res["equipo"].map(lambda e: APODOS.get(e, e))
    return res


# ---------------------------------------------------------------------------
# DATOS
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Descargando datos reales de nflverse (resultados, líneas y clima)...")
def traer_calendario():
    return datos.cargar_calendario()


@st.cache_data
def traer_equipos():
    return datos.cargar_equipos()


@st.cache_data(show_spinner="Calculando el modelo walk-forward (entrena solo con el pasado)...")
def traer_pronosticos_historicos():
    return datos.pronosticos_historicos(traer_calendario())


@st.cache_data(show_spinner="Pronosticando la jornada pendiente...")
def traer_pronosticos_futuros():
    calendario = traer_calendario()
    pendientes = calendario[~calendario["jugado"] & calendario["spread_line"].notna()]
    return datos.pronosticos_futuros(calendario, pendientes)


calendario = traer_calendario()
equipos = traer_equipos()
NOMBRES = datos.mapa_nombres(equipos)
APODOS = datos.mapa_apodos(equipos)
COLORES = datos.mapa_colores(equipos)

partidos = calendario[calendario["jugado"]].copy()
proximos = calendario[~calendario["jugado"] & calendario["spread_line"].notna()].copy()

hist_picks = traer_pronosticos_historicos()
picks_futuros = traer_pronosticos_futuros()

# Los sigmas de la jornada pendiente (misma aritmética que el 📋) los usan la
# calibración y el motor de EV (push + banda) en toda la app, no solo en el
# registro: se dejan puestos aquí una sola vez.
_sigma_fut, _sigma_total_fut = datos.sigma_actual(
    hist_picks[hist_picks["season"] >= 2006])
picks_futuros = picks_futuros.assign(
    sigma_modelo=_sigma_fut, sigma_total_modelo=_sigma_total_fut)


def color_equipos(valores):
    """Lista de colores reales para una lista de abreviaturas."""
    return [COLORES.get(v, "#888888") for v in valores]


def fecha_de_datos():
    """Fecha de la última descarga del CSV de partidos (frescura de líneas)."""
    ruta = Path(datos.BASE) / "nfl_games.csv"
    if ruta.exists():
        return datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
    return "sin archivo local"


def clave_odds_api():
    """Clave de The Odds API: primero la de la sesión, luego secrets.toml."""
    clave = st.session_state.get("odds_api_key", "")
    if clave:
        return clave
    try:
        return str(st.secrets.get("ODDS_API_KEY", "") or "")
    except Exception:
        # Todavía no hay archivo de secretos: la pestaña explica cómo crearlo.
        return ""


def guardar_clave(api_key):
    """Guarda la clave de The Odds API en .streamlit/secrets.toml (solo local)."""
    carpeta = Path(__file__).resolve().parent / ".streamlit"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "secrets.toml").write_text(
        "# Clave gratuita de The Odds API — archivo local, NO se sube a GitHub\n"
        f'ODDS_API_KEY = "{api_key}"\n',
        encoding="utf-8",
    )


def nombre_corto(nombre_api):
    """«Kansas City Chiefs» → «Chiefs» (deja el nombre tal cual si no lo ubica)."""
    abreviatura = datos.abreviatura_de(nombre_api, equipos)
    return APODOS.get(abreviatura, nombre_api) if abreviatura else nombre_api


@st.cache_data(ttl=900, show_spinner="Consultando cuotas en vivo (gasta 2-4 créditos)...")
def traer_precios_casas(clave, regiones):
    """Cuotas entre casas, cacheadas 15 minutos para no gastar créditos.

    Devuelve `(tabla, uso, momento)`: la tabla larga de precios, el uso de
    créditos del mes y la hora (local) en que se hizo la consulta.
    """
    tabla, uso = datos.cargar_precios_casas(clave, regiones=regiones)
    return tabla, uso, datetime.now().strftime("%d/%m %H:%M")


# ---------------------------------------------------------------------------
# ENCABEZADO
# ---------------------------------------------------------------------------
st.title("🏈 Apuestas NFL — análisis con datos reales")
st.caption(
    "Mercado (spread, totales, vig), ATS por equipo, clima, números clave y un "
    "**modelo de pronósticos walk-forward** con su historial completo. "
    "Datos públicos de nflverse. Nada de esto garantiza ganar: el mercado es "
    "casi perfecto (mira la pestaña 💰)."
)

rango_temporadas = (
    f"🗓️ Temporadas {int(partidos['season'].min())}–{int(partidos['season'].max())}"
    if len(partidos)
    else "🗓️ Datos de ejemplo (sin conexión)"
)
st.markdown(
    f'<div class="chips">'
    f'<span>📡 Datos reales · nflverse</span>'
    f'<span>{rango_temporadas}</span>'
    f'<span>🎯 Modelo sin ver el futuro</span>'
    f'<span>🌙 Primetime verificado</span>'
    f'<span>🔞 +18 · Juego responsable</span>'
    f"</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# FILTROS (barra lateral)
# ---------------------------------------------------------------------------
st.sidebar.header("Filtros")

temporadas = sorted((t for t in partidos["season"].unique() if t > 0), reverse=True)
temporadas = temporadas[:10]
if not temporadas:
    st.error(
        "No hay datos de partidos todavía. Comprueba tu conexión y pulsa "
        "«🔄 Actualizar líneas» en la barra lateral."
    )
    st.stop()

temporada_sel = st.sidebar.selectbox("Temporada", temporadas, index=0)

df_temp = partidos[partidos["season"] == temporada_sel]

lista_equipos = sorted(set(df_temp["home_team"]) | set(df_temp["away_team"]))
equipo_sel = st.sidebar.selectbox(
    "Equipo", ["Todos"] + lista_equipos, format_func=lambda v: datos.con_nombre(v, NOMBRES)
)

solo_primetime = st.sidebar.checkbox("Solo partidos primetime 🌙", value=False)

# Base = temporada (para tendencias de liga); Vista = con filtro de equipo
df_base = df_temp[df_temp["primetime"]] if solo_primetime else df_temp
if equipo_sel == "Todos":
    df_vista = df_base
else:
    df_vista = df_base[
        (df_base["home_team"] == equipo_sel) | (df_base["away_team"] == equipo_sel)
    ]

st.sidebar.caption(f"Partidos: {len(df_vista)}")
st.sidebar.markdown("---")

if st.sidebar.button("🔄 Actualizar líneas", help="Vuelve a descargar los datos de nflverse."):
    datos.actualizar_datos()
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption(f"Datos descargados: {fecha_de_datos()}")

st.sidebar.caption("Fuente: [nflverse](https://github.com/nflverse/nflverse-data)")
with st.sidebar.expander("ℹ️ Acerca de"):
    st.markdown(
        "Dashboard de **análisis de apuestas** con datos reales de la NFL. "
        "El modelo de pronósticos entrena **solo con partidos anteriores** y "
        "su historial se muestra tal cual, con temporadas ganadoras y perdedoras. "
        "El mercado de la NFL es casi perfecto: trátalo con escepticismo."
    )
st.sidebar.caption(
    "🔞 Solo para mayores de 18. Si el juego deja de ser diversión: "
    "**1-800-522-4700** (EE. UU.) · **900 200 225** (España). "
    "Nunca apuestes dinero que no puedas permitirte perder."
)


# ---------------------------------------------------------------------------
# MÉTRICAS (según los filtros)
# ---------------------------------------------------------------------------
decididas = df_vista[df_vista["cubre_favorito"].notna()]
con_total = df_vista[df_vista["over"].notna()]

pct_fav = decididas["cubre_favorito"].mean() * 100 if len(decididas) else float("nan")
pct_over = con_total["over"].mean() * 100 if len(con_total) else float("nan")

cuota_ciego = df_vista["home_spread_odds"].where(df_vista["favorito_local"], df_vista["away_spread_odds"])
roi_ciego_vista = (
    float(ganancia_apuesta(cuota_ciego[decididas.index], decididas["cubre_favorito"]).mean()) * 100
    if len(decididas) else float("nan")
)

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Partidos", len(df_vista), border=True,
    help="Partidos jugados que cumplen los filtros de la barra lateral.",
)
c2.metric(
    "Favoritos cubren la línea",
    f"{pct_fav:.1f}%" if len(decididas) else "—",
    border=True,
    help="De los partidos con línea clara (sin push ni pick'em). Si el mercado "
         "fuera perfecto: 50%.",
)
c3.metric(
    "Overs del total",
    f"{pct_over:.1f}%" if len(con_total) else "—",
    border=True,
    help="Partidos en que la suma de puntos superó la línea del total (sin push).",
)
c4.metric(
    "ROI a ciegas (favoritos)",
    f"{roi_ciego_vista:+.1f}%" if len(decididas) else "—",
    border=True,
    help="Resultado por cada $1 apostado SIEMPRE al favorito contra el spread, "
         "en los partidos filtrados. Negativo = la casa gana, como esperarías.",
)

tab_picks, tab_registro, tab_ats, tab_totales, tab_clave, tab_mercado, tab_precios, tab_temporadas = st.tabs([
    "🎯 Picks del modelo",
    "📋 Registro de picks",
    "📈 ATS por equipo",
    "🎲 Totales y clima",
    "🧮 Números clave",
    "💰 Mercado y vig",
    "🛒 Precios entre casas",
    "📊 Temporadas",
])

# Días de la semana en español (para las tablas de partidos)
DIAS_ES = {
    "Sunday": "Domingo", "Monday": "Lunes", "Tuesday": "Martes",
    "Wednesday": "Miércoles", "Thursday": "Jueves", "Friday": "Viernes",
    "Saturday": "Sábado",
}


# ===========================================================================
# TAB 1 — PICKS DEL MODELO
# ===========================================================================
with tab_picks:
    st.header("🎯 Picks del modelo")

    st.warning(
        "**Lee esto antes que nada.** Estos pronósticos salen de un modelo "
        "simple (ratings por puntos, estilo SRS) construido con datos públicos. "
        "El mercado de la NFL es extremadamente eficiente: incluso modelos "
        "profesionales rara vez ganan de forma sostenida después del *vig*. "
        "Abajo tienes el historial real y sin trampa — incluye temporadas en "
        "las que el modelo **pierde dinero**. Esto es material educativo, no "
        "un consejo de inversión. 🔞 Juega solo lo que puedas permitirte perder."
    )

    with st.expander("🤖 ¿Cómo funciona el modelo?"):
        st.markdown(
            """
**Walk-forward, sin ver el futuro.** Cada partido se pronostica usando
**solo los partidos anteriores** a él (el modelo se reajusta al empezar cada
jornada). Nada de "entrenar con todo el histórico y luego fardar de aciertos":
eso es la trampa más común que verás por internet.

**Qué calcula** (ventana móvil de las 2 últimas temporadas, con una pequeña
regularización para que los ratings no se disparen en la semana 1):

- **Margen esperado** ≈ ventaja de jugar en casa + rating_local − rating_visitante
- **Total esperado** ≈ base + ataque_local + ataque_visitante + defensa_local + defensa_visitante

**El pick.** Se compara el pronóstico con la línea del mercado; la diferencia
es el *edge* (puntos de ventaja). Solo se emite pick si el edge supera el
umbral que elijas. Los *push* (línea clavada) devuelven el dinero y no cuentan.
Las cuotas son las reales de nflverse (desde 2006); antes se asume −110.
            """
        )

    umbral = st.select_slider(
        "Umbral de edge: ventaja mínima del modelo para emitir un pick (puntos)",
        options=[1.0, 1.5, 2.0, 2.5, 3.0, 4.0],
        value=2.0,
    )

    # --- 1) La jornada pendiente (líneas ya publicadas) ---
    st.subheader("📅 Jornada pendiente")

    fut = picks_futuros.copy()
    fut = fut[fut["margen_modelo"].notna() & fut["total_modelo"].notna()]

    if len(fut):
        fut["edge"] = fut["margen_modelo"] - fut["spread_line"]
        fut["edge_total"] = fut["total_modelo"] - fut["total_line"]

        n_picks_spread = int((fut["edge"].abs() >= umbral).sum())
        n_picks_total = int((fut["edge_total"].abs() >= umbral).sum())
        semanas = sorted(fut["week"].unique())

        m1, m2, m3 = st.columns(3)
        m1.metric("Partidos con línea publicada", len(fut), border=True,
                  help="Partidos pendientes que ya tienen spread en nflverse.")
        m2.metric("Picks contra el spread", n_picks_spread, border=True,
                  help=f"Partidos con edge ≥ {umbral} puntos contra la línea.")
        m3.metric("Picks de total", n_picks_total, border=True,
                  help=f"Partidos con edge ≥ {umbral} puntos en el total.")

        semanas_txt = ", ".join(f"semana {int(s)}" for s in semanas)
        st.caption(
            f"Líneas capturadas el **{fecha_de_datos()}** ({semanas_txt}). "
            "Las líneas se mueven durante la semana: si la cuota real ya no se "
            "parece a esta, el edge puede haber desaparecido."
        )

        # Tabla: contra el spread
        ts = fut[fut["edge"].abs() >= umbral].copy()
        st.markdown("**Picks contra el spread**")
        if len(ts):
            ts["al_local"] = ts["edge"] > 0
            ts["cuota"] = ts["home_spread_odds"].where(ts["al_local"], ts["away_spread_odds"])
            ts["Pick"] = [
                etiqueta_pick(eq, lin)
                for eq, lin in zip(ts["home_team"].where(ts["al_local"], ts["away_team"]),
                                   np.where(ts["al_local"], -ts["spread_line"], ts["spread_line"]))
            ]
            ts["Partido"] = (
                ts["away_team"].map(APODOS).fillna(ts["away_team"]) + " @ "
                + ts["home_team"].map(APODOS).fillna(ts["home_team"])
            )
            ts["Línea"] = [
                f"{APODOS.get(loc, loc)} {-lin:+.1f}"
                for loc, lin in zip(ts["home_team"], ts["spread_line"])
            ]
            ts["Nivel"] = ts["edge"].abs().map(nivel_confianza)
            p_cubre = calibracion.calibrar("spread", datos.probabilidad_supera(
                ts["margen_modelo"], ts["spread_line"], ts["sigma_modelo"]))
            ts["prob_modelo"] = p_cubre.where(ts["al_local"], 1.0 - p_cubre)
            ts = motor_ev.decorar(ts, "spread")
            tabla_s = ts[["week", "gameday", "Partido", "Línea", "Pick",
                          "margen_modelo", "edge", "cuota", "Nivel",
                          "p_equilibrio", "p_estimada", "p_push", "ev_estimado",
                          "estado_ev"]].rename(
                columns={
                    "week": "Semana", "gameday": "Fecha",
                    "margen_modelo": "Margen modelo", "edge": "Edge",
                    "cuota": "Cuota", "Partido": "Partido",
                    "p_equilibrio": "P. eq.", "p_estimada": "P. est.",
                    "p_push": "P. push", "ev_estimado": "EV $1",
                    "estado_ev": "Estado",
                }
            )
            tabla_s["P. eq."] = tabla_s["P. eq."] * 100.0
            tabla_s["P. est."] = tabla_s["P. est."] * 100.0
            tabla_s["P. push"] = tabla_s["P. push"] * 100.0
            st.dataframe(
                tabla_s, width="stretch", hide_index=True, height=min(430, 40 + 36 * len(tabla_s)),
                column_config={
                    "Semana": st.column_config.NumberColumn(format="%d"),
                    "Margen modelo": st.column_config.NumberColumn(
                        format="%+.1f", help="Margen esperado (local − visitante)."),
                    "Edge": st.column_config.NumberColumn(
                        format="%+.1f", help="Puntos que el modelo ve por encima de la línea."),
                    "Cuota": st.column_config.NumberColumn(format="%d"),
                    "Línea": st.column_config.TextColumn(
                        help="La línea desde el equipo local (+ = local favorito)."),
                    "P. eq.": st.column_config.NumberColumn(
                        format="%.1f%%",
                        help="Probabilidad de equilibrio del momio (1/(1+pago "
                             "neto)): por debajo de ella el EV es negativo."),
                    "P. est.": st.column_config.NumberColumn(
                        format="%.1f%%",
                        help="Probabilidad calibrada del pick (F4)."),
                    "P. push": st.column_config.NumberColumn(
                        format="%.2f%%",
                        help="Probabilidad de push estimada por el modelo: 0 "
                             "exacto en líneas x.5; en líneas enteras y "
                             "empates se estima (con sesgo medido: ver nota "
                             "de abajo)."),
                    "EV $1": st.column_config.NumberColumn(
                        format="%+.3f",
                        help="Valor esperado por $1 con push explícito: si el "
                             "resultado cae justo en la línea, la apuesta se "
                             "devuelve y no suma ni resta."),
                    "Estado": st.column_config.TextColumn(
                        help="Sin EV · EV+ en el ruido · EV+ sin validar. "
                             "Ningún estado «valida» la apuesta."),
                },
            )
            st.caption(
                f"{len(fut) - len(ts)} partidos quedaron sin pick: el modelo no "
                "ve ventaja suficiente. Eso es lo normal — el mercado casi "
                "siempre está bien puesto."
            )
        else:
            st.info("Ningún partido supera el umbral esta jornada. Es lo habitual.")

        # Tabla: totales
        tt = fut[fut["edge_total"].abs() >= umbral].copy()
        st.markdown("**Picks de total (más/menos)**")
        if len(tt):
            tt["Pick"] = np.where(
                tt["edge_total"] > 0,
                "Más de " + tt["total_line"].astype(str),
                "Menos de " + tt["total_line"].astype(str),
            )
            tt["Partido"] = (
                tt["away_team"].map(APODOS).fillna(tt["away_team"]) + " @ "
                + tt["home_team"].map(APODOS).fillna(tt["home_team"])
            )
            tt["cuota"] = tt["over_odds"].where(tt["edge_total"] > 0, tt["under_odds"])
            tt["al_over"] = tt["edge_total"] > 0
            tt["Nivel"] = tt["edge_total"].abs().map(nivel_confianza)
            p_over = calibracion.calibrar("total", datos.probabilidad_supera(
                tt["total_modelo"], tt["total_line"], tt["sigma_total_modelo"]))
            tt["prob_modelo"] = p_over.where(tt["edge_total"] > 0, 1.0 - p_over)
            tt = motor_ev.decorar(tt, "total")
            tabla_t = tt[["week", "gameday", "Partido", "total_line",
                          "total_modelo", "edge_total", "Pick", "cuota",
                          "Nivel", "p_equilibrio", "p_estimada", "p_push",
                          "ev_estimado", "estado_ev"]].rename(
                columns={
                    "week": "Semana", "gameday": "Fecha",
                    "total_line": "Total (línea)", "total_modelo": "Total modelo",
                    "edge_total": "Edge", "cuota": "Cuota",
                    "p_equilibrio": "P. eq.", "p_estimada": "P. est.",
                    "p_push": "P. push", "ev_estimado": "EV $1",
                    "estado_ev": "Estado",
                }
            )
            tabla_t["P. eq."] = tabla_t["P. eq."] * 100.0
            tabla_t["P. est."] = tabla_t["P. est."] * 100.0
            tabla_t["P. push"] = tabla_t["P. push"] * 100.0
            st.dataframe(
                tabla_t, width="stretch", hide_index=True,
                height=min(430, 40 + 36 * len(tabla_t)),
                column_config={
                    "Semana": st.column_config.NumberColumn(format="%d"),
                    "Total (línea)": st.column_config.NumberColumn(format="%.1f"),
                    "Total modelo": st.column_config.NumberColumn(
                        format="%.1f", help="Puntos totales esperados."),
                    "Edge": st.column_config.NumberColumn(format="%+.1f"),
                    "Cuota": st.column_config.NumberColumn(format="%d"),
                    "P. eq.": st.column_config.NumberColumn(
                        format="%.1f%%",
                        help="Probabilidad de equilibrio del momio (1/(1+pago "
                             "neto)): por debajo de ella el EV es negativo."),
                    "P. est.": st.column_config.NumberColumn(
                        format="%.1f%%",
                        help="Probabilidad calibrada del pick (F4)."),
                    "P. push": st.column_config.NumberColumn(
                        format="%.2f%%",
                        help="Probabilidad de push estimada por el modelo: 0 "
                             "exacto en líneas x.5; en líneas enteras y "
                             "empates se estima (con sesgo medido: ver nota "
                             "de abajo)."),
                    "EV $1": st.column_config.NumberColumn(
                        format="%+.3f",
                        help="Valor esperado por $1 con push explícito: si el "
                             "resultado cae justo en la línea, la apuesta se "
                             "devuelve y no suma ni resta."),
                    "Estado": st.column_config.TextColumn(
                        help="Sin EV · EV+ en el ruido · EV+ sin validar. "
                             "Ningún estado «valida» la apuesta."),
                },
            )
        else:
            st.info("Ningún total supera el umbral esta jornada.")

        st.caption(
            "**EV $1** = valor esperado por dólar con **push explícito**: si "
            "el resultado cae justo en la línea, la apuesta se devuelve y no "
            "suma ni resta. **P. eq.** = probabilidad de equilibrio del momio: "
            "por debajo de ella el EV es negativo. **P. est.** = probabilidad "
            "calibrada del pick. **Estado** no «valida» nada: un EV+ puede ser "
            "ruido o error de calibración. Puede no haber ninguna apuesta con "
            "EV+."
        )
        st.caption(f"**Sesgo del push (medido):** {motor_ev.NOTA_PUSH}")
        st.caption(f"**Estado de la estrategia:** {motor_ev.ESTADO_ESTRATEGIA}")
    else:
        st.info(
            "Ahora mismo no hay partidos pendientes con línea publicada "
            "(temporada terminada o líneas aún sin abrir). Vuelve en la semana "
            "de partidos o pulsa «🔄 Actualizar líneas»."
        )

    # --- 2) Historial walk-forward del modelo (2006+ = cuotas reales) ---
    st.subheader("📜 Historial del modelo")
    st.caption(
        "Evaluación **walk-forward** de toda la serie con cuotas reales "
        "(2006 en adelante). Incluye lo bueno y lo malo, tal cual salió. "
        "Los push no cuentan como acierto y devuelven el dinero."
    )

    hist_era = hist_picks[hist_picks["season"] >= 2006].copy()
    picks_spread = evaluar_spread(hist_era, umbral)
    picks_total = evaluar_totales(hist_era, umbral)

    n_s, acierto_s, roi_s = metricas_picks(picks_spread)
    n_t, acierto_t, roi_t = metricas_picks(picks_total)

    # Referencias "a ciegas" del mismo periodo (para comparar)
    ciega_fav = hist_era[hist_era["cubre_favorito"].notna()]
    roi_ciego_fav = float(ganancia_apuesta(
        ciega_fav["home_spread_odds"].where(ciega_fav["favorito_local"],
                                            ciega_fav["away_spread_odds"]),
        ciega_fav["cubre_favorito"],
    ).mean()) * 100
    ciega_tot = hist_era[hist_era["over"].notna()]
    roi_ciego_tot = float(np.mean([
        ganancia_apuesta(ciega_tot["over_odds"], ciega_tot["over"]).mean(),
        ganancia_apuesta(ciega_tot["under_odds"], ~ciega_tot["over"]).mean(),
    ])) * 100

    h1, h2, h3, h4 = st.columns(4)
    h1.metric(
        "Picks contra el spread", n_s, border=True,
        help="Apuestas emitidas con este umbral desde 2006 (sin push).",
    )
    h2.metric(
        "Acierto contra el spread",
        f"{acierto_s:.1f}%" if n_s else "—",
        border=True,
        help="Hay que acertar ~52.4% para empatar con cuota -110.",
    )
    h3.metric(
        "ROI contra el spread",
        f"{roi_s:+.1f}%" if n_s else "—",
        delta=f"{roi_s - roi_ciego_fav:+.1f} pp vs a ciegas" if n_s else None,
        border=True,
        help="Ganancia media por $1 apostado, comparada con apostar siempre "
             "al favorito en el mismo periodo.",
    )
    h4.metric(
        "ROI en totales",
        f"{roi_t:+.1f}%" if n_t else "—",
        delta=f"{roi_t - roi_ciego_tot:+.1f} pp vs a ciegas" if n_t else None,
        border=True,
        help=f"{n_t} picks de más/menos. Comparado con apostar a ciegas "
             "over/under en el mismo periodo.",
    )

    # Gráfica 1: la banca acumulada (modelo vs a ciegas)
    def serie_banca(ganancias, etiqueta, seasons, semanas):
        ganancias = pd.Series(ganancias).astype(float)
        return pd.DataFrame({
            "apuesta": np.arange(1, len(ganancias) + 1),
            "estrategia": etiqueta,
            "ganancia": ganancias.cumsum().to_numpy(),
            "season": np.asarray(seasons),
            "week": np.asarray(semanas),
        })

    banca = pd.concat([
        serie_banca(picks_spread["ganancia"], "Modelo · spread",
                    picks_spread["season"], picks_spread["week"]),
        serie_banca(picks_total["ganancia"], "Modelo · totales",
                    picks_total["season"], picks_total["week"]),
        serie_banca(ganancia_apuesta(
            ciega_fav["home_spread_odds"].where(ciega_fav["favorito_local"],
                                                ciega_fav["away_spread_odds"]),
            ciega_fav["cubre_favorito"],
        ), "A ciegas · favoritos", ciega_fav["season"], ciega_fav["week"]),
    ], ignore_index=True)

    fig = px.line(
        banca, x="apuesta", y="ganancia", color="estrategia",
        color_discrete_map={
            "Modelo · spread": "#00C46A", "Modelo · totales": "#4C9AFF",
            "A ciegas · favoritos": "#5B6B8C",
        },
        custom_data=["season", "week"],
        title="La banca: $1 por apuesta, acumulado (2006–hoy)",
        labels={"apuesta": "Nº de apuesta (cronológico)", "ganancia": "Ganancia ($)", "estrategia": ""},
    )
    fig.update_traces(
        line=dict(width=2.5),
        hovertemplate="Apuesta nº %{x}<br><b>%{fullData.name}</b>"
                      "<br>Acumulado: $%{y:.0f}"
                      "<br>Temporada %{customdata[0]}, semana %{customdata[1]}"
                      "<extra></extra>",
    )
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,.35)")
    mostrar_grafica(fig, alto=470)
    st.caption(
        "Cada línea es una estrategia apostando $1 en cada partido. Si una "
        "línea baja con el tiempo, esa estrategia pierde: la casa se queda "
        "con la diferencia. El objetivo de un modelo es **no caer rápido**, "
        "no hacerse rico."
    )

    # Gráfica 2 (izq): ROI por temporada — y 3 (der): ¿más edge = más acierto?
    izq, der = st.columns(2)
    with izq:
        roi_temp = pd.concat([
            picks_spread.groupby("season").agg(roi=("ganancia", "mean"), n=("ganancia", "size"))
            .assign(estrategia="Spread"),
            picks_total.groupby("season").agg(roi=("ganancia", "mean"), n=("ganancia", "size"))
            .assign(estrategia="Totales"),
        ]).reset_index()
        roi_temp["roi"] = (roi_temp["roi"] * 100).round(1)
        roi_temp["season"] = roi_temp["season"].astype(int).astype(str)
        fig = px.bar(
            roi_temp, x="season", y="roi", color="estrategia", barmode="group",
            color_discrete_map={"Spread": "#00C46A", "Totales": "#4C9AFF"},
            custom_data=["n"],
            title="ROI del modelo por temporada",
            labels={"season": "Temporada", "roi": "ROI (%)", "estrategia": ""},
        )
        fig.update_traces(
            hovertemplate="Temporada %{x} · <b>%{fullData.name}</b>"
                          "<br>ROI: %{y:+.1f}%<br>Apuestas: %{customdata[0]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,.4)")
        mostrar_grafica(fig)
        st.caption(
            "Una temporada ganadora no es una estrategia: fíjate en la mezcla "
            "de años verdes y rojos. Y ojo: aquí NO está contado nada de suerte "
            "posterior — el ROI ya incluye todas las apuestas del umbral elegido."
        )

    with der:
        d = hist_picks[
            (hist_picks["season"] >= 2006) & hist_picks["margen_modelo"].notna()
            & hist_picks["spread_line"].notna()
        ].copy()
        d["edge"] = d["margen_modelo"] - d["spread_line"]
        d["al_local"] = d["edge"] > 0
        d["gano"] = d["cubre_local"].where(d["al_local"], d["cubre_visitante"])
        d["gano"] = d["gano"].mask(d["push_spread"].fillna(False))
        d["tramo"] = pd.cut(d["edge"].abs(), [0, 1, 2, 3, 4, 6, 100],
                            labels=["0–1", "1–2", "2–3", "3–4", "4–6", "6+"])
        res_edge = (d.groupby("tramo", observed=True)
                    .agg(ats=("gano", "mean"), n=("gano", "count")).reset_index())
        res_edge["ats"] = (res_edge["ats"] * 100).round(1)
        fig = px.bar(
            res_edge, x="tramo", y="ats", custom_data=["n"], text="ats",
            title="¿Un edge más grande acierta más? (spread)",
            labels={"tramo": "Tamaño del edge (puntos)", "ats": "% que cubrió"},
        )
        fig.update_traces(
            marker_color="#F2C14E", texttemplate="%{text:.0f}%", textposition="outside",
            hovertemplate="Edge %{x} pts: %{y:.1f}%<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=52.4, line_dash="dash", line_color="#00C46A",
                      annotation_text="52.4% = empatar con -110")
        fig.add_hline(y=50, line_dash="dot", line_color="rgba(255,255,255,.4)",
                      annotation_text="50% (azar)")
        mostrar_grafica(fig)
        st.caption(
            "Esta gráfica es la más honesta de todas: un edge grande **no** "
            "garantiza acertar más. Si la ventaja real existiera y el mercado "
            "no la viera, esta escalera subiría... y no sube."
        )


# ===========================================================================
# TAB 1B — REGISTRO DE PICKS (la auditoría: ¿pegó o no?)
# ===========================================================================
with tab_registro:
    st.header("📋 Registro de picks")

    st.markdown(
        "La **auditoría de todos los picks** del modelo — spread, totales y "
        "moneyline — cada uno con su resultado real (**¿pegó o no?**), el "
        "marcador y el **% de acierto por mercado**. Cada pick se emitió "
        "*walk-forward* (sin ver el futuro); aquí solo se comprueba qué pasó. "
        "Los partidos que aún no se juegan quedan **pendientes** hasta que se "
        "jueguen y pulses **🔄 Actualizar líneas**. Los picks nuevos se pueden "
        "**congelar al emitirse** (📌 registro fiel, con su línea exacta de "
        "aquel momento); los antiguos van marcados **🧮 Reconstruido** porque "
        "se recalculan con la línea actual — se mezclan lo menos posible."
    )

    c1, c2 = st.columns(2)
    umbral_reg = c1.select_slider(
        "Umbral de edge: spread y totales (puntos)",
        options=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0], value=2.0, key="umbral_reg",
        help="Igual que en la pestaña 🎯: solo aparecen los picks que lo superan.",
    )
    umbral_ml_reg = c2.select_slider(
        "Umbral de edge: moneyline (puntos de probabilidad)",
        options=[2, 3, 4, 5, 6, 7, 8], value=4, key="umbral_ml_reg",
        help="Ventaja mínima de la probabilidad calibrada sobre el mercado "
             "(sin vig), en puntos porcentuales.",
    )

    EMOJI_ESTADO = {
        "Pegó": "✅ Pegó", "No pegó": "❌ No pegó",
        "Push": "➖ Push", "Pendiente": "⏳ Pendiente",
    }

    era_reg = hist_picks[hist_picks["season"] >= 2006].copy()
    sigma_hoy, sigma_total_hoy = datos.sigma_actual(era_reg)
    futuros_reg = picks_futuros.copy()
    futuros_reg["sigma_modelo"] = sigma_hoy
    futuros_reg["sigma_total_modelo"] = sigma_total_hoy

    def _bloque_registro(picks, mercado, lado, texto_pick, lineas, lineas_num,
                         edges, edges_num, jugado):
        """Normaliza un bloque de picks a las columnas del registro.

        Además de lo visible (pick, línea y edge ya formateados), conserva lo
        NUMÉRICO (lado, línea, edge, probabilidades y game_id): es lo que viaja
        al registro fiel cuando se congelan los picks.
        """
        prob_modelo = (pd.to_numeric(picks["prob_modelo"], errors="coerce")
                       if "prob_modelo" in picks.columns
                       else pd.Series(float("nan"), index=picks.index))
        prob_mercado = (pd.to_numeric(picks["prob_mercado"], errors="coerce")
                        if "prob_mercado" in picks.columns
                        else pd.Series(float("nan"), index=picks.index))
        ev_num = (pd.to_numeric(picks["ev_estimado"], errors="coerce")
                  if "ev_estimado" in picks.columns
                  else pd.Series(float("nan"), index=picks.index))
        return pd.DataFrame({
            "temporada": picks["season"].astype(int),
            "semana": picks["week"].astype(int),
            "fecha": picks["gameday"].astype(str),
            "partido": (picks["away_team"].map(lambda e: APODOS.get(e, e))
                        + " @ "
                        + picks["home_team"].map(lambda e: APODOS.get(e, e))),
            "mercado": mercado,
            "lado": lado,
            "pick": texto_pick,
            "linea": lineas,
            "linea_num": pd.to_numeric(lineas_num, errors="coerce"),
            "edge": edges,
            "edge_num": pd.to_numeric(edges_num, errors="coerce"),
            "prob_modelo": prob_modelo,
            "prob_mercado": prob_mercado,
            "cuota": pd.to_numeric(picks["cuota"], errors="coerce"),
            "ev_num": ev_num,
            "gano": picks["gano"].astype("boolean"),
            "ganancia": pd.to_numeric(picks["ganancia"], errors="coerce"),
            "jugado": jugado,
            "game_id": picks["game_id"].astype(str),
            "equipo_local": picks["home_team"].astype(str),
            "equipo_visitante": picks["away_team"].astype(str),
        })

    hs = evaluar_spread(era_reg, umbral_reg)
    ht = evaluar_totales(era_reg, umbral_reg)
    hm = datos.evaluar_picks_ml(era_reg, umbral=umbral_ml_reg / 100.0)
    fs = evaluar_spread(futuros_reg, umbral_reg, calibrado=True)
    ft = evaluar_totales(futuros_reg, umbral_reg, calibrado=True)
    fm = datos.evaluar_picks_ml(futuros_reg, umbral=umbral_ml_reg / 100.0,
                                calibrado=True)
    # Motor F5: EV con push explícito, probabilidad de equilibrio y estado.
    # No cambia la selección; añade columnas para la interfaz y el registro.
    fs = motor_ev.decorar(fs, "spread")
    ft = motor_ev.decorar(ft, "total")
    fm = motor_ev.decorar(fm, "moneyline")

    def _texto_spread(picks):
        return pd.Series(
            [etiqueta_pick(eq, li) for eq, li in zip(picks["pick"], picks["linea_pick"])],
            index=picks.index)

    def _texto_ml(picks):
        return picks["pick"].map(lambda e: f"{APODOS.get(e, e)} gana")

    registro = pd.concat([
        _bloque_registro(
            hs, "Spread",
            hs["al_local"].map({True: "local", False: "visitante"}),
            _texto_spread(hs),
            hs["linea_pick"].map(lambda x: f"{x:+.1f}"),
            hs["linea_pick"],
            hs["edge"].map(lambda x: f"{x:+.1f} pts"),
            hs["edge"],
            True),
        _bloque_registro(
            ht, "Total",
            ht["al_over"].map({True: "over", False: "under"}),
            ht["pick"],
            ht["total_line"].map(lambda x: f"{x:.1f}"),
            ht["total_line"],
            ht["edge"].map(lambda x: f"{x:+.1f} pts"),
            ht["edge"],
            True),
        _bloque_registro(
            hm, "Moneyline",
            hm["al_local"].map({True: "local", False: "visitante"}),
            _texto_ml(hm),
            pd.Series("—", index=hm.index),
            pd.Series(float("nan"), index=hm.index),
            (hm["edge"] * 100).map(lambda x: f"{x:+.1f}%"),
            hm["edge"],
            True),
        _bloque_registro(
            fs, "Spread",
            fs["al_local"].map({True: "local", False: "visitante"}),
            _texto_spread(fs),
            fs["linea_pick"].map(lambda x: f"{x:+.1f}"),
            fs["linea_pick"],
            fs["edge"].map(lambda x: f"{x:+.1f} pts"),
            fs["edge"],
            False),
        _bloque_registro(
            ft, "Total",
            ft["al_over"].map({True: "over", False: "under"}),
            ft["pick"],
            ft["total_line"].map(lambda x: f"{x:.1f}"),
            ft["total_line"],
            ft["edge"].map(lambda x: f"{x:+.1f} pts"),
            ft["edge"],
            False),
        _bloque_registro(
            fm, "Moneyline",
            fm["al_local"].map({True: "local", False: "visitante"}),
            _texto_ml(fm),
            pd.Series("—", index=fm.index),
            pd.Series(float("nan"), index=fm.index),
            (fm["edge"] * 100).map(lambda x: f"{x:+.1f}%"),
            fm["edge"],
            False),
    ], ignore_index=True)

    registro["estado"] = datos.estado_picks(registro["gano"], registro["jugado"])
    registro["Estado"] = registro["estado"].map(EMOJI_ESTADO)
    registro["origen"] = "🧮 Reconstruido"
    registro = registro.sort_values(
        ["temporada", "semana", "partido"], ascending=[False, False, True]
    )

    COLUMNAS_TABLA = {
        "fecha": "Fecha", "partido": "Partido", "mercado": "Mercado",
        "origen": "Origen", "pick": "Pick", "linea": "Línea", "edge": "Edge",
        "cuota": "Cuota", "ev_num": "EV $1", "Estado": "Estado",
        "ganancia": "Ganancia $1",
    }
    CONFIG_TABLA = {
        "Cuota": st.column_config.NumberColumn(format="%+.0f"),
    }

    def _tabla_picks(datos_vista):
        """Tabla de picks lista para mostrar (ganancia vacía si pendiente).

        `EV $1` solo aparece donde el motor F5 dejó su EV (la jornada
        pendiente); en lo histórico va vacío — no se recalcula nada.
        """
        v = datos_vista[["fecha", "partido", "mercado", "origen", "pick", "linea",
                         "edge", "cuota", "ev_num", "Estado", "ganancia"]].rename(columns=COLUMNAS_TABLA)
        v = v.copy()
        pendiente = v["Estado"].str.contains("Pendiente")
        v["Ganancia $1"] = [
            "" if es_pendiente or pd.isna(g) else f"{g:+.2f}"
            for es_pendiente, g in zip(pendiente, v["Ganancia $1"])
        ]
        v["EV $1"] = [
            f"{x:+.3f}" if pd.notna(x) else ""
            for x in pd.to_numeric(v["EV $1"], errors="coerce")
        ]
        return v

    # --- La jornada, pick a pick -----------------------------------------
    st.subheader("🗓️ La jornada, pick a pick")

    temporada_actual = int(calendario["season"].max())
    de_temporada = registro[registro["temporada"] == temporada_actual]
    pendientes_sem = de_temporada[de_temporada["estado"] == "Pendiente"]
    if len(pendientes_sem):
        semana_actual = int(pendientes_sem["semana"].min())
    else:
        semana_actual = int(de_temporada["semana"].max())
    opciones_sem = [semana_actual] + sorted(
        s for s in de_temporada["semana"].unique() if s != semana_actual
    )

    def _etiqueta_semana(s):
        curso = " · en curso" if s == semana_actual else ""
        return f"Semana {s}{curso}"

    sem = st.selectbox("Jornada a auditar:", opciones_sem,
                       format_func=_etiqueta_semana, key="semana_registro")
    de_la_semana = de_temporada[de_temporada["semana"] == sem]

    if len(de_la_semana):
        pegados = int((de_la_semana["estado"] == "Pegó").sum())
        fallados = int((de_la_semana["estado"] == "No pegó").sum())
        pendientes = int((de_la_semana["estado"] == "Pendiente").sum())
        decididas = pegados + fallados
        resueltas = de_la_semana[de_la_semana["estado"] != "Pendiente"]
        roi_sem = float(resueltas["ganancia"].mean()) * 100 if len(resueltas) else float("nan")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Picks de la jornada", len(de_la_semana), border=True,
                  help="Spread + totales + moneyline que superan el umbral.")
        m2.metric("Marcador (pegados–fallados)", f"{pegados}–{fallados}", border=True,
                  help="Solo picks ya resueltos. Los push devuelven el dinero y no cuentan.")
        m3.metric("% de acierto", f"{pegados / decididas * 100:.1f}%" if decididas else "—",
                  border=True,
                  help="Pegados entre los resueltos (sin push ni pendientes).")
        m4.metric("Pendientes", pendientes, border=True,
                  help="Se resuelven solos cuando la jornada se juega y actualizas las líneas.")
        if np.isfinite(roi_sem):
            st.caption(f"ROI de la jornada resuelta: **{roi_sem:+.1f}%** por cada dólar "
                       "apostado (los push cuentan como 0, igual que en el resto de la app).")

        st.dataframe(_tabla_picks(de_la_semana), hide_index=True, width="stretch",
                     column_config=CONFIG_TABLA)
    else:
        st.info("Esta jornada no tiene picks con el umbral elegido.")

    # --- Registro fiel: picks congelados al emitirse (inmutable) ----------
    st.subheader("📌 Registro fiel (picks congelados)")
    st.markdown(
        "El **registro fiel** guarda cada pick con la **línea, cuota y "
        "probabilidad exactas del momento en que se emitió**: si después el "
        "mercado mueve las líneas, aquí no se reescribe nada (y el resultado "
        "se decide con la línea congelada, no con la de hoy). Congelar es un "
        "acto explícito: así queda claro qué se emitió, cuándo y a qué precio. "
        "Desde el 16/10/2026 lo que se congela es la **probabilidad calibrada** "
        "(`srs-v2+cal-f4-1`, la corrección medida en la auditoría F4) y el "
        "**EV con push explícito** (motor F5: si el resultado cae justo en la "
        "línea, la apuesta se devuelve y no suma ni resta); los picks "
        "anteriores conservan la probabilidad y el EV con los que se emitieron."
    )

    existente_fiel = datos.cargar_registro_picks()
    nuevas_fiel = datos.registro_desde_picks(
        registro[~registro["jugado"]].rename(columns={"pick": "seleccion"}),
        version=f"{datos.VERSION_MODELO}+{calibracion.VERSION_CALIBRACION}")
    ids_ya = set(existente_fiel["id"]) if len(existente_fiel) else set()
    n_nuevos_fiel = int((~nuevas_fiel["id"].isin(ids_ya)).sum()) if len(nuevas_fiel) else 0

    if not len(nuevas_fiel):
        st.info("Ahora mismo no hay picks pendientes que congelar (no hay "
                "jornada con líneas publicadas o ninguno supera el umbral).")
    elif not n_nuevos_fiel:
        st.caption("✓ Los picks pendientes de esta jornada ya están congelados. "
                   "No hay nada nuevo que registrar.")
    else:
        if st.button(
            f"📌 Congelar {n_nuevos_fiel} picks de la jornada (línea y cuota de este momento)",
            help="Guarda una fotografía inmutable: selección, línea, cuota, "
                 "probabilidad, edge y EV quedan fijados tal como están ahora. "
                 "Volver a pulsar no cambia lo ya congelado.",
        ):
            existente_fiel, nuevos_fiel_n, repetidos_fiel = datos.capturar_registro_picks(
                nuevas_fiel)
            aviso = f"✅ Congelados {nuevos_fiel_n} picks nuevos."
            if repetidos_fiel:
                aviso += f" ({repetidos_fiel} ya estaban y no se han tocado.)"
            st.success(aviso)

    if len(existente_fiel):
        fiel = datos.evaluar_registro_fiel(existente_fiel, calendario)
        peg_fiel = int((fiel["estado"] == "Pegó").sum())
        fal_fiel = int((fiel["estado"] == "No pegó").sum())
        push_fiel = int((fiel["estado"] == "Push").sum())
        pen_fiel = int((fiel["estado"] == "Pendiente").sum())
        resueltas_fiel = fiel[fiel["estado"] != "Pendiente"]
        roi_fiel = (float(resueltas_fiel["ganancia"].mean()) * 100
                    if len(resueltas_fiel) and resueltas_fiel["ganancia"].notna().any()
                    else float("nan"))
        roi_txt = (f"ROI **{roi_fiel:+.1f}%** por $1 (solo resueltos con cuota real; "
                   "sin cuota no se inventa)"
                   if np.isfinite(roi_fiel) else "ROI — (aún sin resueltos con cuota)")
        st.caption(
            f"Congelados: **{len(fiel)}** · resueltos {peg_fiel + fal_fiel + push_fiel} "
            f"· marcador **{peg_fiel}–{fal_fiel}** · push {push_fiel} · "
            f"pendientes {pen_fiel} · {roi_txt}."
        )

        def _tabla_fiel(fiel_df):
            """Tabla del registro fiel: lo congelado + el resultado derivado."""
            vista_f = pd.DataFrame({
                "Capturado": pd.to_datetime(fiel_df["capturado_en"], errors="coerce")
                               .dt.strftime("%d/%m %H:%M"),
                "Partido": (fiel_df["equipo_visitante"].map(lambda e: APODOS.get(e, e))
                            + " @ "
                            + fiel_df["equipo_local"].map(lambda e: APODOS.get(e, e))),
                "Mercado": fiel_df["mercado"],
                "Pick": fiel_df["seleccion"],
                "Línea": pd.to_numeric(fiel_df["linea"], errors="coerce"),
                "Cuota": pd.to_numeric(fiel_df["cuota"], errors="coerce"),
                "Prob. modelo": pd.to_numeric(fiel_df["prob_modelo"], errors="coerce") * 100,
                "Prob. sin vig": pd.to_numeric(fiel_df["prob_sin_vig"], errors="coerce") * 100,
            })
            vista_f["Edge"] = [
                f"{e:+.1f} pp" if m == "Moneyline" else f"{e:+.1f} pts"
                for e, m in zip(pd.to_numeric(fiel_df["edge"], errors="coerce"),
                                fiel_df["mercado"])
            ]
            ev_fiel = pd.to_numeric(fiel_df["ev"], errors="coerce")
            vista_f["EV $1"] = [f"{x:+.3f}" if pd.notna(x) else "" for x in ev_fiel]
            vista_f["Estado"] = fiel_df["estado"].map(EMOJI_ESTADO)
            vista_f["Ganancia $1"] = [
                "" if est == "Pendiente" or pd.isna(g)
                else ("$0.00" if est == "Push" else f"{g:+.2f}")
                for est, g in zip(fiel_df["estado"],
                                  pd.to_numeric(fiel_df["ganancia"], errors="coerce"))
            ]
            vista_f = vista_f.assign(_orden=fiel_df["capturado_en"].astype(str))
            return vista_f.sort_values("_orden", ascending=False).drop(columns="_orden")

        st.dataframe(
            _tabla_fiel(fiel), hide_index=True, width="stretch",
            column_config={
                "Línea": st.column_config.NumberColumn(format="%+.1f"),
                "Cuota": st.column_config.NumberColumn(format="%+.0f"),
                "Prob. modelo": st.column_config.NumberColumn(format="%.1f%%"),
                "Prob. sin vig": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            "**«Sin vig»** = probabilidad implícita del mercado quitándole la "
            "comisión (la referencia justa). **EV $1** = valor esperado por "
            "dólar con **push explícito** (el push devuelve el importe) según "
            "la probabilidad calibrada congelada; los picks capturados desde "
            "F5 lo guardan así. Un EV positivo no valida la apuesta: la "
            "validación de la estrategia es prospectiva."
        )
    else:
        st.caption(
            "Todavía no hay ningún pick capturado: los primeros serán los que "
            "congeles a partir de ahora. Los picks antiguos no se pueden "
            "recuperar como se emitieron (el archivo histórico no guardaba la "
            "línea del momento): van marcados como **🧮 Reconstruido** y se "
            "recalculan con la línea actual de la tabla de abajo."
        )

    # --- Acumulado --------------------------------------------------------
    st.subheader("📊 Acumulado: cómo va de verdad")

    alcance = st.radio(
        "Alcance:",
        [f"Temporada {temporada_actual}", "Histórico completo (desde 2006)"],
        horizontal=True, key="alcance_registro",
    )
    sub = de_temporada if alcance.startswith("Temporada") else registro

    if len(sub):
        peg = int((sub["estado"] == "Pegó").sum())
        fal = int((sub["estado"] == "No pegó").sum())
        pen = int((sub["estado"] == "Pendiente").sum())
        pus = int((sub["estado"] == "Push").sum())
        resueltas_sub = sub[sub["estado"] != "Pendiente"]
        acierto_sub = 100.0 * peg / (peg + fal) if (peg + fal) else float("nan")
        roi_sub = float(resueltas_sub["ganancia"].mean()) * 100 if len(resueltas_sub) else float("nan")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Picks totales", len(sub), border=True,
                  help="Todos los picks emitidos (los pendientes no cuentan en el %).")
        m2.metric("Marcador", f"{peg}–{fal}", border=True,
                  help=f"Pegados–fallados. Push: {pus} (no cuentan).")
        m3.metric("% de acierto", f"{acierto_sub:.1f}%" if np.isfinite(acierto_sub) else "—",
                  border=True)
        m4.metric("ROI por $1", f"{roi_sub:+.1f}%" if np.isfinite(roi_sub) else "—",
                  border=True, help="Sobre los picks resueltos; push = $0.")

        resumen_reg = datos.resumen_picks(sub)
        resumen_reg = resumen_reg[["mercado", "picks", "pegados", "fallados", "push",
                                   "pendientes", "pct_acierto", "roi"]].rename(columns={
            "mercado": "Mercado", "picks": "Picks", "pegados": "Pegaron",
            "fallados": "Fallaron", "push": "Push", "pendientes": "Pendientes",
            "pct_acierto": "% acierto", "roi": "ROI %",
        })
        st.dataframe(
            resumen_reg, hide_index=True, width="stretch",
            column_config={
                "% acierto": st.column_config.NumberColumn(format="%.1f%%"),
                "ROI %": st.column_config.NumberColumn(format="%+.1f%%"),
            },
        )
        st.caption(
            "El **% de acierto** se calcula sobre las apuestas decididas (los push "
            "devuelven el dinero y quedan fuera). El **ROI** promedia las resueltas "
            "con los push como $0. Si sale en rojo, es la realidad: batir al "
            "mercado es dificilísimo — eso también se aprende."
        )
    else:
        st.info("Todavía no hay picks para este alcance.")

    # --- Calidad de las probabilidades (Brier, Log Loss, calibración) -----
    st.subheader("📐 ¿Dicen la verdad las probabilidades? (Brier y Log Loss)")
    st.markdown(
        "Una probabilidad solo sirve si **dice la verdad**: si el modelo dice "
        "60% y esos partidos se ganan 40% de las veces, engaña (y cualquier "
        "«valor esperado» calculado con ella, también). Dos números lo miden "
        "(**menor = mejor**): **Brier** (error cuadrático medio) y **Log Loss** "
        "(castiga sobre todo la confianza mal puesta). Referencias honestas: "
        "decir 50% a todo da Brier **0.25** y el rival a batir es el **mercado "
        "sin vig**. Se calcula sobre TODOS los partidos jugados desde 2006 "
        "(los push quedan fuera)."
    )

    p_local_spread = datos.probabilidad_supera(
        era_reg["margen_modelo"], era_reg["spread_line"], era_reg["sigma_modelo"])
    p_over_total = datos.probabilidad_supera(
        era_reg["total_modelo"], era_reg["total_line"], era_reg["sigma_total_modelo"])
    p_local_ml = datos.probabilidades_ml(
        era_reg["margen_modelo"], era_reg["sigma_modelo"])[0]
    po_cal = datos._prob_implicita(era_reg["over_odds"])
    pu_cal = datos._prob_implicita(era_reg["under_odds"])
    p_mercado_total = po_cal / (po_cal + pu_cal)
    METRICAS_POR_MERCADO = {
        "Spread": (p_local_spread, era_reg["prob_local_spread_sin_vig"],
                   era_reg["cubre_local"]),
        "Total": (p_over_total, p_mercado_total, era_reg["over"]),
        "Moneyline": (p_local_ml, era_reg["prob_local_sin_vig"],
                      era_reg["gano_local"]),
    }

    filas_calidad = []
    for nombre_cal, (p_modelo_cal, p_mercado_cal, resultado_cal) in METRICAS_POR_MERCADO.items():
        y_cal = resultado_cal.astype(float)
        filas_calidad.append({
            "Mercado": nombre_cal,
            "Partidos": int((p_modelo_cal.notna() & y_cal.notna()).sum()),
            "Brier modelo": datos.brier_score(p_modelo_cal, y_cal),
            "Brier mercado": datos.brier_score(p_mercado_cal, y_cal),
            "LogLoss modelo": datos.log_loss(p_modelo_cal, y_cal),
            "LogLoss mercado": datos.log_loss(p_mercado_cal, y_cal),
        })
    st.dataframe(
        pd.DataFrame(filas_calidad), hide_index=True, width="stretch",
        column_config={
            "Partidos": st.column_config.NumberColumn(format="%d"),
            "Brier modelo": st.column_config.NumberColumn(format="%.4f"),
            "Brier mercado": st.column_config.NumberColumn(format="%.4f"),
            "LogLoss modelo": st.column_config.NumberColumn(format="%.4f"),
            "LogLoss mercado": st.column_config.NumberColumn(format="%.4f"),
        },
    )
    st.caption(
        "Si el modelo saca peor Brier que el mercado (lo normal hoy), sus "
        "probabilidades todavía no sirven para calcular un valor esperado "
        "fiable. Reconocerlo es parte del juego."
    )

    mercado_cal = st.selectbox(
        "Curva de calibración:", ["Moneyline", "Spread", "Total"],
        key="mercado_calibracion",
        help="Probabilidad dicha (eje X) frente a frecuencia real (eje Y). "
             "Pegado a la diagonal = probabilidades honestas.",
    )
    p_modelo_cal, p_mercado_cal, resultado_cal = METRICAS_POR_MERCADO[mercado_cal]
    y_cal = resultado_cal.astype(float)
    cortes_cal = (0.0, 0.35, 0.45, 0.50, 0.55, 0.65, 1.0)
    tabla_modelo = datos.tabla_calibracion(p_modelo_cal, y_cal, cortes_cal)
    tabla_mercado = datos.tabla_calibracion(p_mercado_cal, y_cal, cortes_cal)

    fig_cal = go.Figure()
    fig_cal.add_trace(go.Scatter(
        x=[0, 100], y=[0, 100], mode="lines", name="Ideal",
        line=dict(color="rgba(255,255,255,.35)", dash="dash", width=1.5),
        hoverinfo="skip",
    ))
    for tabla_cal, nombre_serie, color_serie in (
        (tabla_modelo, "Modelo", "#F2C14E"),
        (tabla_mercado, "Mercado (sin vig)", "#00C46A"),
    ):
        fig_cal.add_trace(go.Scatter(
            x=tabla_cal["prob_media"] * 100, y=tabla_cal["real"] * 100,
            mode="lines+markers", name=nombre_serie,
            marker=dict(size=9, color=color_serie),
            line=dict(width=2.5, color=color_serie),
            customdata=tabla_cal["n"],
            hovertemplate=("%{x:.1f}% dicho → %{y:.1f}% real<br>n = %{customdata}"
                           "<extra>" + nombre_serie + "</extra>"),
        ))
    fig_cal.update_xaxes(title_text="Probabilidad dicha (%)", range=[0, 100])
    fig_cal.update_yaxes(title_text="Frecuencia real (%)", range=[0, 100])
    mostrar_grafica(fig_cal)
    st.caption(
        "**Cómo leerla:** si el modelo se aleja de la diagonal, miente — por "
        "encima en la zona baja = promete más de lo que cumple; por debajo en "
        "la zona alta = se queda corto. El mercado casi siempre va pegado a la "
        "diagonal: es el listón real de esta app."
    )

    # --- Todos los picks ---------------------------------------------------
    st.subheader("🧾 Todos los picks, uno a uno")

    f1, f2, f3 = st.columns(3)
    temporadas_disp = ["Todas"] + sorted(
        (int(t) for t in registro["temporada"].unique()), reverse=True)
    equipos_disp = ["Todos"] + sorted({
        p for partido in registro["partido"] for p in partido.split(" @ ")
    })
    temp_sel = f1.selectbox("Temporada:", temporadas_disp, key="temp_registro")
    equipo_sel = f2.selectbox("Equipo:", equipos_disp, key="equipo_registro")
    mercado_sel = f3.selectbox("Mercado:", ["Todos", "Spread", "Total", "Moneyline"],
                               key="mercado_registro")

    vista = registro
    if temp_sel != "Todas":
        vista = vista[vista["temporada"] == temp_sel]
    if equipo_sel != "Todos":
        vista = vista[vista["partido"].str.contains(equipo_sel, regex=False)]
    if mercado_sel != "Todos":
        vista = vista[vista["mercado"] == mercado_sel]

    MAX_FILAS = 300
    st.dataframe(_tabla_picks(vista.head(MAX_FILAS)), hide_index=True, width="stretch",
                 column_config=CONFIG_TABLA)
    st.caption(
        f"Mostrando {min(len(vista), MAX_FILAS)} de {len(vista)} picks (temporada y "
        "semana más nuevas primero). Esta lista es la prueba de todo lo demás: "
        "cada pick, con su resultado real, sin borrar los fallos."
    )


# ===========================================================================
# TAB 2 — ATS POR EQUIPO
# ===========================================================================
with tab_ats:
    st.header("📈 ATS por equipo (contra la línea)")

    st.markdown(
        "**ATS** = *against the spread*: no es si el equipo gana, es si **cubre "
        "la línea**. Si el local es favorito por 3 y gana por 1, ganó el partido "
        "pero no cubrió: para el mercado, perdió."
    )

    apuestas_todas = partidos[
        partidos["cubre_favorito"].notna() & partidos["over"].notna()
    ].copy()
    reg = registros_ats(df_vista)

    if len(reg):
        mejor = reg.sort_values("pct", ascending=False).iloc[0]
        peor = reg.sort_values("pct", ascending=True).iloc[0]
    else:
        mejor = peor = None

    n1, n2, n3, n4 = st.columns(4)
    n1.metric(
        "Partidos con línea (filtro)", int(len(df_vista[df_vista["spread_line"].notna()])),
        border=True,
        help="Partidos de la temporada/filtro actual comparables contra la línea.",
    )
    n2.metric(
        "Push (línea clavada)",
        f"{df_vista['push_spread'].fillna(False).mean() * 100:.1f}%"
        if len(df_vista) else "—",
        border=True,
        help="Partidos que terminaron EXACTAMENTE en la línea. Devuelven el "
             "dinero. Por eso las casas prefieren líneas .5.",
    )
    n3.metric(
        "Mejor ATS", f"{mejor['apodo']} · {mejor['pct']:.0f}%" if mejor is not None else "—",
        border=True,
        help="Mejor % cubriendo la línea en el filtro actual (puede ser racha de suerte).",
    )
    n4.metric(
        "Peor ATS", f"{peor['apodo']} · {peor['pct']:.0f}%" if peor is not None else "—",
        border=True,
        help="Peor % cubriendo la línea en el filtro actual (puede ser mala suerte).",
    )

    with st.expander("📅 Todos los partidos de la temporada (con línea y resultado ATS)"):
        cols_mostrar = ["week", "weekday", "gametime", "away_team", "home_team",
                        "away_score", "home_score", "spread_line"]
        tabla = df_vista[[c for c in cols_mostrar if c in df_vista.columns]].copy()
        tabla["Cubrió"] = np.select(
            [
                df_vista["push_spread"].fillna(False),
                df_vista["cubre_local"].fillna(False),
                df_vista["cubre_visitante"].fillna(False),
            ],
            ["Push (todos)", "Local", "Visitante"],
            default="—",
        )
        for equipo_col in ("away_team", "home_team"):
            tabla[equipo_col] = tabla[equipo_col].map(lambda e: APODOS.get(e, e))
        tabla["weekday"] = tabla["weekday"].replace(DIAS_ES)
        st.dataframe(
            tabla.rename(columns={
                "week": "Semana", "weekday": "Día", "gametime": "Hora",
                "away_team": "Visitante", "home_team": "Local",
                "away_score": "Pts visitante", "home_score": "Pts local",
                "spread_line": "Spread",
            }),
            width="stretch", hide_index=True, height=420,
            column_config={
                "Semana": st.column_config.NumberColumn(format="%d"),
                "Hora": st.column_config.TextColumn(help="Hora de inicio en el Este (ET)."),
                "Pts visitante": st.column_config.NumberColumn(format="%d"),
                "Pts local": st.column_config.NumberColumn(format="%d"),
                "Spread": st.column_config.NumberColumn(
                    format="%.1f",
                    help="Positivo: el local es favorito (el visitante es underdog). "
                         "Negativo: el local es underdog.",
                ),
            },
        )

    if len(reg):
        # Gráfica: récord ATS por equipo
        r = reg.sort_values("pct")
        fig = px.bar(
            r, x="pct", y="apodo", orientation="h",
            custom_data=["cubiertas", "falladas", "pushes"],
            title="% de veces que cada equipo cubrió la línea",
            labels={"pct": "% que cubrió", "apodo": ""},
        )
        fig.update_traces(
            marker_color=color_equipos(r["equipo"]),
            hovertemplate="%{y}: %{x:.1f}%<br>Cubrió %{customdata[0]}, falló "
                          "%{customdata[1]}, push %{customdata[2]}<extra></extra>",
        )
        fig.add_vline(x=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        mostrar_grafica(fig, alto=max(430, 14 * len(r) + 90))
        st.caption(
            "La línea se mueve justo para que esto ronde el 50%. Los extremos "
            "(muy por encima o por debajo) suelen ser **rachas**, no virtudes: "
            "mira el nº de partidos en el tooltip antes de creerte un 70%."
        )

    # Mapa de calor ATS de la temporada
    st.subheader(f"🔥 Mapa de calor ATS — temporada {temporada_sel}")
    zv, zt = matriz_ats(df_temp)
    if len(zv):
        reg_temp = registros_ats(df_temp).set_index("equipo")["pct"]
        orden = reg_temp.sort_values(ascending=False).index.tolist()
        orden = [e for e in orden if e in zv.index]
        semanas = list(zv.columns)
        fig = go.Figure(go.Heatmap(
            z=zv.reindex(orden).to_numpy(dtype=float),
            x=[f"S{int(s)}" for s in semanas],
            y=[APODOS.get(e, e) for e in orden],
            customdata=zt.reindex(orden).to_numpy(),
            colorscale=[
                [0.0, "#FF6B6B"], [0.499, "#FF6B6B"],
                [0.5, "#5B6B8C"], [0.501, "#00C46A"], [1.0, "#00C46A"],
            ],
            zmin=-1, zmax=1, showscale=False,
            hovertemplate="%{y} · %{x}<br>%{customdata}<extra></extra>",
            xgap=2, ygap=3,
        ))
        mostrar_grafica(fig, alto=max(560, 20 * len(orden) + 120))
        st.caption(
            "Verde = cubrió la línea · rojo = no la cubrió · gris = push · "
            "hueco = no jugó. Equipos ordenados por % de la temporada. Este mapa "
            "no depende de los filtros de la barra lateral (siempre muestra la "
            "temporada completa) para que veas el cuadro entero."
        )

    # Favoritos cubriendo según el tamaño de la línea (toda la serie)
    izq, der = st.columns(2)
    with izq:
        tam = apuestas_todas.copy()
        tam["tramo"] = pd.cut(tam["spread_line"].abs(), [0, 1, 3, 6.5, 10, 100],
                              labels=["0–1", "1.5–3", "3.5–6.5", "7–10", "10.5+"])
        res_tam = (tam.groupby("tramo", observed=True)
                   .agg(cubre=("cubre_favorito", "mean"), n=("cubre_favorito", "size"))
                   .reset_index())
        res_tam["cubre"] = (res_tam["cubre"] * 100).round(1)
        fig = px.bar(
            res_tam, x="tramo", y="cubre", custom_data=["n"], text="cubre",
            title="% de favoritos que cubren, por tamaño de línea",
            labels={"tramo": "Favoritismo (puntos)", "cubre": "% que cubrió"},
        )
        fig.update_traces(
            marker_color="#00C46A", texttemplate="%{text:.0f}%", textposition="outside",
            hovertemplate="Spread %{x}: %{y:.1f}%<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        mostrar_grafica(fig)
        st.caption("Toda la serie (1999–hoy). Ni los favoritos grandes ni los "
                   "pequeños cubren de forma sistemática.")
    with der:
        por_temp = (apuestas_todas.groupby("season")
                    .agg(cubre=("cubre_favorito", "mean"), n=("cubre_favorito", "size"))
                    .reset_index())
        por_temp["cubre"] = (por_temp["cubre"] * 100).round(1)
        fig = px.line(
            por_temp, x="season", y="cubre", markers=True, custom_data=["n"],
            title="% de favoritos que cubren, por temporada",
            labels={"season": "Temporada", "cubre": "% que cubrió"},
        )
        fig.update_traces(
            line=dict(width=3, color="#4C9AFF"), marker=dict(size=7, color="#4C9AFF"),
            hovertemplate="Temporada %{x}: %{y:.1f}%<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        fig.update_xaxes(dtick=2)
        mostrar_grafica(fig)
        st.caption("Temporada tras temporada, el resultado se pasea alrededor "
                   "del 50%: el precio manda.")


# ===========================================================================
# TAB 3 — TOTALES Y CLIMA
# ===========================================================================
with tab_totales:
    st.header("🎲 Totales (más/menos) y clima")

    st.markdown(
        "El mercado del **total** es la línea de puntos sumados. Aquí ves "
        "quiénes empujan los partidos hacia arriba (overs), qué pesa el clima "
        "y cómo de bien clava el mercado la línea semana a semana."
    )

    tot_eq = totales_por_equipo(df_vista)
    sob = df_vista[df_vista["over"].notna()]

    interior = partidos[partidos["interior"].fillna(False)]
    exterior = partidos[~partidos["interior"].fillna(False)]
    pts_interior = interior["total_puntos"].mean() if len(interior) else float("nan")
    pts_exterior = exterior["total_puntos"].mean() if len(exterior) else float("nan")

    t1, t2, t3, t4 = st.columns(4)
    t1.metric(
        "Overs del total", f"{sob['over'].mean() * 100:.1f}%" if len(sob) else "—",
        border=True,
        help="Partidos filtrados que superaron la línea del total (sin push).",
    )
    t2.metric(
        "Puntos por partido",
        f"{df_vista['total_puntos'].mean():.1f}" if len(df_vista) else "—",
        border=True,
        help="Media real de puntos anotados en los partidos filtrados.",
    )
    t3.metric(
        "Puntos · bajo techo", f"{pts_interior:.1f}" if len(interior) else "—",
        border=True,
        help="Media en estadios con techo cerrado (toda la serie).",
    )
    t4.metric(
        "Puntos · intemperie", f"{pts_exterior:.1f}" if len(exterior) else "—",
        border=True,
        help="Media al aire libre (toda la serie). El clima suele venir ya "
             "cobrado en la línea.",
    )

    izq, der = st.columns(2)
    with izq:
        if len(tot_eq):
            r = tot_eq.sort_values("pct")
            fig = px.bar(
                r, x="pct", y="apodo", orientation="h", custom_data=["overs", "n"],
                title="% de overs por equipo (temporada/filtro)",
                labels={"pct": "% over", "apodo": ""},
            )
            fig.update_traces(
                marker_color=color_equipos(r["equipo"]),
                hovertemplate="%{y}: %{x:.1f}%<br>%{customdata[0]} de "
                              "%{customdata[1]} partidos<extra></extra>",
            )
            fig.add_vline(x=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
            mostrar_grafica(fig, alto=max(430, 14 * len(r) + 90))
    with der:
        semana = (df_base.groupby("week")
                  .agg(puntos=("total_puntos", "mean"), linea=("total_line", "mean"),
                       partidos=("total_puntos", "size"))
                  .reset_index())
        df_largo = pd.concat([
            semana[["week", "puntos", "partidos"]].rename(columns={"puntos": "valor"})
            .assign(serie="Puntos reales"),
            semana[["week", "linea", "partidos"]].rename(columns={"linea": "valor"})
            .assign(serie="Línea del mercado"),
        ])
        fig = px.line(
            df_largo, x="week", y="valor", color="serie", markers=True,
            color_discrete_map={"Puntos reales": "#00C46A", "Línea del mercado": "#4C9AFF"},
            title="Puntos por semana: realidad vs. línea del mercado",
            labels={"week": "Semana", "valor": "Puntos por partido", "serie": ""},
        )
        fig.update_traces(line=dict(width=2.5), marker=dict(size=7))
        mostrar_grafica(fig, alto=max(430, 14 * len(tot_eq) + 90))
        st.caption(
            "La línea azul es lo que el mercado esperaba; la verde, lo que pasó. "
            "Van pegadas: el precio es un pronóstico muy bueno."
        )

    # Clima: viento y temperatura (solo partidos al aire libre con dato)
    fuera = partidos[partidos["wind"].notna()].copy()
    izq, der = st.columns(2)
    with izq:
        fuera["tramo"] = pd.cut(fuera["wind"], [0, 5, 10, 15, 100],
                                labels=["0–5", "5–10", "10–15", "15+"])
        res_v = (fuera.groupby("tramo", observed=True)
                 .agg(puntos=("total_puntos", "mean"), over=("over", "mean"),
                      n=("over", "count"))
                 .reset_index())
        res_o = res_v.copy()
        res_o["over"] = (res_o["over"] * 100).round(1)
        fig = px.bar(
            res_o, x="tramo", y="over", custom_data=["n"], text="over",
            title="% de overs según el viento (al aire libre)",
            labels={"tramo": "Viento (mph)", "over": "% over"},
        )
        fig.update_traces(
            marker_color="#4C9AFF", texttemplate="%{text:.0f}%", textposition="outside",
            hovertemplate="Viento %{x} mph: %{y:.1f}% over<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        mostrar_grafica(fig)
    with der:
        fig = px.bar(
            res_v, x="tramo", y="puntos", custom_data=["n"], text="puntos",
            title="Puntos por partido según el viento (al aire libre)",
            labels={"tramo": "Viento (mph)", "puntos": "Puntos por partido"},
        )
        fig.update_traces(
            marker_color="#B48EFF", texttemplate="%{text:.1f}", textposition="outside",
            hovertemplate="Viento %{x} mph: %{y:.1f} puntos<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        mostrar_grafica(fig)
    st.caption(
        "Con viento fuerte se anotan 3–4 puntos menos por partido... y aun así "
        "el % de overs no se dispara: la línea ya suele venir ajustada al clima "
        "(y solo hay dato de viento para partidos al aire libre: ~2 de cada 3)."
    )

    # Temperatura (solo exteriores con dato)
    frio = partidos[partidos["temp"].notna()].copy()
    if len(frio):
        frio["tramo"] = pd.cut(frio["temp"], [0, 32, 50, 70, 200],
                               labels=["< 32°F", "32–49°F", "50–69°F", "70°F+"])
        res_t = (frio.groupby("tramo", observed=True)
                 .agg(puntos=("total_puntos", "mean"), over=("over", "mean"),
                      n=("over", "count"))
                 .reset_index())
        res_t["puntos"] = res_t["puntos"].round(1)
        fig = px.bar(
            res_t, x="tramo", y="puntos", custom_data=["n"], text="puntos",
            title="Puntos por partido según la temperatura (exteriores)",
            labels={"tramo": "Temperatura", "puntos": "Puntos por partido"},
        )
        fig.update_traces(
            marker_color="#F2C14E", texttemplate="%{text:.1f}", textposition="outside",
            hovertemplate="%{x}: %{y:.1f} puntos<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        mostrar_grafica(fig, alto=380)
        st.caption(
            "El frío baja el total medio y el calor lo sube, pero la línea del "
            "mercado ya lo sabe: la pregunta correcta nunca es «¿hace frío?», "
            "sino «¿está el frío **ya** en el precio?»."
        )


# ===========================================================================
# TAB 4 — NÚMEROS CLAVE
# ===========================================================================
with tab_clave:
    st.header("🧮 Números clave y descanso")
    st.caption(
        "Esta pestaña usa **todo el histórico**: los números clave (3 y 7), el "
        "descanso y el primetime son propiedades del juego, y se ven mejor con "
        "miles de partidos que con una temporada suelta."
    )

    # Métricas de números clave
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Margen exacto = 3", f"{(partidos['margen'] == 3).mean() * 100:.1f}%",
        border=True,
        help="Gol de campo: el resultado más habitual de la NFL.",
    )
    k2.metric(
        "Margen exacto = 7", f"{(partidos['margen'] == 7).mean() * 100:.1f}%",
        border=True,
        help="Touchdown + punto extra.",
    )
    lineas_enteras = partidos[
        partidos["spread_line"].notna() & (partidos["spread_line"] % 1 == 0)
        & (partidos["spread_line"] != 0)
    ]
    k3.metric(
        "Push con línea entera",
        f"{lineas_enteras['push_spread'].fillna(False).mean() * 100:.1f}%"
        if len(lineas_enteras) else "—",
        border=True,
        help="Se clavó la línea exacta: la apuesta devuelve el dinero.",
    )
    k4.metric(
        "Push con línea .5", "0.0%", border=True,
        help="Imposible por diseño: por eso las casas prefieren líneas .5.",
    )

    # Gráfica 1: distribución de márgenes
    fig = px.histogram(
        partidos[partidos["margen"].abs() <= 35], x="margen", nbins=71,
        title="Los márgenes de 3 y 7 puntos mandan",
        labels={"margen": "Margen (local − visitante)", "count": "Partidos"},
    )
    fig.update_traces(marker_color="#4C9AFF", marker_line_width=0)
    fig.add_vline(x=3, line_dash="dash", line_color="#F2C14E",
                  annotation_text="3 (gol de campo)")
    fig.add_vline(x=7, line_dash="dash", line_color="#F2C14E",
                  annotation_text="7 (TD + extra)")
    fig.add_vline(x=0, line_dash="dot", line_color="rgba(255,255,255,.35)",
                  annotation_text="empate")
    mostrar_grafica(fig)
    st.caption(
        "Por esto las líneas suelen ser 2.5, 3.5, 6.5, 7.5…: en los enteros "
        "(3, 7, 10) es donde más veces se «clava» la línea y se devuelve el "
        "dinero (**push**). Las casas mueven la línea justo por esto."
    )

    # Gráfica 2: ¿qué líneas enteras se clavan más?
    li = partidos[
        partidos["spread_line"].notna() & (partidos["spread_line"] % 1 == 0)
        & (partidos["spread_line"] != 0)
    ].copy()
    if len(li):
        li["linea"] = li["spread_line"].abs()
        res_p = (li.groupby("linea")
                 .agg(push=("push_spread", "mean"), n=("push_spread", "size"))
                 .reset_index())
        res_p = res_p[res_p["n"] >= 10].sort_values("push", ascending=False).head(8)
        res_p["push"] = (res_p["push"] * 100).round(1)
        res_p["etiqueta"] = res_p["linea"].map(lambda x: f"±{int(x)}")
        fig = px.bar(
            res_p, x="etiqueta", y="push", custom_data=["n"], text="push",
            title="¿Dónde se clava la línea? (% de push por línea entera)",
            labels={"etiqueta": "Línea (valor absoluto)", "push": "% push"},
        )
        fig.update_traces(
            marker_color="#FF6B6B", texttemplate="%{text:.1f}%", textposition="outside",
            hovertemplate="Línea %{x}: %{y:.1f}% push<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        mostrar_grafica(fig)
        st.caption(
            "La línea 3 es la reina del push (termina clavada ~10% de las "
            "veces). Es la razón matemática por la que existe la línea 3.5: "
            "evitar devoluciones y asegurar el vig."
        )

    izq, der = st.columns(2)
    with izq:
        # Descanso
        des = partidos.copy()
        des["tramo"] = pd.cut(
            des["ventaja_descanso"], [-30, -3.5, -0.5, 0.5, 3.5, 30],
            labels=["≤ −4", "−3 a −1", "Igual (0)", "+1 a +3", "≥ +4"],
        )
        res_des = (des.groupby("tramo", observed=True)
                   .agg(gana_local=("gano_local", "mean"), n=("gano_local", "size"))
                   .reset_index())
        res_des["gana_local"] = (res_des["gana_local"] * 100).round(1)
        fig = px.bar(
            res_des, x="tramo", y="gana_local", custom_data=["n"], text="gana_local",
            title="Victorias del local según descanso",
            labels={"tramo": "Días extra de descanso del local", "gana_local": "% gana local"},
        )
        fig.update_traces(
            marker_color="#B48EFF", texttemplate="%{text:.0f}%", textposition="outside",
            hovertemplate="%{x}: %{y:.1f}%<br>Partidos: %{customdata[0]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        mostrar_grafica(fig)
    with der:
        # Primetime: ¿ángulo real o historia del abuelo?
        ud = df_base[df_base["hay_underdog"]]
        pt = ud[ud["primetime"]]
        npt = ud[~ud["primetime"]]
        pct_pt = pt["gano_underdog"].mean() * 100 if len(pt) else float("nan")
        pct_npt = npt["gano_underdog"].mean() * 100 if len(npt) else float("nan")
        res_pt = pd.DataFrame({
            "grupo": ["Primetime 🌙", "Resto"],
            "pct": [pct_pt, pct_npt],
            "n": [len(pt), len(npt)],
        })
        fig = px.bar(
            res_pt, x="grupo", y="pct", color="grupo", custom_data=["n"],
            title="% de underdogs que ganan: primetime vs. resto (temporada)",
            labels={"grupo": "", "pct": "% que ganó"},
            color_discrete_map={"Primetime 🌙": "#F2C14E", "Resto": "#5B6B8C"},
        )
        fig.update_traces(
            showlegend=False,
            hovertemplate="%{x}: %{y:.1f}%<br>Partidos con underdog: %{customdata[0]}"
                          "<extra></extra>",
        )
        mostrar_grafica(fig)

    n_ud = len(df_base[df_base["hay_underdog"]])
    st.caption(
        f"El «descanso da ventaja» y «en primetime pasan cosas raras» se "
        f"desmontan con datos: los efectos o son minúsculos o ya están en la "
        f"línea. En la temporada elegida hay {n_ud} partidos con underdog: con "
        "tan pocos, casi cualquier resultado es compatible con el azar "
        "(**apofenia**: ver patrones donde solo hay ruido). "
        "Antes de creer una tendencia: ¿cuántos partidos son? ¿se repite en "
        "varias temporadas? ¿hay una razón?"
    )


# ===========================================================================
# TAB 5 — MERCADO Y VIG
# ===========================================================================
with tab_mercado:
    st.header("💰 Mercado, vig y la banca a ciegas")

    st.caption(
        "Esta pestaña usa **todas las temporadas** a propósito: al mercado solo "
        "se le puede juzgar con miles de partidos, no con una temporada suelta. "
        "Cuotas reales desde 2006; antes se asume la cuota estándar -110. "
        "Los *push* (empate exacto con la línea) no cuentan como apuesta."
    )

    pl = {}
    if len(apuestas_todas):
        fav_local = apuestas_todas["favorito_local"]
        resultado = {
            "Favoritos ATS": (
                apuestas_todas["home_spread_odds"].where(fav_local, apuestas_todas["away_spread_odds"]),
                apuestas_todas["cubre_favorito"],
            ),
            "Underdogs ATS": (
                apuestas_todas["away_spread_odds"].where(fav_local, apuestas_todas["home_spread_odds"]),
                ~apuestas_todas["cubre_favorito"],
            ),
            "Over (más)": (apuestas_todas["over_odds"], apuestas_todas["over"]),
            "Under (menos)": (apuestas_todas["under_odds"], ~apuestas_todas["over"]),
        }
        pl = {nombre: ganancia_apuesta(cuota, gano)
              for nombre, (cuota, gano) in resultado.items()}

        hold_ml = partidos["hold_ml"].dropna()
        hold_sp = partidos["hold_spread"].dropna()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Ventaja casa (moneyline)",
            f"{hold_ml.mean() * 100:.2f}%" if len(hold_ml) else "—",
            border=True,
            help="Margen medio de las cuotas de ganador (2006+): lo que se "
                 "queda la casa apostando a los dos lados.",
        )
        m2.metric(
            "Ventaja casa (spread)",
            f"{hold_sp.mean() * 100:.2f}%" if len(hold_sp) else "—",
            border=True,
            help="Lo mismo con las cuotas de la línea.",
        )
        m3.metric(
            "ROI a ciegas · favoritos",
            f"{pl['Favoritos ATS'].mean() * 100:+.1f}%",
            border=True,
            help="Por cada $1 apostado a TODOS los favoritos contra el spread.",
        )
        m4.metric(
            "ROI a ciegas · underdogs",
            f"{pl['Underdogs ATS'].mean() * 100:+.1f}%",
            border=True,
            help="Por cada $1 apostado a TODOS los underdogs contra el spread.",
        )

        # Banca a largo plazo: LA lección central
        banca = []
        for nombre, serie in pl.items():
            banca.append(pd.DataFrame({
                "apuesta": range(1, len(serie) + 1),
                "estrategia": nombre,
                "ganancia": serie.cumsum().values,
                "season": apuestas_todas["season"].values,
                "week": apuestas_todas["week"].values,
            }))
        banca = pd.concat(banca, ignore_index=True)
        fig = px.line(
            banca, x="apuesta", y="ganancia", color="estrategia",
            color_discrete_map={
                "Favoritos ATS": "#4C9AFF", "Underdogs ATS": "#F2C14E",
                "Over (más)": "#00C46A", "Under (menos)": "#B48EFF",
            },
            custom_data=["season", "week"],
            title="La banca a largo plazo: apostar $1 a ciegas en cada partido",
            labels={"apuesta": "Nº de apuesta (cronológico)",
                    "ganancia": "Ganancia acumulada ($)", "estrategia": ""},
        )
        fig.update_traces(
            line=dict(width=2.5),
            hovertemplate="Apuesta nº %{x}<br><b>%{fullData.name}</b>"
                          "<br>Acumulado: $%{y:.0f}"
                          "<br>Temporada %{customdata[0]}, semana %{customdata[1]}"
                          "<extra></extra>",
        )
        fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,.35)")
        mostrar_grafica(fig, alto=480)
        st.caption(
            f"Resultado por cada $1 apostado a ciegas "
            f"({int(apuestas_todas['season'].min())}–{int(apuestas_todas['season'].max())}): "
            f"favoritos ATS **{pl['Favoritos ATS'].mean() * 100:+.1f}%**, "
            f"underdogs ATS {pl['Underdogs ATS'].mean() * 100:+.1f}%, "
            f"over {pl['Over (más)'].mean() * 100:+.1f}%, "
            f"under {pl['Under (menos)'].mean() * 100:+.1f}%. "
            f"Ninguna estrategia gana: la casa cobra por existir. Compara esta "
            f"gráfica con la banca del modelo (pestaña 🎯) — ahí está la vara "
            f"real de cualquier «sistema»."
        )
    else:
        st.warning("Sin datos de apuestas disponibles (¿respaldo sin internet?).")

    # ¿El precio acierta? (calibración del moneyline)
    ml = partidos[partidos["prob_local_sin_vig"].notna()].copy()
    ml["tramo"] = pd.cut(
        ml["prob_local_sin_vig"], [0, .35, .45, .55, .65, 1],
        labels=["<35%", "35–45%", "45–55%", "55–65%", ">65%"],
    )
    cal = (ml.groupby("tramo", observed=True)
             .agg(implicita=("prob_local_sin_vig", "mean"),
                  real=("gano_local", "mean"),
                  n=("gano_local", "size"))
             .reset_index())
    fig = px.scatter(
        cal, x="implicita", y="real", size="n", text="tramo",
        title="¿El mercado se equivoca? Precio (sin vig) vs. victorias reales del local",
        labels={"implicita": "Probabilidad implícita (sin vig)",
                "real": "Victorias reales", "n": "Partidos"},
    )
    fig.update_traces(
        textposition="top center",
        customdata=cal[["n"]],
        hovertemplate="%{x:.1%} implícita → %{y:.1%} real"
                      "<br>Partidos: %{customdata[0]}<extra></extra>",
    )
    fig.add_trace(go.Scatter(
        x=[0, 1], y=[0, 1], mode="lines",
        line=dict(dash="dash", width=1, color="rgba(255,255,255,.5)"),
        name="Si el mercado fuera perfecto", hoverinfo="skip",
    ))
    fig.update_xaxes(tickformat=".0%", range=[0, 1])
    fig.update_yaxes(tickformat=".0%", range=[0, 1])
    mostrar_grafica(fig)
    st.caption(
        "Cada punto es un tramo de probabilidad del moneyline (datos desde 2006). "
        "Los puntos caen **sobre la diagonal**: el precio es casi una bola de "
        "cristal. Batirlo de forma constante es mucho más difícil de lo que "
        "sugieren los «expertos» de internet — y este dashboard incluye su "
        "propio modelo para que lo compruebes con datos."
    )

    with st.expander("📚 La lección del dinero (vig, valor esperado y apofenia)"):
        st.markdown(
            """
**¿Por qué el casino siempre gana?** Por el **margen de la casa** (*vig*).
En una cuota `-110` arriesgas 110 para ganar 100: necesitas ~**52.4%**
solo para empatar. El margen típico es **4–7%** por mercado.

**Valor esperado (EV):**

```
EV = (prob. de ganar × ganancia) − (prob. de perder × pérdida)
```

Si el EV es negativo, por muchas rachas que tengas, a largo plazo pierdes.

**Cuidado con las "tendencias" (la trampa más común):**

- "Los underdogs en primetime ganan todo" puede ser **casualidad** de pocos
  partidos, no un patrón real.
- Esto se llama **apofenia**: ver patrones donde solo hay azar.
- Con 50 lanzamientos de moneda, ver 30 caras es normal. No significa que
  la moneda esté cargada.
- En las gráficas, mira el **número de partidos** del tooltip: con n
  pequeño, casi cualquier resultado es "normal".

**Regla de oro:** antes de creer una tendencia, pregúntate:
¿*cuántos* partidos son? ¿se repite en *varias* temporadas? ¿hay una
*razón* (no solo el dato)?

> Los picks del modelo sirven para **entender** el mercado y sus márgenes,
> no para "vencerlo". El historial está ahí para que lo juzgues tú.
            """
        )


# ===========================================================================
# TAB 6 — PRECIOS ENTRE CASAS (The Odds API)
# ===========================================================================
with tab_precios:
    st.header("🛒 Precios entre casas (compara antes de apostar)")

    st.markdown(
        "El mismo partido se paga distinto en cada casa: la diferencia es la "
        "**comisión (*vig*)** que cobra cada una. Aquí se bajan las cuotas "
        "**reales y actuales** de la próxima jornada desde **The Odds API** "
        "(plan gratuito) y se ve quién paga mejor cada lado. Comparar precios "
        "**no crea una ventaja**: abarata la comisión. La ventaja hay que "
        "ganarla acertando (mira el historial del modelo, que es honesto)."
    )

    clave = clave_odds_api()

    if not clave:
        st.info(
            "Para encender esta pestaña hace falta una **clave gratuita** de "
            "The Odds API (500 consultas al mes, sin tarjeta). Se tarda 2 "
            "minutos:\n\n"
            "1. Entra en **[the-odds-api.com](https://the-odds-api.com)** y "
            "pulsa *Get API Key → Starter (Free)*.\n"
            "2. Escribe tu correo: la clave te llega por email (mira también "
            "el spam; a veces tarda unos minutos).\n"
            "3. Pégala justo aquí abajo y pulsa **Guardar**.\n\n"
            "Se queda solo en tu Mac (`.streamlit/secrets.toml`, ignorado por "
            "GitHub). Mientras no la tengas, el resto de la app funciona igual.",
            icon="🔑",
        )

    with st.expander("🔑 Pegar o cambiar la clave de The Odds API",
                     expanded=not clave):
        nueva_clave = st.text_input(
            "Clave (no se muestra en pantalla):",
            type="password", key="entrada_clave_odds",
        )
        c1, c2 = st.columns([1, 3])
        if c1.button("💾 Guardar clave"):
            limpia = nueva_clave.strip().replace('"', "")
            if len(limpia) >= 20:
                guardar_clave(limpia)
                st.session_state["odds_api_key"] = limpia
                st.rerun()
            else:
                st.warning("Eso no parece una clave: cópiala completa del correo.")
        c2.caption(
            "La clave se queda en tu equipo; nunca se sube a GitHub ni se enseña."
        )

    if clave:
        regiones_txt = st.radio(
            "Casas a consultar:",
            ["🇺🇸 Solo EE. UU. (2 créditos)", "🌍 EE. UU. + Europa (4 créditos)"],
            horizontal=True,
        )
        regiones = "us" if regiones_txt.startswith("🇺🇸") else "us,eu"

        if st.button("🔄 Traer precios ahora",
                     help="Ignora la caché de 15 minutos y consulta de nuevo."):
            traer_precios_casas.clear()

        try:
            tabla_casas, uso, momento = traer_precios_casas(clave, regiones)
            error_casas = None
        except ValueError as error:
            tabla_casas, uso, momento, error_casas = pd.DataFrame(), {}, "", error

        if error_casas is not None:
            st.error(f"⚠️ {error_casas}")
        else:
            st.caption(
                f"Consulta de las {momento} (se cachea 15 minutos) · créditos "
                f"gratis restantes este mes: **{uso.get('restantes') or '?'}** "
                "(cada consulta gasta 2, o 4 con Europa, de los 500 del plan "
                "gratuito)."
            )

            # Solo la próxima jornada: los partidos ya empezados no interesan aquí.
            tabla_casas["inicio_dt"] = pd.to_datetime(
                tabla_casas["inicio"], utc=True, errors="coerce")
            ahora = pd.Timestamp.now(tz="UTC")
            tabla_futura = tabla_casas[tabla_casas["inicio_dt"] > ahora].copy()

            analisis_casas = datos.analizar_precios_casas(tabla_futura)
            resumen_casas = analisis_casas["resumen"]

            if not resumen_casas["juegos"]:
                st.info(
                    "Ahora mismo no hay partidos próximos con cuotas nuevas "
                    "(la jornada ya empezó o no hay líneas publicadas todavía). "
                    "Vuelve a mirar más cerca del domingo."
                )
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Partidos próximos", resumen_casas["juegos"],
                          border=True,
                          help="Partidos que todavía no han empezado.")
                m2.metric("Casas comparadas", resumen_casas["casas"],
                          border=True,
                          help="Casa deportiva distinta con cuotas publicadas.")
                m3.metric("Vig medio de las casas",
                          f"{resumen_casas['vig_medio']:.1f}%", border=True,
                          help="Comisión media (''hold'') que cobra cada casa "
                               "si el dinero se reparte parejo. Con -110 a "
                               "ambos lados son 4.8%.")
                m4.metric(
                    "Vig con el mejor precio",
                    f"{resumen_casas['vig_mejor']:.1f}%",
                    delta=f"{resumen_casas['vig_mejor'] - resumen_casas['vig_medio']:+.1f} pts vs media",
                    delta_color="inverse",
                    border=True,
                    help="Lo que cuesta el mercado si tomas SIEMPRE el precio "
                         "más alto de cada lado, cambiando de casa. Menos es "
                         "mejor (y esto es lo que regala el line shopping).",
                )

                # Gráfica: comisión media por casa
                fig = px.bar(
                    analisis_casas["por_casa"], x="casa", y="vig_medio",
                    custom_data=["partidos"], text="vig_medio",
                    title="Comisión media (vig) de cada casa, próxima jornada",
                    labels={"casa": "", "vig_medio": "Vig (%)"},
                )
                fig.update_traces(
                    marker_color="#FF6B6B", texttemplate="%{text:.1f}%",
                    textposition="outside",
                    hovertemplate="%{x}: %{y:.2f}% de vig"
                                  "<br>Partidos cubiertos: %{customdata[0]}"
                                  "<extra></extra>",
                )
                fig.add_hline(
                    y=resumen_casas["vig_mejor"], line_dash="dash",
                    line_color="#00C46A",
                    annotation_text="mejor precio de cada lado",
                    annotation_font_color="#00C46A",
                )
                fig.update_xaxes(tickangle=-20)
                mostrar_grafica(fig, alto=470)
                st.caption(
                    "Menos es más: la casa con la barra más baja te cobra "
                    "menos por apostar. La línea verde marca lo que costaría "
                    "tomar el mejor precio de cada lado — la meta del *line "
                    "shopping*."
                )

                # Tabla por partido
                mercado_txt = st.radio(
                    "Mercado a comparar:",
                    ["Spread (contra la línea)", "Totales (over/under)"],
                    horizontal=True, key="mercado_casas",
                )
                mercado_casas = ("spreads" if mercado_txt.startswith("Spread")
                                 else "totals")

                juegos_casas = analisis_casas["juegos"].sort_values("inicio")
                vj = analisis_casas["vig_juego"]
                mj = analisis_casas["mejores"]

                filas_casas = []
                for _, meta in juegos_casas.iterrows():
                    lados = mj[(mj["juego_id"] == meta["juego_id"])
                               & (mj["mercado"] == mercado_casas)]
                    vfila = vj[(vj["juego_id"] == meta["juego_id"])
                               & (vj["mercado"] == mercado_casas)]
                    if not len(lados) or not len(vfila):
                        continue
                    vfila = vfila.iloc[0]

                    cuando = pd.to_datetime(meta["inicio"], utc=True) \
                        .tz_convert("America/New_York")
                    cuando_txt = cuando.strftime("%d/%m %H:%M")

                    if mercado_casas == "spreads":
                        lado_local, lado_visita = meta["local"], meta["visitante"]
                        linea_local = lados[lados["lado"] == lado_local]
                        linea_txt = (
                            f"{nombre_corto(lado_local)} "
                            f"{linea_local.iloc[0]['linea']:+g}"
                            if len(linea_local) else "—"
                        )
                        titulo_local, titulo_visita = "Mejor local", "Mejor visitante"
                    else:
                        lado_local, lado_visita = "Over", "Under"
                        linea_total = lados[lados["lado"] == "Over"]
                        linea_txt = (
                            f"Total {linea_total.iloc[0]['linea']:g}"
                            if len(linea_total) else "—"
                        )
                        titulo_local, titulo_visita = "Mejor Over", "Mejor Under"

                    def celda(lado):
                        casa_lado = lados[lados["lado"] == lado]
                        if not len(casa_lado):
                            return "—"
                        fila_lado = casa_lado.iloc[0]
                        return (f"{fila_lado['mejor_cuota']:+.0f} "
                                f"({fila_lado['casa_mejor']})")

                    dif_precio = (
                        (lados["pago_mejor"] - lados["pago_peor"]).mean() * 100
                    )
                    vig_mejor_txt = (
                        f"{vfila['vig_mejor']:.1f}%"
                        if pd.notna(vfila["vig_mejor"]) else "—"
                    )
                    filas_casas.append({
                        "Partido": f"{nombre_corto(meta['visitante'])} @ "
                                   f"{nombre_corto(meta['local'])}",
                        "Cuándo (ET)": cuando_txt,
                        "Línea": linea_txt,
                        titulo_local: celda(lado_local),
                        titulo_visita: celda(lado_visita),
                        "Dif. por $100": f"+${dif_precio:.0f}",
                        "Vig medio": f"{vfila['vig_medio']:.1f}%",
                        "Vig mejor": vig_mejor_txt,
                    })

                if filas_casas:
                    tabla_vista = pd.DataFrame(filas_casas)
                    st.dataframe(
                        tabla_vista, width="stretch", hide_index=True,
                        height=min(480, 40 + 36 * len(tabla_vista)),
                    )
                    st.caption(
                        "La **mejor cuota** de cada lado es la más alta (la que "
                        "te paga más). Para comparar peras con peras solo se "
                        "usan las cuotas de la **línea más común** entre las "
                        "casas; si una casa ofrece medio punto distinto, eso a "
                        "veces vale más que el precio: míralo con lupa. La "
                        "columna de $100 es la diferencia de ganancia entre la "
                        "casa más barata y la más cara en esa misma apuesta."
                    )
                    st.caption(
                        "⚠️ Comparar precios **no crea una ventaja**: baja la "
                        "comisión. Con el mejor precio en −105 aún hace falta "
                        "ganar ~51.2% para no perder. La paciencia para "
                        "comparar es gratis; el edge, no."
                    )
                else:
                    st.info(
                        "No hay cuotas de este mercado para los partidos "
                        "próximos."
                    )

                st.caption(
                    "Datos: The Odds API (cuotas reales de la próxima "
                    "jornada). 🔞 +18 · Juego responsable."
                )


# ===========================================================================
# TAB 7 — TEMPORADAS COMPARADAS
# ===========================================================================
with tab_temporadas:
    st.header("📊 Temporadas comparadas (2020–hoy)")

    st.caption(
        "Esta vista compara **temporadas completas de toda la liga** en "
        "paralelo (ignora los filtros de la barra lateral a propósito). "
        "Sirve para la pregunta clave: ¿las «tendencias» de una temporada se "
        "repiten en la siguiente? Apuestas de $1; los push no cuentan."
    )

    resumen_temp = datos.resumen_por_temporada(partidos, desde=2020)

    if len(resumen_temp):
        r1, r2, r3, r4 = st.columns(4)
        r1.metric(
            "Temporadas comparadas", len(resumen_temp), border=True,
            help="Temporadas 2020 en adelante con partidos jugados "
                 "(la última suele ir a medias).",
        )
        r2.metric(
            "ROI medio · favoritos",
            f"{resumen_temp['roi_favoritos'].mean():+.1f}%",
            border=True,
            help="Media del ROI a ciegas al favorito contra la línea, $1 por "
                 "apuesta: cuánto se gana (?) o pierde año a año.",
        )
        r3.metric(
            "ROI medio · underdogs",
            f"{resumen_temp['roi_underdogs'].mean():+.1f}%",
            border=True,
            help="Lo mismo apostando siempre al underdog. También debería "
                 "quedar en negativo: la casa cobra el vig igual.",
        )
        r4.metric(
            "% overs medio",
            f"{resumen_temp['pct_overs'].mean():.1f}%",
            border=True,
            help="Media del % de partidos que superaron la línea del total. "
                 "Si el mercado fuera perfecto: 50%.",
        )

        # 1) Puntos por partido
        fig = px.bar(
            resumen_temp, x="temporada", y="puntos_por_partido",
            custom_data=["partidos"], text="puntos_por_partido",
            title="Puntos por partido, temporada a temporada",
            labels={"temporada": "Temporada",
                    "puntos_por_partido": "Puntos por partido"},
        )
        fig.update_traces(
            marker_color="#00C46A", texttemplate="%{text:.1f}",
            textposition="outside",
            hovertemplate="Temporada %{x}: %{y:.1f} puntos por partido"
                          "<br>Partidos: %{customdata[0]}<extra></extra>",
        )
        fig.add_hline(
            y=resumen_temp["puntos_por_partido"].mean(),
            line_dash="dash", line_color="rgba(255,255,255,.4)",
        )
        fig.update_xaxes(dtick=1)
        mostrar_grafica(fig)
        st.caption(
            "Cuánto se marca de media cada temporada (línea punteada: media "
            "del periodo). Sube y baja sin patrón fijo: ninguna cifra es "
            "«la normal» para siempre."
        )

        # 2) % de overs por temporada
        fig = px.bar(
            resumen_temp, x="temporada", y="pct_overs",
            custom_data=["partidos"], text="pct_overs",
            title="% de partidos que superaron la línea del total",
            labels={"temporada": "Temporada", "pct_overs": "% overs"},
        )
        fig.update_traces(
            marker_color="#4C9AFF", texttemplate="%{text:.0f}%",
            textposition="outside",
            hovertemplate="Temporada %{x}: %{y:.1f}% overs"
                          "<br>Partidos: %{customdata[0]}<extra></extra>",
        )
        fig.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        fig.update_xaxes(dtick=1)
        mostrar_grafica(fig)
        st.caption(
            "La línea se pone para rondar el 50%. Una temporada de 56% o 44% "
            "casi siempre es azar, no una ley: mira cuántos partidos son antes "
            "de creerte una tendencia."
        )

        # 3) % de favoritos cubriendo por temporada
        fig = px.bar(
            resumen_temp, x="temporada", y="pct_favoritos",
            custom_data=["partidos"], text="pct_favoritos",
            title="% de favoritos que cubrieron la línea (ATS)",
            labels={"temporada": "Temporada", "pct_favoritos": "% que cubrió"},
        )
        fig.update_traces(
            marker_color="#F2C14E", texttemplate="%{text:.0f}%",
            textposition="outside",
            hovertemplate="Temporada %{x}: %{y:.1f}% de favoritos cubrieron"
                          "<br>Partidos: %{customdata[0]}<extra></extra>",
        )
        fig.add_hline(y=50, line_dash="dash", line_color="rgba(255,255,255,.4)")
        fig.update_xaxes(dtick=1)
        mostrar_grafica(fig)
        st.caption(
            "Ni los favoritos ni los underdogs tienen una temporada «buena» "
            "fija: el % se pasea alrededor del 50% porque la línea se ajusta "
            "para eso."
        )

        # 4) ROI a ciegas por temporada (la prueba del vig, año a año)
        roi_temp = resumen_temp.melt(
            id_vars=["temporada", "partidos"],
            value_vars=["roi_favoritos", "roi_underdogs"],
            var_name="estrategia", value_name="roi",
        )
        roi_temp["estrategia"] = roi_temp["estrategia"].map({
            "roi_favoritos": "Favoritos ATS",
            "roi_underdogs": "Underdogs ATS",
        })
        fig = px.bar(
            roi_temp, x="temporada", y="roi", color="estrategia",
            barmode="group", custom_data=["partidos"], text="roi",
            color_discrete_map={"Favoritos ATS": "#4C9AFF",
                                "Underdogs ATS": "#F2C14E"},
            title="ROI a ciegas por temporada: apostar $1 en cada partido",
            labels={"temporada": "Temporada", "roi": "ROI (%)", "estrategia": ""},
        )
        fig.update_traces(
            texttemplate="%{text:+.1f}%", textposition="outside",
            hovertemplate="Temporada %{x} · %{fullData.name}: %{y:+.1f}%"
                          "<br>Partidos: %{customdata[0]}<extra></extra>",
        )
        fig.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,.35)")
        fig.update_xaxes(dtick=1)
        mostrar_grafica(fig)
        st.caption(
            "La prueba año a año de que apostar a ciegas no es un plan: el ROI "
            "queda bajo cero en casi todas las temporadas, y lo que gana una "
            "lo devuelve la siguiente. Eso no es mala suerte: es la casa "
            "cobrando su margen."
        )

        # Tabla resumen
        st.subheader("📋 El resumen, en tabla")
        st.dataframe(
            resumen_temp.rename(columns={
                "temporada": "Temporada", "partidos": "Partidos",
                "puntos_por_partido": "Puntos/partido",
                "pct_overs": "% overs", "pct_favoritos": "% favoritos ATS",
                "roi_favoritos": "ROI favoritos ($1)",
                "roi_underdogs": "ROI underdogs ($1)",
            }),
            width="stretch", hide_index=True,
            height=min(430, 40 + 36 * len(resumen_temp)),
            column_config={
                "Temporada": st.column_config.NumberColumn(format="%d"),
                "Partidos": st.column_config.NumberColumn(format="%d"),
                "Puntos/partido": st.column_config.NumberColumn(
                    format="%.1f", help="Media de puntos sumados por partido."),
                "% overs": st.column_config.NumberColumn(
                    format="%.1f",
                    help="% de partidos que superaron la línea (sin push)."),
                "% favoritos ATS": st.column_config.NumberColumn(
                    format="%.1f",
                    help="% de partidos en que cubrió el favorito (sin push)."),
                "ROI favoritos ($1)": st.column_config.NumberColumn(
                    format="%+.1f",
                    help="Ganancia media por $1 apostado al favorito (%)."),
                "ROI underdogs ($1)": st.column_config.NumberColumn(
                    format="%+.1f",
                    help="Ganancia media por $1 apostado al underdog (%)."),
            },
        )
        st.caption(
            "La última temporada suele estar **a medias**: mira la columna de "
            "partidos antes de sacar conclusiones."
        )
    else:
        st.info("No hay temporadas de 2020 en adelante en los datos actuales.")


st.divider()
st.caption(
    "Datos: nflverse · Hecho con Python + Streamlit + Plotly. "
    "Nada de esto es consejo de apuestas ni garantiza ganancias. "
    "🔞 +18 · Juego responsable. Cambia de temporada en la barra lateral para comparar."
)
