"""
Capa de datos — Dashboard de Fútbol Americano
=============================================

Descarga datos REALES de nflverse (resultados, líneas de apuestas y horarios),
los guarda en caché (para no volver a bajarlos) y agrega las columnas que
necesitamos para el análisis:
    - margen, ganador
    - underdog / favorito
    - si ganó el underdog
    - si el partido fue en "primetime"
    - mercado de apuestas: quién cubre el spread, over/under, probabilidad
      implícita de las cuotas (moneyline y spread) y ventaja de descanso
    - clima: techo (interior/exterior), viento y temperatura
    - MODELO de pronósticos (walk-forward, sin ver el futuro): margen y total
      esperados de cada partido, para compararlos con la línea del mercado
    - precios entre casas (The Odds API, opcional con clave gratuita): cuotas
      de la próxima jornada en varias casas deportivas, para comparar la
      comisión (vig) de cada una

Si no hay internet, cae de vuelta a los datos de ejemplo (data/partidos.csv).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE = Path(__file__).parent / "data"

URL_JUEGOS = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
URL_EQUIPOS = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"


# ---------------------------------------------------------------------------
# Descarga con caché
# ---------------------------------------------------------------------------
def _descargar(url: str, destino: Path, forzar: bool = False) -> bool:
    """Descarga `url` a `destino` si no existe todavía. Devuelve True si hay archivo.

    Usamos `requests` (no urllib) porque este Python de macOS no trae los
    certificados SSL, y requests sí los incluye.

    Con `forzar=True` vuelve a bajar el archivo aunque ya exista (para
    refrescar las líneas de apuestas, que se mueven durante la semana).
    """
    if destino.exists() and not forzar:
        return True
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        respuesta = requests.get(url, timeout=120)
        respuesta.raise_for_status()
        destino.write_bytes(respuesta.content)
        return True
    except Exception:
        return False


def actualizar_datos() -> bool:
    """Fuerza la re-descarga de los CSV (líneas y calendario frescos).

    Devuelve True si el archivo de partidos quedó disponible. Si no hay
    internet, conserva el que ya estaba en caché.
    """
    ok_juegos = _descargar(URL_JUEGOS, BASE / "nfl_games.csv", forzar=True)
    _descargar(URL_EQUIPOS, BASE / "equipos.csv", forzar=True)
    return ok_juegos


# ---------------------------------------------------------------------------
# Equipos (nombres y colores)
# ---------------------------------------------------------------------------
def cargar_equipos() -> pd.DataFrame:
    if not _descargar(URL_EQUIPOS, BASE / "equipos.csv"):
        return pd.DataFrame(columns=["team_abbr", "team_name", "team_nick", "team_color"])
    t = pd.read_csv(BASE / "equipos.csv")
    return t[["team_abbr", "team_name", "team_nick", "team_color"]]


# ---------------------------------------------------------------------------
# Partidos
# ---------------------------------------------------------------------------
def _prob_implicita(cuota: pd.Series) -> pd.Series:
    """Cuota americana (-110, +145...) → probabilidad implícita (0–1).

    La probabilidad implícita incluye el margen de la casa ("vig"): por eso
    las dos cuotas de un partido suman más de 1. NaN si no hay cuota.
    """
    v = pd.to_numeric(cuota, errors="coerce")
    prob = (100 / (v + 100)).where(v > 0, (-v) / (-v + 100))
    return prob.mask(v.isna() | (v == 0))


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega las columnas de análisis a los datos crudos.

    Funciona igual con partidos jugados que con partidos pendientes: en los
    pendientes (sin resultado) todo lo que depende del marcador queda vacío
    (NA) y no cuenta en ningún porcentaje.
    """
    df = df.copy()

    # Columnas que el respaldo de ejemplo (o un CSV viejo) podría no traer.
    # Se rellenan aquí para que el resto del código nunca falle por una
    # columna que falta.
    for columna in (
        "gametime", "weekday", "game_id", "gameday", "spread_line", "total_line",
        "home_moneyline", "away_moneyline", "home_spread_odds", "away_spread_odds",
        "over_odds", "under_odds", "away_rest", "home_rest",
        "roof", "surface", "wind", "temp", "stadium", "div_game", "overtime",
    ):
        if columna not in df:
            df[columna] = float("nan")

    # ¿Ya se jugó? El calendario incluye la temporada en curso sin terminar.
    df["jugado"] = df["home_score"].notna() & df["away_score"].notna()

    # Margen y ganador (NA mientras no haya resultado)
    df["margen"] = df["home_score"] - df["away_score"]
    df["gano_local"] = (df["margen"] > 0).astype("boolean").mask(df["margen"].isna())
    df["empate"] = (df["margen"] == 0).astype("boolean").mask(df["margen"].isna())

    # Underdog = el equipo que RECIBE puntos (al que nadie espera que gane).
    # Convención nflverse: spread_line > 0 => LOCAL favorito => VISITANTE underdog
    #                     spread_line < 0 => LOCAL underdog
    df["local_underdog"] = df["spread_line"] < 0
    df["visitante_underdog"] = df["spread_line"] > 0
    df["hay_underdog"] = df["local_underdog"] | df["visitante_underdog"]

    # ¿Ganó el underdog?
    df["gano_underdog"] = (
        (df["local_underdog"] & df["gano_local"])
        | (df["visitante_underdog"] & ~df["gano_local"] & ~df["empate"])
    )

    # Primetime = partido NOCTURNO (inicio a las 19:00 o más, hora del Este).
    # La regla vieja también marcaba lunes/jueves enteros, pero eso metía
    # partidos de día (Thanksgiving 12:30/16:30, Christmas, reprogramados).
    #
    # Correcciones a la fuente (nflverse), verificadas contra los datos:
    #   - 2000–2005: los partidos de las 21:00 (MNF, inaugurales de jueves y
    #     algunos sábados de diciembre) vienen como "09:00" porque el dato
    #     original (9:00 PM) perdió el AM/PM. Se corrigen a 21:00.
    #   - 1999: toda la hora viene vacía; los lunes eran Monday Night Football
    #     (nocturnos). Los jueves de 1999 se dejan fuera porque no se pueden
    #     distinguir de un Thanksgiving de día.
    hora = pd.to_numeric(df["gametime"].astype(str).str.slice(0, 2), errors="coerce")
    dia = df["weekday"] if "weekday" in df else pd.Series("", index=df.index)
    hora = hora.mask((hora == 9) & df["season"].between(2000, 2005), 21)
    sin_hora_lunes = hora.isna() & (dia == "Monday")

    df["primetime"] = (hora >= 19) | sin_hora_lunes

    df["total_puntos"] = df["home_score"] + df["away_score"]

    # -----------------------------------------------------------------
    # Mercado de apuestas: spread, totales, cuotas, descanso y clima
    # -----------------------------------------------------------------
    hay_margen = df["margen"].notna()

    # ¿Quién cubre el spread? Empate exacto con la línea = "push" (no cuenta).
    # Recuerda: spread_line > 0 → local favorito; < 0 → visitante favorito.
    df["push_spread"] = (
        (df["spread_line"].notna() & (df["margen"] == df["spread_line"]))
        .astype("boolean").mask(~hay_margen)
    )
    df["cubre_local"] = (
        (df["spread_line"].notna() & (df["margen"] > df["spread_line"]))
        .astype("boolean").mask(~hay_margen)
    )
    df["cubre_visitante"] = (
        (df["spread_line"].notna() & (df["margen"] < df["spread_line"]))
        .astype("boolean").mask(~hay_margen)
    )
    df["favorito_local"] = df["spread_line"] > 0
    df["pickem"] = df["spread_line"] == 0  # línea 0: sin favorito real

    # ¿Cubrió el favorito? Vacío (NA) en pick'em, push, sin línea o sin jugar:
    # esas apuestas no se pueden evaluar y no deben contar en los porcentajes.
    cubre_favorito = df["cubre_local"].where(df["favorito_local"], df["cubre_visitante"])
    df["cubre_favorito"] = cubre_favorito.mask(
        df["pickem"] | df["push_spread"].fillna(False)
        | df["spread_line"].isna() | ~hay_margen
    )

    # Totales: ¿la suma de puntos superó la línea? En push queda vacío
    # (esa apuesta devuelve el dinero y no se puede evaluar como acierto/fallo).
    hay_total = df["total_puntos"].notna()
    df["push_total"] = (
        (df["total_line"].notna() & (df["total_puntos"] == df["total_line"]))
        .astype("boolean").mask(~hay_total)
    )
    df["over"] = (
        (df["total_line"].notna() & (df["total_puntos"] > df["total_line"]))
        .astype("boolean").mask(~hay_total | df["push_total"].fillna(False))
    )

    # Cuotas → probabilidad implícita; "hold" = ventaja de la casa del partido
    df["prob_local_ml"] = _prob_implicita(df["home_moneyline"])
    df["prob_visitante_ml"] = _prob_implicita(df["away_moneyline"])
    suma_prob = df["prob_local_ml"] + df["prob_visitante_ml"]
    df["prob_local_sin_vig"] = df["prob_local_ml"] / suma_prob
    df["hold_ml"] = suma_prob - 1

    # Lo mismo con las cuotas del spread (la renta de la casa en la línea)
    prob_sp_local = _prob_implicita(df["home_spread_odds"])
    prob_sp_visit = _prob_implicita(df["away_spread_odds"])
    suma_sp = prob_sp_local + prob_sp_visit
    df["prob_local_spread_sin_vig"] = prob_sp_local / suma_sp
    df["hold_spread"] = suma_sp - 1

    # Descanso: días del local menos días del visitante
    df["ventaja_descanso"] = df["home_rest"] - df["away_rest"]

    # Clima: "interior" = techo cerrado (dome/closed). Vacío si no hay dato
    # de techo (p. ej. el respaldo de ejemplo).
    df["interior"] = (
        df["roof"].isin(["dome", "closed"]).astype("boolean").mask(df["roof"].isna())
    )

    return df


