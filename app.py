"""
Dashboard de Estadísticas — Fútbol Americano (datos REALES)
==========================================================

Proyecto educativo. Analiza datos deportivos reales (nflverse); NO predice
apuestas ni promete ganarle al casino (eso es imposible, se explica en la app).

Cómo se corre (NO dentro de Thonny, es una app web):
    source .venv/bin/activate
    streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import datos

# ---------------------------------------------------------------------------
st.set_page_config(page_title="Dashboard Fútbol Americano", page_icon="🏈", layout="wide")
st.title("🏈 Dashboard de Fútbol Americano")
st.caption(
    "Datos REALES de nflverse (resultados, líneas de apuestas y horarios). "
    "Proyecto educativo: analiza datos, no apuesta."
)


# ---------------------------------------------------------------------------
# DATOS
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Descargando datos reales de nflverse...")
def traer_datos():
    return datos.cargar_partidos()


@st.cache_data
def traer_equipos():
    return datos.cargar_equipos()


partidos = traer_datos()
equipos = traer_equipos()
NOMBRES = datos.mapa_nombres(equipos)
COLORES = datos.mapa_colores(equipos)


def color_equipos(valores):
    """Lista de colores reales para una lista de abreviaturas."""
    return [COLORES.get(v, "#888888") for v in valores]


# ---------------------------------------------------------------------------
# FILTROS (barra lateral)
# ---------------------------------------------------------------------------
st.sidebar.header("Filtros")

temporadas = sorted(partidos["season"].unique(), reverse=True)
temporadas = [t for t in temporadas if t > 0][:10]
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
st.sidebar.caption("Fuente: [nflverse](https://github.com/nflverse/nflverse-data)")


# ---------------------------------------------------------------------------
# MÉTRICAS
# ---------------------------------------------------------------------------
ud_vista = df_vista[df_vista["hay_underdog"]]
pct_ud = ud_vista["gano_underdog"].mean() * 100 if len(ud_vista) else float("nan")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Partidos", len(df_vista))
c2.metric(
    "Puntos por partido",
    f"{df_vista['total_puntos'].mean():.1f}" if len(df_vista) else "—",
)
c3.metric("Underdogs que ganaron", f"{pct_ud:.1f}%" if len(ud_vista) else "—")
c4.metric(
    "Local vs visitante",
    f"{df_vista['home_score'].mean():.1f} - {df_vista['away_score'].mean():.1f}"
    if len(df_vista)
    else "—",
)

tab1, tab2, tab3 = st.tabs(["📊 Equipos y partidos", "🐶 Underdogs y tendencias", "📚 Educación"])


# ===========================================================================
# TAB 1 — EQUIPOS Y PARTIDOS
# ===========================================================================
with tab1:
    st.subheader("📅 Partidos")
    cols_mostrar = ["week", "weekday", "gametime", "away_team", "home_team",
                    "away_score", "home_score", "spread_line", "primetime"]
    cols_mostrar = [c for c in cols_mostrar if c in df_vista.columns]
    st.dataframe(df_vista[cols_mostrar], width="stretch", hide_index=True)

    # --- Resumen por equipo ---
    def partidos_por_equipo(datos_df):
        filas = []
        for _, g in datos_df.iterrows():
            filas.append({"equipo": g["home_team"], "favor": g["home_score"],
                          "contra": g["away_score"]})
            filas.append({"equipo": g["away_team"], "favor": g["away_score"],
                          "contra": g["home_score"]})
        d = pd.DataFrame(filas)
        d["victoria"] = d["favor"] > d["contra"]
        return d

    det = partidos_por_equipo(df_vista)
    resumen = (det.groupby("equipo")
               .agg(partidos=("favor", "size"), victorias=("victoria", "sum"),
                    prom_favor=("favor", "mean"), prom_contra=("contra", "mean"))
               .reset_index())
    resumen["prom_favor"] = resumen["prom_favor"].round(1)
    resumen["prom_contra"] = resumen["prom_contra"].round(1)
    resumen["nombre"] = resumen["equipo"].map(lambda e: datos.con_nombre(e, NOMBRES))
    resumen = resumen.sort_values("victorias", ascending=False)

    st.subheader("🏆 Resumen por equipo")
    st.dataframe(
        resumen[["nombre", "partidos", "victorias", "prom_favor", "prom_contra"]],
        width="stretch", hide_index=True,
    )

    izq, der = st.columns(2)
    with izq:
        r = resumen.sort_values("prom_favor")
        fig = px.bar(r, x="prom_favor", y="nombre", orientation="h",
                     title="Promedio de puntos anotados por equipo",
                     labels={"prom_favor": "Puntos a favor", "nombre": ""})
        fig.update_traces(marker_color=color_equipos(r["equipo"]))
        st.plotly_chart(fig, width="stretch")
    with der:
        r = resumen.sort_values("victorias")
        fig = px.bar(r, x="victorias", y="nombre", orientation="h",
                     title="Victorias por equipo",
                     labels={"victorias": "Victorias", "nombre": ""})
        fig.update_traces(marker_color=color_equipos(r["equipo"]))
        st.plotly_chart(fig, width="stretch")

    izq, der = st.columns(2)
    with izq:
        fig = px.histogram(df_vista, x="margen", nbins=30,
                           title="Distribución de márgenes (local − visitante)",
                           labels={"margen": "Diferencia de puntos"})
        fig.add_vline(x=0, line_dash="dash", line_color="white")
        st.plotly_chart(fig, width="stretch")
    with der:
        sem = (df_vista.groupby("week")
               .agg(puntos=("total_puntos", "mean"), partidos=("total_puntos", "size"))
               .reset_index())
        fig = px.line(sem, x="week", y="puntos", markers=True,
                      title="Puntos por partido, por semana (tendencia)",
                      labels={"week": "Semana", "puntos": "Puntos por partido"})
        st.plotly_chart(fig, width="stretch")

    # Local vs visitante
    fig = px.bar(
        x=["Local", "Visitante"],
        y=[df_vista["home_score"].mean(), df_vista["away_score"].mean()],
        title="Promedio de puntos: local vs. visitante",
        labels={"x": "", "y": "Puntos"}, color=["Local", "Visitante"],
    )
    st.plotly_chart(fig, width="stretch")


# ===========================================================================
# TAB 2 — UNDERDOGS Y TENDENCIAS
# ===========================================================================
with tab2:
    st.subheader(f"🐶 Underdogs — temporada {temporada_sel}")

    ud = df_base[df_base["hay_underdog"]]
    if len(ud):
        gan = int(ud["gano_underdog"].sum())
        pct = ud["gano_underdog"].mean() * 100
        m1, m2, m3 = st.columns(3)
        m1.metric("Partidos con underdog", len(ud))
        m2.metric("Underdogs que ganaron", gan)
        m3.metric("% Underdogs que ganaron", f"{pct:.1f}%")

    # % de underdogs que ganan por semana (LA TENDENCIA)
    por_semana = (ud.groupby("week")
                  .agg(pct=("gano_underdog", "mean"), n=("gano_underdog", "size"))
                  .reset_index())
    por_semana["pct"] = (por_semana["pct"] * 100).round(1)
    fig = px.line(por_semana, x="week", y="pct", markers=True,
                  title="% de underdogs que ganan, por semana",
                  labels={"week": "Semana", "pct": "% que ganó"})
    fig.add_hline(y=50, line_dash="dash", line_color="gray",
                  annotation_text="50% (azar)")
    st.plotly_chart(fig, width="stretch")

    # Primetime vs no primetime
    pt = ud[ud["primetime"]]
    npt = ud[~ud["primetime"]]
    pct_pt = pt["gano_underdog"].mean() * 100 if len(pt) else float("nan")
    pct_npt = npt["gano_underdog"].mean() * 100 if len(npt) else float("nan")

    izq, der = st.columns(2)
    with izq:
        fig = px.bar(
            x=["Primetime 🌙", "Resto"], y=[pct_pt, pct_npt],
            title="% underdogs que ganan: primetime vs. resto",
            labels={"x": "", "y": "% que ganó"}, color=["Primetime", "Resto"],
        )
        st.plotly_chart(fig, width="stretch")
    with der:
        # Underdogs por equipo (cuántas veces fueron underdog y cuántas ganaron)
        filas = []
        for _, g in ud.iterrows():
            if g["local_underdog"]:
                filas.append({"equipo": g["home_team"], "gano": g["gano_underdog"]})
            else:
                filas.append({"equipo": g["away_team"], "gano": g["gano_underdog"]})
        t = pd.DataFrame(filas)
        res = (t.groupby("equipo")
               .agg(veces=("gano", "size"), ganadas=("gano", "sum")).reset_index())
        res["pct"] = (res["ganadas"] / res["veces"] * 100).round(1)
        res["nombre"] = res["equipo"].map(lambda e: datos.con_nombre(e, NOMBRES))
        res = res.sort_values("pct", ascending=False)
        fig = px.bar(res, x="pct", y="nombre", orientation="h",
                     title="% de veces que ganó siendo underdog (por equipo)",
                     labels={"pct": "% ganadas", "nombre": ""})
        fig.update_traces(marker_color=color_equipos(res["equipo"]))
        st.plotly_chart(fig, width="stretch")

    st.info(
        f"Esta temporada, los underdogs ganaron **{pct_ud:.0f}%** de sus partidos. "
        f"En primetime: **{pct_pt:.0f}%**. El resto: **{pct_npt:.0f}%**. "
        "⚠️ Con pocos partidos, una racha puede parecer una 'tendencia', pero suele "
        "ser **variación aleatoria**. Cambia de temporada y compara."
    )


# ===========================================================================
# TAB 3 — EDUCACIÓN
# ===========================================================================
with tab3:
    st.subheader("📚 Cómo leer esto sin engañarte")
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

        **Regla de oro:** antes de creer una tendencia, pregúntate:
        ¿*cuántos* partidos son? ¿se repite en *varias* temporadas? ¿hay una
        *razón* (no solo el dato)?

        > Este dashboard sirve para **entender** los datos y el sistema,
        > no para "vencerlo".
        """
    )

st.divider()
st.caption(
    "Datos: nflverse · Hecho con Python + Streamlit + Plotly. "
    "Cambia de temporada en la barra lateral para comparar."
)
