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

Si no hay internet, cae de vuelta a los datos de ejemplo (data/partidos.csv).
"""

from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).parent / "data"

URL_JUEGOS = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
URL_EQUIPOS = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"


# ---------------------------------------------------------------------------
# Descarga con caché
# ---------------------------------------------------------------------------
def _descargar(url: str, destino: Path) -> bool:
    """Descarga `url` a `destino` si no existe todavía. Devuelve True si hay archivo.

    Usamos `requests` (no urllib) porque este Python de macOS no trae los
    certificados SSL, y requests sí los incluye.
    """
    if destino.exists():
        return True
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        respuesta = requests.get(url, timeout=120)
        respuesta.raise_for_status()
        destino.write_bytes(respuesta.content)
        return True
    except Exception:
        return False


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
def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega las columnas de análisis a los datos crudos."""
    df = df.copy()

    # Margen y ganador
    df["margen"] = df["home_score"] - df["away_score"]
    df["gano_local"] = df["margen"] > 0
    df["empate"] = df["margen"] == 0

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

    # Primetime = partidos nocturnos (19:00+) o lunes/jueves
    hora = pd.to_numeric(df["gametime"].astype(str).str.slice(0, 2), errors="coerce")
    semanas_dia = df["weekday"].isin(["Monday", "Thursday"]) if "weekday" in df else False
    df["primetime"] = (hora >= 19) | semanas_dia

    df["total_puntos"] = df["home_score"] + df["away_score"]
    return df


def cargar_partidos() -> pd.DataFrame:
    """Devuelve los partidos ya jugados, con columnas de análisis."""
    if _descargar(URL_JUEGOS, BASE / "nfl_games.csv"):
        df = pd.read_csv(BASE / "nfl_games.csv", low_memory=False)
        df = df[df["home_score"].notna() & df["away_score"].notna()].copy()
        return _preparar(df)

    # Respaldo: datos de ejemplo (sin líneas de apuestas)
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
    ej["spread_line"] = float("nan")
    ej["gametime"] = "13:00"
    ej["weekday"] = "Sunday"
    return _preparar(ej)


# ---------------------------------------------------------------------------
# Utilidades de nombres/colores
# ---------------------------------------------------------------------------
def mapa_nombres(equipos: pd.DataFrame) -> dict:
    return dict(zip(equipos["team_abbr"], equipos["team_name"]))


def mapa_colores(equipos: pd.DataFrame) -> dict:
    return dict(zip(equipos["team_abbr"], equipos["team_color"]))


def con_nombre(valor: str, nombres: dict) -> str:
    """Si `valor` es una abreviatura de equipo, la cambia por el nombre largo."""
    return nombres.get(valor, valor)