def cargar_calendario() -> pd.DataFrame:
    """Todos los partidos (jugados y pendientes), ya preparados.

    Incluye los partidos de la temporada en curso que todavía no se juegan:
    sirven para pronosticar la jornada que viene. Los pendientes solo traen
    línea si la casa ya la publicó en nflverse (`spread_line` vacío si no).
    """
    if _descargar(URL_JUEGOS, BASE / "nfl_games.csv"):
        df = pd.read_csv(BASE / "nfl_games.csv", low_memory=False)
        return _preparar(df)

    # Respaldo: datos de ejemplo (sin líneas de apuestas ni pendientes)
    ej = pd.read_csv(BASE / "partidos.csv")
    ej = ej.rename(
        columns={
            "jornada": "week",
            "equipo_local": "home_team",
            "equipo_visitante": "away_team",
            "puntos_local": "home_score",
            "puntos_visitante": "away_score",
        }
    )
    ej["season"] = 0
    ej["gametime"] = "13:00"
    ej["weekday"] = "Sunday"
    return _preparar(ej)


def cargar_partidos() -> pd.DataFrame:
    """Solo los partidos ya jugados (la base del análisis histórico)."""
    calendario = cargar_calendario()
    return calendario[calendario["jugado"]].copy()


# ---------------------------------------------------------------------------
# Utilidades de nombres/colores
# ---------------------------------------------------------------------------
def mapa_nombres(equipos: pd.DataFrame) -> dict:
    return dict(zip(equipos["team_abbr"], equipos["team_name"]))


