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
    - moneyline: probabilidad de victoria según el modelo (normal sobre el
      margen pronosticado) frente a la cuota real del mercado
    - REGISTRO de picks: estado real de cada pick (Pegó · No pegó · Push ·
      Pendiente), % de acierto y ROI por mercado, todo walk-forward
    - REGISTRO FIEL de picks (congelado al emitirse): línea, cuota y
      probabilidad EXACTAS del momento de la emisión (inmunes a los cambios
      posteriores del mercado); los picks antiguos no capturados van marcados
      como "reconstruido" (se recalculan con la línea actual)
    - CALIDAD de las probabilidades: Brier, Log Loss y calibración frente al
      mercado sin vig (una probabilidad que no dice la verdad no vale nada)
    - precios entre casas (The Odds API, opcional con clave gratuita): cuotas
      de la próxima jornada en varias casas deportivas, para comparar la
      comisión (vig) de cada una

Si no hay internet, cae de vuelta a los datos de ejemplo (data/partidos.csv).
"""

from pathlib import Path
from datetime import datetime
import math

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


def _sigma_margen(residuos, ventana: int = 500, minimo: int = 100) -> float:
    """Desvío de los errores recientes del modelo (margen real − pronóstico).

    Sirve para pasar el margen pronosticado a PROBABILIDAD de victoria con una
    normal: cuanto mejor predice el modelo, más estrecho es el desvío. Se
    calcula walk-forward (solo con errores ANTERIORES al partido a pronosticar)
    y devuelve NaN mientras no haya suficientes partidos evaluados.
    """
    if len(residuos) < minimo:
        return float("nan")
    recientes = np.asarray(residuos[-ventana:], dtype=float)
    return float(np.std(recientes, ddof=1))


def sigma_actual(df_historicos_con_modelo: pd.DataFrame) -> tuple:
    """(sigma del margen, sigma del total) con TODOS los errores disponibles.

    Para emitir los picks de la jornada PENDIENTE: los errores de los partidos
    ya jugados se conocen en ese momento, así que se usan enteros (misma
    ventana y mínimo que `_sigma_margen`). Devuelve `(nan, nan)` si aún no hay
    suficiente historia.
    """
    residuos_margen = (df_historicos_con_modelo["margen"]
                       - df_historicos_con_modelo["margen_modelo"]).dropna().tolist()
    residuos_total = (df_historicos_con_modelo["total_puntos"]
                      - df_historicos_con_modelo["total_modelo"]).dropna().tolist()
    return _sigma_margen(residuos_margen), _sigma_margen(residuos_total)


def pronosticos_historicos(df_jugados: pd.DataFrame, ventana: int = 2,
                           rigidez: float = 2.0, minimo_partidos: int = 150) -> pd.DataFrame:
    """Agrega `margen_modelo`, `total_modelo` y los dos sigmas a los jugados.

    Walk-forward: el pronóstico de cada partido usa solo partidos anteriores
    (los ratings se reajustan al empezar cada jornada). Si todavía no hay
    suficiente historia, el pronóstico queda vacío (NaN). `sigma_modelo` y
    `sigma_total_modelo` son los desvíos de los errores recientes ANTES de
    cada jornada (para pasar los pronósticos a probabilidad); NaN hasta tener
    100 errores acumulados. El sigma se CONGELA al empezar la jornada: un
    partido del jueves nunca se usa para la probabilidad del domingo.
    """
    jugados = df_jugados[df_jugados["jugado"]].sort_values(
        ["season", "week"], kind="stable"
    )
    equipos = sorted(set(jugados["home_team"]) | set(jugados["away_team"]))
    modelo = _ModeloPuntos(equipos, ventana=ventana, rigidez=rigidez)

    margenes, totales = [], []
    sigmas_margen, sigmas_total = [], []
    # Errores de pronósticos anteriores (real − modelo), por mercado:
    residuos, residuos_total = [], []
    jornada_ajustada = None
    sigma_jornada = float("nan")
    sigma_total_jornada = float("nan")
    for season, week, local, visitante, margen, total in _columnas_modelo(jugados).itertuples(
        index=False, name=None
    ):
        modelo.quitar_viejos(season)
        if (season, week) != jornada_ajustada:
            if len(modelo.historial) >= minimo_partidos:
                modelo.ajustar()
            # Sigma congelado al EMPEZAR la jornada (sin fuga dentro de la semana)
            sigma_jornada = _sigma_margen(residuos)
            sigma_total_jornada = _sigma_margen(residuos_total)
            jornada_ajustada = (season, week)
        if len(modelo.historial) >= minimo_partidos:
            m, t = modelo.predecir(local, visitante)
        else:
            m, t = float("nan"), float("nan")
        margenes.append(m)
        totales.append(t)
        sigmas_margen.append(sigma_jornada)
        sigmas_total.append(sigma_total_jornada)
        if not math.isnan(m):
            residuos.append(margen - m)
            residuos_total.append(total - t)
        modelo.agregar(season, local, visitante, margen, total)

    salida = jugados.copy()
    salida["margen_modelo"] = margenes
    salida["total_modelo"] = totales
    salida["sigma_modelo"] = sigmas_margen
    salida["sigma_total_modelo"] = sigmas_total
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


# ---------------------------------------------------------------------------
# MONEYLINE (probabilidad del modelo vs. cuota del mercado)
# ---------------------------------------------------------------------------
def _phi(z):
    """Φ(z): probabilidad acumulada de una normal estándar (sin scipy)."""
    z = np.asarray(z, dtype=float)
    if z.size == 0:  # un registro vacío es válido: devolver vacío
        return z
    return 0.5 * (1.0 + np.vectorize(math.erf, otypes=[float])(z / math.sqrt(2.0)))


def probabilidades_ml(margen_modelo, sigma_modelo):
    """Margen pronosticado → probabilidad de victoria (local, visitante).

    Usa una normal centrada en el margen con desvío `sigma_modelo` (el error
    real del modelo medido walk-forward). Los empates son rarísimos en la
    NFL; si ocurren, la apuesta se trata como push en la evaluación.
    """
    m = pd.to_numeric(pd.Series(margen_modelo), errors="coerce").astype(float)
    s = pd.to_numeric(pd.Series(sigma_modelo), errors="coerce").astype(float)
    p_local = pd.Series(_phi((m / s).to_numpy()), index=m.index)
    p_local = p_local.mask(m.isna() | s.isna() | (s <= 0))
    return p_local, 1.0 - p_local


def probabilidad_supera(valor_modelo, linea, sigma):
    """P(valor real > línea) con una normal centrada en el pronóstico.

    Sirve para pasar el margen pronosticado a probabilidad de CUBRIR el
    spread (`valor_modelo=margen_modelo`, `linea=spread_line`) y el total
    pronosticado a probabilidad de MÁS (over). Es una aproximación continua:
    los empujes exactos (push) valen ~2% y se tratan aparte en la evaluación.
    """
    v = pd.to_numeric(pd.Series(valor_modelo), errors="coerce").astype(float)
    l = pd.to_numeric(pd.Series(linea), errors="coerce").astype(float)
    s = pd.to_numeric(pd.Series(sigma), errors="coerce").astype(float)
    p = pd.Series(_phi(((v - l) / s).to_numpy()), index=v.index)
    return p.mask(v.isna() | l.isna() | s.isna() | (s <= 0))


# ---------------------------------------------------------------------------
# CALIDAD DE LAS PROBABILIDADES (Brier, Log Loss y calibración)
# ---------------------------------------------------------------------------
# Una probabilidad solo sirve si dice la verdad: si el modelo dice 60% y esos
# partidos se ganan 40% de las veces, la probabilidad ENGAÑA (y cualquier
# "valor esperado" calculado con ella también). Brier y Log Loss miden ese
# error en número (menor = mejor): decir 50% a todo da Brier 0.25.
def _prob_y_resultado(probabilidad, resultado):
    """Limpia un par (probabilidad, resultado 0/1) y descarta los vacíos."""
    p = pd.to_numeric(pd.Series(probabilidad), errors="coerce").astype(float)
    y = pd.to_numeric(pd.Series(resultado), errors="coerce").astype(float)
    valido = p.notna() & y.notna() & ((y == 0) | (y == 1))
    return p[valido], y[valido]


def brier_score(probabilidad, resultado) -> float:
    """Error cuadrático medio de una probabilidad binaria (menor = mejor).

    `resultado` va en 0/1; push y pendientes (vacíos) se descartan. NaN si no
    queda ningún caso evaluable.
    """
    p, y = _prob_y_resultado(probabilidad, resultado)
    if not len(p):
        return float("nan")
    return float(((p - y) ** 2).mean())


def log_loss(probabilidad, resultado, epsilon: float = 1e-12) -> float:
    """−log-verosimilitud media de una probabilidad binaria (menor = mejor).

    Decir 50% a todo da 0.6931. Se recortan 0 y 1 para evitar log(0).
    """
    p, y = _prob_y_resultado(probabilidad, resultado)
    if not len(p):
        return float("nan")
    p = p.clip(epsilon, 1.0 - epsilon)
    return float(-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)).mean())


def tabla_calibracion(probabilidad, resultado,
                      cortes=(0.0, 0.35, 0.45, 0.50, 0.55, 0.65, 1.0)) -> pd.DataFrame:
    """Probabilidad dicha vs frecuencia real, por tramos.

    Devuelve una fila por tramo: cuántos casos hay (`n`), la probabilidad
    media dicha (`prob_media`), la frecuencia real (`real`) y su diferencia
    (`diferencia`; negativa = la probabilidad se pasó de lista). Para pintar
    la curva de calibración. Push y pendientes se descartan.
    """
    columnas = ["tramo", "desde", "hasta", "n", "prob_media", "real", "diferencia"]
    p, y = _prob_y_resultado(probabilidad, resultado)
    if not len(p):
        return pd.DataFrame(columns=columnas)
    tramo = pd.cut(p, bins=list(cortes))
    res = (pd.DataFrame({"tramo": tramo, "p": p, "y": y})
           .groupby("tramo", observed=True)
           .agg(n=("y", "size"), prob_media=("p", "mean"), real=("y", "mean"))
           .reset_index())
    res["diferencia"] = res["real"] - res["prob_media"]
    res["desde"] = res["tramo"].map(lambda t: float(t.left))
    res["hasta"] = res["tramo"].map(lambda t: float(t.right))
    return res[columnas]


def evaluar_picks_ml(df: pd.DataFrame, umbral: float = 0.04) -> pd.DataFrame:
    """Picks del modelo al ganador (moneyline), con su resultado.

    El edge se mide en PROBABILIDAD: probabilidad del modelo − probabilidad
    sin vig del mercado. Solo se emite pick si |edge| ≥ `umbral` (0.04 = 4
    puntos porcentuales) y el partido trae cuota real. Necesita `margen_modelo`,
    `sigma_modelo` y las cuotas `home_moneyline`/`away_moneyline` (de
    `_preparar`). En empate: push (apuesta nula, no cuenta como acierto).
    La salida ya trae `prob_modelo` y `prob_mercado` DEL LADO DEL PICK.
    """
    d = df[
        df["margen_modelo"].notna() & df["sigma_modelo"].notna()
        & df["home_moneyline"].notna() & df["away_moneyline"].notna()
        & df["prob_local_sin_vig"].notna()
    ].copy()
    p_local, p_visitante = probabilidades_ml(d["margen_modelo"], d["sigma_modelo"])
    d["prob_local_modelo"] = p_local
    d["prob_visitante_modelo"] = p_visitante
    d["edge"] = d["prob_local_modelo"] - d["prob_local_sin_vig"]
    d = d[d["edge"].abs() >= umbral].copy()
    d["al_local"] = d["edge"] > 0
    d["prob_modelo"] = d["prob_local_modelo"].where(d["al_local"], d["prob_visitante_modelo"])
    d["prob_mercado"] = d["prob_local_sin_vig"].where(d["al_local"], 1.0 - d["prob_local_sin_vig"])
    d["pick"] = d["home_team"].where(d["al_local"], d["away_team"])
    d["cuota"] = d["home_moneyline"].where(d["al_local"], d["away_moneyline"])
    gano_local = d["gano_local"].astype("boolean")
    empate = d["empate"].astype("boolean").fillna(False)
    gano_visita = (~gano_local).astype("boolean") & ~empate
    d["gano"] = gano_local.where(d["al_local"], gano_visita).mask(empate)
    pago = _pago_por_dolar(d["cuota"])
    d["ganancia"] = pago.where(d["gano"].astype("boolean").fillna(False), -1.0)
    d["ganancia"] = d["ganancia"].where(d["gano"].notna(), 0.0)
    return d


# ---------------------------------------------------------------------------
# REGISTRO DE PICKS (auditoría: ¿pegó o no?)
# ---------------------------------------------------------------------------
ESTADOS_PICKS = ("Pegó", "No pegó", "Push", "Pendiente")


def estado_picks(gano, jugado) -> pd.Series:
    """Estado de cada pick para el registro: Pegó · No pegó · Push · Pendiente.

    - Se jugó y acertó → "Pegó"; se jugó y falló → "No pegó".
    - Se jugó pero quedó nula (push: exactamente la línea, o empate en
      moneyline) → "Push" (devuelve el dinero, no cuenta en el % de acierto).
    - Aún no se juega → "Pendiente".
    """
    gano = pd.Series(gano).astype("boolean")
    if np.isscalar(jugado):
        jugado = pd.Series(bool(jugado), index=gano.index)
    else:
        jugado = pd.Series(jugado).reindex(gano.index)
    jugado = jugado.astype("boolean").fillna(False).astype(bool)
    gano_bool = gano.fillna(False).astype(bool)
    estado = pd.Series("Pendiente", index=gano.index, dtype=object)
    estado[jugado & gano.notna() & gano_bool] = "Pegó"
    estado[jugado & gano.notna() & ~gano_bool] = "No pegó"
    estado[jugado & gano.isna()] = "Push"
    return estado


def resumen_picks(registro: pd.DataFrame, columna_mercado: str = "mercado") -> pd.DataFrame:
    """Agrega el registro por mercado: cuántos picks hay y cómo van.

    Espera las columnas `mercado`, `estado` y `ganancia` ($ por $1 apostado).
    Devuelve una fila por mercado con: picks, pegados, fallados, push,
    pendientes, pct_acierto (% sobre las decididas, sin push) y roi (% por $1
    sobre las resueltas; los push cuentan como $0, igual que en el resto de
    la app).
    """
    columnas = ["mercado", "picks", "pegados", "fallados", "push",
                "pendientes", "pct_acierto", "roi"]
    if not len(registro):
        return pd.DataFrame(columns=columnas)
    filas = []
    for mercado, g in registro.groupby(columna_mercado, sort=False):
        pegados = int((g["estado"] == "Pegó").sum())
        fallados = int((g["estado"] == "No pegó").sum())
        push = int((g["estado"] == "Push").sum())
        pendientes = int((g["estado"] == "Pendiente").sum())
        decididas = pegados + fallados
        pct = 100.0 * pegados / decididas if decididas else float("nan")
        resueltas = g[g["estado"] != "Pendiente"]
        roi = 100.0 * float(resueltas["ganancia"].mean()) if len(resueltas) else float("nan")
        filas.append({
            "mercado": mercado, "picks": len(g), "pegados": pegados,
            "fallados": fallados, "push": push, "pendientes": pendientes,
            "pct_acierto": pct, "roi": roi,
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# REGISTRO FIEL DE PICKS (congelado al emitirse — auditoría honesta)
# ---------------------------------------------------------------------------
# A partir de esta versión, los picks de la jornada pendiente se pueden
# CONGELAR: se guarda una fotografía con la línea, la cuota y las
# probabilidades EXACTAS del momento de la emisión (data/registro_picks.csv).
# Que el mercado mueva las líneas después NO reescribe nada: el archivo es de
# solo-añadir y ante un id repetido siempre gana la PRIMERA captura.
#
# El resultado (¿pegó?) no se guarda: se deriva al leer, con la línea
# CONGELADA y el marcador real, así que es determinista y comprobable. Los
# picks anteriores a este sistema no se pueden recuperar: la app los marca
# como "🧮 Reconstruido" (se recalculan con la línea actual) y solo lo
# capturado lleva el sello "📌 Capturado".
VERSION_MODELO = "srs-v1"  # Súbela si cambia el modelo (ventana, rigidez, sigma...)
RUTA_REGISTRO_PICKS = BASE / "registro_picks.csv"
COLUMNAS_REGISTRO_PICKS = [
    "id", "capturado_en", "temporada", "semana", "game_id", "equipo_local",
    "equipo_visitante", "mercado", "lado", "seleccion", "linea", "cuota",
    "prob_modelo", "prob_implicita", "prob_sin_vig", "edge", "ev",
    "version_modelo",
]
# Columnas comunes que debe traer el DataFrame de entrada (las arma la app):
# `linea_num`, `edge_num` y `prob_mercado` son números; `seleccion` es texto.
COLUMNAS_ENTRADA_REGISTRO = (
    "temporada", "semana", "game_id", "equipo_local", "equipo_visitante",
    "mercado", "lado", "seleccion", "linea_num", "cuota", "prob_modelo",
    "prob_mercado", "edge_num",
)


def registro_desde_picks(picks: pd.DataFrame, momento=None,
                         version: str = VERSION_MODELO) -> pd.DataFrame:
    """Jornada pendiente (columnas comunes de la pestaña 📋) → registro fiel.

    Copia la línea, la cuota y las probabilidades LITERALMENTE (sin redondear
    ni inventar) y calcula lo derivado: `id` (temporada|semana|game_id|mercado|
    lado), probabilidad implícita (con vig) y `ev` ($ por $1, aproximado: los
    empujes valen ~0 y no se descuentan). Sin cuota real, `prob_implicita` y
    `ev` quedan VACÍOS: aquí no se asume −110 nunca. Unidades del edge:
    spread/totales en puntos; moneyline en puntos de probabilidad (0–1).
    """
    if picks is None or not len(picks):
        return pd.DataFrame(columns=COLUMNAS_REGISTRO_PICKS)
    faltan = [c for c in COLUMNAS_ENTRADA_REGISTRO if c not in picks.columns]
    if faltan:
        raise ValueError(f"Faltan columnas para el registro fiel: {faltan}")
    momento = momento or datetime.now().isoformat(timespec="seconds")

    cuota = pd.to_numeric(picks["cuota"], errors="coerce")
    prob_modelo = pd.to_numeric(picks["prob_modelo"], errors="coerce")
    pago = (cuota / 100.0).where(cuota > 0, 100.0 / -cuota)
    ev = (prob_modelo * pago - (1.0 - prob_modelo)).where(
        cuota.notna() & prob_modelo.notna())

    registro = pd.DataFrame({
        "id": (picks["temporada"].astype(int).astype(str) + "|"
               + picks["semana"].astype(int).astype(str) + "|"
               + picks["game_id"].astype(str) + "|"
               + picks["mercado"].astype(str) + "|"
               + picks["lado"].astype(str)),
        "capturado_en": momento,
        "temporada": picks["temporada"].astype(int),
        "semana": picks["semana"].astype(int),
        "game_id": picks["game_id"].astype(str),
        "equipo_local": picks["equipo_local"].astype(str),
        "equipo_visitante": picks["equipo_visitante"].astype(str),
        "mercado": picks["mercado"].astype(str),
        "lado": picks["lado"].astype(str),
        "seleccion": picks["seleccion"].astype(str),
        "linea": pd.to_numeric(picks["linea_num"], errors="coerce"),
        "cuota": cuota,
        "prob_modelo": prob_modelo,
        "prob_implicita": _prob_implicita(cuota),
        "prob_sin_vig": pd.to_numeric(picks["prob_mercado"], errors="coerce"),
        "edge": pd.to_numeric(picks["edge_num"], errors="coerce"),
        "ev": ev,
        "version_modelo": version,
    })
    return registro[COLUMNAS_REGISTRO_PICKS].reset_index(drop=True)


def cargar_registro_picks(ruta=None) -> pd.DataFrame:
    """Lee el registro fiel del disco (vacío si todavía no existe).

    `ruta=None` usa `RUTA_REGISTRO_PICKS` (permite apuntar a otro archivo en
    verificación y pruebas).
    """
    ruta = Path(ruta) if ruta is not None else RUTA_REGISTRO_PICKS
    if not ruta.exists():
        return pd.DataFrame(columns=COLUMNAS_REGISTRO_PICKS)
    registro = pd.read_csv(ruta, dtype={"game_id": str})
    if "capturado_en" in registro:
        registro["capturado_en"] = registro["capturado_en"].astype(str)
    for columna in COLUMNAS_REGISTRO_PICKS:
        if columna not in registro:
            registro[columna] = float("nan")
    return registro[COLUMNAS_REGISTRO_PICKS]


def unir_registro_fiel(nuevas: pd.DataFrame, existente: pd.DataFrame) -> pd.DataFrame:
    """Une picks nuevos SIN reescribir los ya capturados: gana el PRIMERO.

    Es la garantía central del registro: una vez congelada una emisión, volver
    a capturar el mismo pick (mismo id) — aunque la línea o la cuota hayan
    cambiado — no altera nada de lo guardado.
    """
    if existente is None or not len(existente):
        columnas = COLUMNAS_REGISTRO_PICKS
        if nuevas is None or not len(nuevas):
            return pd.DataFrame(columns=columnas)
        return nuevas.drop_duplicates("id", keep="first").reset_index(drop=True)
    if nuevas is None or not len(nuevas):
        return existente.copy()
    total = pd.concat([existente, nuevas], ignore_index=True)
    return total.drop_duplicates("id", keep="first").reset_index(drop=True)


def guardar_registro_picks(registro: pd.DataFrame, ruta=None) -> Path:
    """Escribe el registro fiel en disco (CSV legible; vacíos = celda vacía)."""
    ruta = Path(ruta) if ruta is not None else RUTA_REGISTRO_PICKS
    ruta.parent.mkdir(parents=True, exist_ok=True)
    registro.to_csv(ruta, index=False, na_rep="")
    return ruta


def capturar_registro_picks(nuevas: pd.DataFrame, ruta=None) -> tuple:
    """Congela los picks nuevos y devuelve `(registro_total, nuevos, repetidos)`.

    Solo escribe si hay algo nuevo que añadir (el archivo no se reescribe por
    gusto). `ruta=None` usa el registro del proyecto.
    """
    existente = cargar_registro_picks(ruta)
    repetidos = 0
    if nuevas is not None and len(nuevas) and len(existente):
        repetidos = int(nuevas["id"].isin(existente["id"]).sum())
    total = unir_registro_fiel(nuevas, existente)
    nuevos = len(total) - len(existente)
    if nuevos:
        guardar_registro_picks(total, ruta)
    return total, nuevos, repetidos


def evaluar_registro_fiel(registro: pd.DataFrame, calendario: pd.DataFrame) -> pd.DataFrame:
    """Resultado real de cada pick capturado, con su LÍNEA CONGELADA.

    Une por `game_id` con el marcador real y decide Pegó / No pegó / Push /
    Pendiente usando lo capturado (el mercado puede haber movido la línea; da
    igual). `ganancia` ($ por $1) queda vacía si el partido no se ha jugado o
    si no había cuota real capturada: nunca se asume −110 aquí.
    """
    reg = registro.copy()
    if not len(reg):
        for columna, tipo in (("jugado", "bool"), ("gano", "boolean"),
                              ("estado", "object"), ("ganancia", "float")):
            reg[columna] = pd.Series(dtype=tipo)
        return reg

    reg["game_id"] = reg["game_id"].astype(str)
    if calendario is None or not len(calendario):
        reg["home_score"] = float("nan")
        reg["away_score"] = float("nan")
    else:
        marcadores = (calendario.drop_duplicates("game_id")
                      .assign(game_id=lambda d: d["game_id"].astype(str))
                      .set_index("game_id")[["home_score", "away_score"]])
        reg = reg.join(marcadores, on="game_id")

    home = pd.to_numeric(reg["home_score"], errors="coerce")
    away = pd.to_numeric(reg["away_score"], errors="coerce")
    margen = home - away
    total_puntos = home + away
    jugado = margen.notna()

    lado = reg["lado"].astype(str)
    linea = pd.to_numeric(reg["linea"], errors="coerce")
    es_spread = reg["mercado"].eq("Spread")
    es_total = reg["mercado"].eq("Total")
    es_ml = reg["mercado"].eq("Moneyline")

    # Diferencia desde la perspectiva del pick (línea capturada = su perspectiva):
    dif_spread = margen.where(lado.eq("local"), -margen) + linea
    dif_total = (total_puntos - linea).where(lado.eq("over"), linea - total_puntos)
    gano_ml = (margen > 0).where(lado.eq("local"), margen < 0)

    push = ((es_spread & jugado & dif_spread.eq(0))
            | (es_total & jugado & dif_total.eq(0))
            | (es_ml & jugado & margen.eq(0)))
    gano = pd.Series(pd.NA, dtype="boolean", index=reg.index)
    gano[es_spread & jugado] = dif_spread[es_spread & jugado] > 0
    gano[es_total & jugado] = dif_total[es_total & jugado] > 0
    gano[es_ml & jugado] = gano_ml[es_ml & jugado]
    gano = gano.mask(push)
    jugado = jugado.astype(bool)

    cuota = pd.to_numeric(reg["cuota"], errors="coerce")
    pago = (cuota / 100.0).where(cuota > 0, 100.0 / -cuota)
    ganancia = pd.Series(float("nan"), index=reg.index)
    con_pago = jugado & ~push & cuota.notna()
    ganancia[con_pago] = pago[con_pago].where(gano[con_pago].fillna(False), -1.0)
    ganancia[push] = 0.0

    resultado = reg.drop(columns=["home_score", "away_score"])
    resultado["jugado"] = jugado
    resultado["gano"] = gano
    resultado["estado"] = estado_picks(gano, jugado)
    resultado["ganancia"] = ganancia
    return resultado.reset_index(drop=True)
