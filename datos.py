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