def mapa_apodos(equipos: pd.DataFrame) -> dict:
    """Nombre corto ("Chiefs", "Bills") para tablas y ejes."""
    return dict(zip(equipos["team_abbr"], equipos["team_nick"]))


def mapa_colores(equipos: pd.DataFrame) -> dict:
    return dict(zip(equipos["team_abbr"], equipos["team_color"]))


def con_nombre(valor: str, nombres: dict) -> str:
    """Si `valor` es una abreviatura de equipo, la cambia por el nombre largo."""
    return nombres.get(valor, valor)


# ---------------------------------------------------------------------------
# RESUMEN POR TEMPORADA (vista comparada)
# ---------------------------------------------------------------------------
def _pago_por_dolar(cuotas: pd.Series) -> pd.Series:
    """Cuota americana (-110, +145...) → ganancia por $1 (sin devolver el $).

    Sin cuota real (vacíos o datos viejos) se asume la estándar -110,
    igual que en el resto de la app.
    """
    c = pd.to_numeric(cuotas, errors="coerce")
    pago = (c / 100).where(c > 0, 100 / -c)
    return pago.where(np.isfinite(pago), 100 / 110)


def resumen_por_temporada(partidos: pd.DataFrame, desde: int = 2020) -> pd.DataFrame:
    """Una fila por temporada (desde `desde`) con las métricas de liga.

    Pensado para la pestaña de comparación: partidos, puntos por partido,
    % de overs, % de favoritos cubriendo y ROI a ciegas de favoritos y
    underdogs ($1 por apuesta, sin contar push). Cada lado se paga con SU
    cuota (si el favorito gana cobra la suya; el underdog, la suya).
    """
    d = partidos[partidos["season"] >= desde].copy()
    if d.empty:
        return pd.DataFrame(columns=[
            "temporada", "partidos", "puntos_por_partido",
            "pct_overs", "pct_favoritos", "roi_favoritos", "roi_underdogs",
        ])

    con_spread = d[d["cubre_favorito"].notna()].copy()
    cuota_fav = con_spread["home_spread_odds"].where(
        con_spread["favorito_local"], con_spread["away_spread_odds"]
    )
    cuota_dog = con_spread["away_spread_odds"].where(
        con_spread["favorito_local"], con_spread["home_spread_odds"]
    )
    gano_fav = con_spread["cubre_favorito"].astype(bool)
    con_spread["gan_fav"] = _pago_por_dolar(cuota_fav).where(gano_fav, -1.0)
    con_spread["gan_dog"] = _pago_por_dolar(cuota_dog).where(~gano_fav, -1.0)

    con_total = d[d["over"].notna()]

    resumen = pd.DataFrame({
        "partidos": d.groupby("season").size(),
        "puntos_por_partido": d.groupby("season")["total_puntos"].mean(),
        "pct_overs": con_total.groupby("season")["over"].mean() * 100,
        "pct_favoritos": con_spread.groupby("season")["cubre_favorito"].mean() * 100,
        "roi_favoritos": con_spread.groupby("season")["gan_fav"].mean() * 100,
        "roi_underdogs": con_spread.groupby("season")["gan_dog"].mean() * 100,
    }).rename_axis("temporada").reset_index()
    return resumen


# ---------------------------------------------------------------------------
# PRECIOS ENTRE CASAS (The Odds API — clave personal y gratuita)
# ---------------------------------------------------------------------------
# nflverse solo trae UN precio por partido. Para comparar precios entre casas
# deportivas usamos The Odds API (https://the-odds-api.com): su plan gratuito
# da 500 créditos al mes (sin tarjeta), cubre las casas más conocidas de
# EE. UU. y Europa, y solo necesita una clave personal que se guarda en
# `.streamlit/secrets.toml` (ese archivo NO se sube a GitHub). Una consulta
# de spreads+totales gasta 2 créditos por región, así que la app cachea la
# respuesta y muestra cuántos créditos quedan.
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"


def cargar_precios_casas(api_key: str, regiones: str = "us",
                         mercados: str = "spreads,totals"):
    """Cuotas actuales de la NFL en varias casas (The Odds API).

    Devuelve `(tabla, uso)`: la tabla larga de `parsear_precios_casas(...)` y
    un dict con los créditos del plan gratuito (`usados`, `restantes`,
    `ultima`). Lanza `ValueError` con un mensaje claro en español si la clave
    no sirve, no quedan consultas o no hay conexión.
    """
    try:
        respuesta = requests.get(
            ODDS_API_URL,
            params={
                "apiKey": api_key,
                "regions": regiones,
                "markets": mercados,
                "oddsFormat": "american",
                "dateFormat": "iso",
            },
            timeout=30,
        )
    except requests.RequestException as error:
        raise ValueError(f"Sin conexión con The Odds API ({error}).") from error

    if respuesta.status_code == 401:
        raise ValueError(
            "La clave de The Odds API no es válida o está incompleta: "
            "cópiala otra vez desde el correo que te llegó al registrarte."
        )
    if respuesta.status_code == 429:
        raise ValueError(
            "Se agotaron las consultas gratuitas del mes (500). "
            "Se renuevan el día 1 del mes que viene."
        )
    if respuesta.status_code != 200:
        raise ValueError(
            f"The Odds API respondió {respuesta.status_code}: "
            f"{respuesta.text[:160]}"
        )

    tabla = parsear_precios_casas(respuesta.json())
    uso = {
        "usados": respuesta.headers.get("x-requests-used"),
        "restantes": respuesta.headers.get("x-requests-remaining"),
        "ultima": respuesta.headers.get("x-requests-last"),
    }
    return tabla, uso


def parsear_precios_casas(payload) -> pd.DataFrame:
    """Respuesta JSON de The Odds API → tabla larga (una fila por precio).

    Columnas: juego_id, inicio, local, visitante, casa, mercado, lado, linea
    y cuota. En «spreads» el lado es el nombre del equipo; en «totals» es
    "Over"/"Under". `linea` es el punto del spread o del total.
    """
    columnas = ["juego_id", "inicio", "local", "visitante", "casa",
                "mercado", "lado", "linea", "cuota"]
    filas = []
    for juego in payload or []:
        for casa in juego.get("bookmakers") or []:
            for mercado in casa.get("markets") or []:
                for lado in mercado.get("outcomes") or []:
                    filas.append({
                        "juego_id": juego.get("id"),
                        "inicio": juego.get("commence_time"),
                        "local": juego.get("home_team"),
                        "visitante": juego.get("away_team"),
                        "casa": casa.get("title"),
                        "mercado": mercado.get("key"),
                        "lado": lado.get("name"),
                        "linea": lado.get("point"),
                        "cuota": lado.get("price"),
                    })
    tabla = pd.DataFrame(filas, columns=columnas)
    if len(tabla):
        tabla["cuota"] = pd.to_numeric(tabla["cuota"], errors="coerce")
        tabla["linea"] = pd.to_numeric(tabla["linea"], errors="coerce")
    return tabla


def abreviatura_de(nombre: str, equipos: pd.DataFrame):
    """Nombre completo de la API («Kansas City Chiefs») → abreviatura («KC»).

    Primero busca coincidencia exacta con `team_name`; si no, prueba a que el
    nombre termine en el apodo («... Chiefs»). Devuelve `None` si no lo
    reconoce (la vista entonces muestra el nombre tal cual, sin romperse).
    """
    if not isinstance(nombre, str) or equipos is None or not len(equipos):
        return None
    exacto = equipos["team_name"] == nombre
    if exacto.any():
        return equipos.loc[exacto, "team_abbr"].iloc[0]
    apodos = equipos[equipos["team_nick"].notna()]
    acaba = apodos["team_nick"].astype(str).apply(nombre.endswith)
    if acaba.any():
        return apodos.loc[acaba, "team_abbr"].iloc[0]
    return None


def analizar_precios_casas(tabla: pd.DataFrame) -> dict:
    """Resúmenes de la vista «precios entre casas».

    Devuelve un dict con:
      - `juegos`: metadatos de cada partido (una fila por juego).
      - `mejores`: por juego/mercado/lado, la mejor y la peor cuota (y qué
        casa las ofrece), en la línea más común entre las casas, más la
        ganancia por $1 de cada una.
      - `por_casa`: vig medio (%) de cada casa y partidos que cubre.
      - `vig_juego`: por juego/mercado, el vig medio de las casas y el vig
        tomando el mejor precio de cada lado (ambos en %).
      - `resumen`: totales para las tarjetas (juegos, casas, vig medio,
        vig con el mejor precio).

    El vig («hold») de una casa en un mercado es la suma de las
    probabilidades implícitas de sus dos lados menos 1: lo que cobra de
    comisión si el dinero se reparte parejo.
    """
    vacio = {
        "juegos": pd.DataFrame(
            columns=["juego_id", "inicio", "local", "visitante"]),
        "mejores": pd.DataFrame(
            columns=["juego_id", "mercado", "lado", "linea", "mejor_cuota",
                     "casa_mejor", "peor_cuota", "casa_peor",
                     "pago_mejor", "pago_peor"]),
        "por_casa": pd.DataFrame(columns=["casa", "vig_medio", "partidos"]),
        "vig_juego": pd.DataFrame(
            columns=["juego_id", "mercado", "vig_medio", "vig_mejor",
                     "n_casas"]),
        "resumen": {"juegos": 0, "casas": 0, "vig_medio": float("nan"),
                    "vig_mejor": float("nan")},
    }
    if tabla is None or not len(tabla):
        return vacio

    t = tabla.dropna(subset=["cuota"]).copy()
    t["prob"] = _prob_implicita(t["cuota"])
    t = t[t["prob"].notna()]
    if not len(t):
        return vacio

    # --- vig de cada casa: solo cuando publica los DOS lados del mercado ---
    dos_lados = t.groupby(["juego_id", "mercado", "casa"]).filter(
        lambda g: len(g) == 2 and g["lado"].nunique() == 2
    )
    vig_casa = (dos_lados.groupby(["juego_id", "mercado", "casa"])["prob"]
                .sum().sub(1).mul(100))
    vig_casa.name = "vig"

    por_casa = (
        vig_casa.groupby(level="casa").agg(["mean", "count"])
        .rename(columns={"mean": "vig_medio", "count": "partidos"})
        .reset_index()
        .sort_values("vig_medio")
        .reset_index(drop=True)
    )

    vig_partido = (
        vig_casa.groupby(level=["juego_id", "mercado"])
        .agg(["mean", "count"])
        .rename(columns={"mean": "vig_medio", "count": "n_casas"})
        .reset_index()
    )

    # --- mejor y peor precio por lado, en la línea más común del mercado ---
    def _linea_comun(serie):
        modas = serie.mode()
        return modas.iloc[0] if len(modas) else np.nan

    t["linea_comun"] = t.groupby(["juego_id", "mercado", "lado"])["linea"] \
        .transform(_linea_comun)
    misma_linea = t[t["linea"].isna() | t["linea"].eq(t["linea_comun"])]

    orden = misma_linea.sort_values(
        ["juego_id", "mercado", "lado", "cuota"],
        ascending=[True, True, True, False],
    )
    mejor = orden.drop_duplicates(["juego_id", "mercado", "lado"], keep="first")[
        ["juego_id", "mercado", "lado", "linea_comun", "cuota", "casa"]
    ].rename(columns={"cuota": "mejor_cuota", "casa": "casa_mejor",
                      "linea_comun": "linea"})
    peor = orden.drop_duplicates(["juego_id", "mercado", "lado"], keep="last")[
        ["juego_id", "mercado", "lado", "cuota", "casa"]
    ].rename(columns={"cuota": "peor_cuota", "casa": "casa_peor"})
    mejores = mejor.merge(peor, on=["juego_id", "mercado", "lado"])
    mejores["pago_mejor"] = _pago_por_dolar(mejores["mejor_cuota"])
    mejores["pago_peor"] = _pago_por_dolar(mejores["peor_cuota"])

    # --- vig tomando el mejor precio de cada lado ---
    prob_mejor = misma_linea.groupby(["juego_id", "mercado", "lado"])["prob"].min()
    cuenta = prob_mejor.groupby(level=["juego_id", "mercado"]).agg(["sum", "count"])
    vig_mejor = ((cuenta["sum"] - 1) * 100).where(cuenta["count"] == 2)
    vig_mejor = vig_mejor.rename("vig_mejor").reset_index()

    vig_juego = vig_partido.merge(
        vig_mejor, on=["juego_id", "mercado"], how="left"
    )[["juego_id", "mercado", "vig_medio", "vig_mejor", "n_casas"]]

    juegos = (
        t[["juego_id", "inicio", "local", "visitante"]]
        .drop_duplicates("juego_id")
        .reset_index(drop=True)
    )

    resumen = {
        "juegos": int(t["juego_id"].nunique()),
        "casas": int(t["casa"].nunique()),
        "vig_medio": float(por_casa["vig_medio"].mean()) if len(por_casa) else float("nan"),
        "vig_mejor": float(vig_juego["vig_mejor"].mean()) if len(vig_juego) else float("nan"),
    }
    return {"juegos": juegos, "mejores": mejores, "por_casa": por_casa,
            "vig_juego": vig_juego, "resumen": resumen}


# ---------------------------------------------------------------------------
# MODELO DE PRONÓSTICOS — walk-forward (sin ver el futuro)
# ---------------------------------------------------------------------------
# Cómo funciona (estilo "SRS", el sistema clásico de ratings por puntos):
#   - Cada equipo tiene un rating de fuerza que se estima resolviendo un
#     sistema lineal con los partidos ANTERIORES al que se quiere predecir:
#         margen ≈ ventaja_local + rating_local − rating_visitante
#         total  ≈ base + ataque_local + ataque_visitante
#                  + defensa_local + defensa_visitante
#   - Se usa una ventana móvil (por defecto, las 2 últimas temporadas) y una
#     pequeña regularización ("rigidez") para que los ratings no se disparen
#     a principio de temporada.
#   - La evaluación es WALK-FORWARD: cada partido se pronostica solo con lo
#     sucedido ANTES de él, nunca con su propio resultado (sin trampa).
# La diferencia entre el pronóstico y la línea del mercado es el "edge".


class _ModeloPuntos:
    """Sistema de ratings con ventana móvil y ajuste incremental.

    Mantiene las ecuaciones normales de dos regresiones (margen y total) y las
    resuelve al empezar cada jornada. Los métodos `agregar` y `quitar_viejos`
    actualizan las matrices sin recalcular todo, así la evaluación
    walk-forward de ~7.000 partidos corre en un par de segundos.
    """

    def __init__(self, equipos, ventana=2, rigidez=2.0):
        self.equipos = list(equipos)
        self.indice = {equipo: i for i, equipo in enumerate(self.equipos)}
        self.ventana = ventana
        n = len(self.equipos)
        # Sistema del margen: parámetros [ventaja_local, rating_1..n]
        self.n_margen = n + 1
        self.N_margen = np.eye(self.n_margen) * rigidez
        self.b_margen = np.zeros(self.n_margen)
        # Sistema del total: parámetros [base, ataque_1..n, defensa_1..n]
        self.n_total = 2 * n + 1
        self.N_total = np.eye(self.n_total) * rigidez
        self.b_total = np.zeros(self.n_total)
        self.historial = []  # (season, xm, xt, margen, total) para la ventana
        self.param_margen = None
        self.param_total = None

    def _filas(self, local, visitante):
        """Vector de características (x) de cada sistema para un partido."""
        i, j = self.indice[local], self.indice[visitante]
        n = len(self.equipos)
        xm = np.zeros(self.n_margen)
        xm[0] = 1.0          # ventaja de jugar en casa
        xm[1 + i] = 1.0      # rating del local
        xm[1 + j] = -1.0     # rating del visitante (resta)
        xt = np.zeros(self.n_total)
        xt[0] = 1.0          # base
        xt[1 + i] = 1.0      # ataque del local
        xt[1 + j] = 1.0      # ataque del visitante
        xt[1 + n + i] = 1.0  # defensa del local
        xt[1 + n + j] = 1.0  # defensa del visitante
        return xm, xt

    def agregar(self, season, local, visitante, margen, total):
        """Suma un partido al sistema (y a la ventana móvil)."""
        xm, xt = self._filas(local, visitante)
        self.N_margen += np.outer(xm, xm)
        self.b_margen += xm * margen
        self.N_total += np.outer(xt, xt)
        self.b_total += xt * total
        self.historial.append((season, xm, xt, margen, total))

    def quitar_viejos(self, season_actual):
        """Saca del ajuste los partidos fuera de la ventana móvil."""
        limite = season_actual - self.ventana + 1
        while self.historial and self.historial[0][0] < limite:
            _, xm, xt, margen, total = self.historial.pop(0)
            self.N_margen -= np.outer(xm, xm)
            self.b_margen -= xm * margen
            self.N_total -= np.outer(xt, xt)
            self.b_total -= xt * total

    def ajustar(self):
        """Resuelve los dos sistemas lineales (la rigidez ya va incluida)."""
        self.param_margen = np.linalg.solve(self.N_margen, self.b_margen)
        self.param_total = np.linalg.solve(self.N_total, self.b_total)

    def predecir(self, local, visitante):
        """Margen y total esperados (perspectiva local). NaN si falta un equipo."""
        if self.param_margen is None:
            return float("nan"), float("nan")
        if local not in self.indice or visitante not in self.indice:
            return float("nan"), float("nan")
        i, j = self.indice[local], self.indice[visitante]
        n = len(self.equipos)
        margen = (self.param_margen[0]
                  + self.param_margen[1 + i] - self.param_margen[1 + j])
        total = (self.param_total[0]
                 + self.param_total[1 + i] + self.param_total[1 + j]
                 + self.param_total[1 + n + i] + self.param_total[1 + n + j])
        return float(margen), float(total)


def _columnas_modelo(df: pd.DataFrame) -> pd.DataFrame:
    """Las columnas que necesita el modelo, en orden."""
    return df[["season", "week", "home_team", "away_team", "margen", "total_puntos"]]


def pronosticos_historicos(df_jugados: pd.DataFrame, ventana: int = 2,
                           rigidez: float = 2.0, minimo_partidos: int = 150) -> pd.DataFrame:
    """Agrega `margen_modelo` y `total_modelo` a los partidos jugados.

    Walk-forward: el pronóstico de cada partido usa solo partidos anteriores
    (los ratings se reajustan al empezar cada jornada). Si todavía no hay
    suficiente historia, el pronóstico queda vacío (NaN).
    """
    jugados = df_jugados[df_jugados["jugado"]].sort_values(
        ["season", "week"], kind="stable"
    )
    equipos = sorted(set(jugados["home_team"]) | set(jugados["away_team"]))
    modelo = _ModeloPuntos(equipos, ventana=ventana, rigidez=rigidez)

    margenes, totales = [], []
    jornada_ajustada = None
    for season, week, local, visitante, margen, total in _columnas_modelo(jugados).itertuples(
        index=False, name=None
    ):
        modelo.quitar_viejos(season)
        if (season, week) != jornada_ajustada:
            if len(modelo.historial) >= minimo_partidos:
                modelo.ajustar()
            jornada_ajustada = (season, week)
        if len(modelo.historial) >= minimo_partidos:
            m, t = modelo.predecir(local, visitante)
        else:
            m, t = float("nan"), float("nan")
        margenes.append(m)
        totales.append(t)
        modelo.agregar(season, local, visitante, margen, total)

    salida = jugados.copy()
    salida["margen_modelo"] = margenes
    salida["total_modelo"] = totales
    return salida


def pronosticos_futuros(df_jugados: pd.DataFrame, df_pendientes: pd.DataFrame,
                        ventana: int = 2, rigidez: float = 2.0) -> pd.DataFrame:
    """Pronostica los partidos pendientes con TODO lo jugado hasta ahora.

    Devuelve una copia de `df_pendientes` con `margen_modelo` y `total_modelo`.
    """
    jugados = df_jugados[df_jugados["jugado"]].sort_values(
        ["season", "week"], kind="stable"
    )
    equipos = sorted(set(jugados["home_team"]) | set(jugados["away_team"]))
    modelo = _ModeloPuntos(equipos, ventana=ventana, rigidez=rigidez)
    for season, _semana, local, visitante, margen, total in _columnas_modelo(jugados).itertuples(
        index=False, name=None
    ):
        modelo.quitar_viejos(season)
        modelo.agregar(season, local, visitante, margen, total)
    modelo.ajustar()

    pendientes = df_pendientes.copy()
    margenes, totales = [], []
    for local, visitante in pendientes[["home_team", "away_team"]].itertuples(
        index=False, name=None
    ):
        m, t = modelo.predecir(local, visitante)
        margenes.append(m)
        totales.append(t)
    pendientes["margen_modelo"] = margenes
    pendientes["total_modelo"] = totales
    return pendientes
