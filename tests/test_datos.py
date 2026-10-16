"""
Pruebas básicas de `datos.py` (sin internet, sin Streamlit).

Cómo correrlas (desde la carpeta del proyecto):
    .venv/bin/python -m unittest discover -s tests -t .

Cubren: cuotas y vig, convención del spread, push, totales, primetime
(incluidas las correcciones de 1999–2005), el resumen por temporada, los
precios entre casas (The Odds API), el respaldo sin conexión, el modelo de
pronósticos (que NO use información del futuro: walk-forward), las
probabilidades y picks de moneyline y el registro de picks (¿pegó?, % de
acierto y ROI).
"""

import itertools
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

import datos


# ---------------------------------------------------------------------------
# Utilidades para fabricar partidos "crudos" de laboratorio
# ---------------------------------------------------------------------------
def fila_partido(**cambios) -> dict:
    """Un partido con valores razonables; se toca solo lo que interesa."""
    base = {
        "season": 2024, "week": 1, "weekday": "Sunday", "gametime": "13:00",
        "home_team": "AAA", "away_team": "BBB",
        "home_score": 24.0, "away_score": 20.0,
        "spread_line": 3.0, "total_line": 44.0,
        "home_moneyline": -150.0, "away_moneyline": 130.0,
        "home_spread_odds": -110.0, "away_spread_odds": -110.0,
        "over_odds": -110.0, "under_odds": -110.0,
        "home_rest": 7.0, "away_rest": 7.0,
        "wind": float("nan"), "temp": float("nan"), "roof": "outdoors",
    }
    base.update(cambios)
    return base


def preparar(*filas) -> pd.DataFrame:
    return datos._preparar(pd.DataFrame([fila_partido(**f) for f in filas]))


def calendario_sintetico(fuerzas=None):
    """24 partidos (2 temporadas, 4 equipos) con fuerzas conocidas.

    Devuelve (crudo, preparado): el crudo permite falsear resultados antes
    de prepararlo (para probar que el modelo no ve el futuro).
    """
    if fuerzas is None:
        fuerzas = {"AAA": 10, "BBB": 4, "CCC": -4, "DDD": -10}
    filas = []
    for season in (2024, 2025):
        for i, (local, visitante) in enumerate(itertools.permutations(fuerzas, 2)):
            margen = fuerzas[local] - fuerzas[visitante] + 3  # +3 por localía
            filas.append(fila_partido(
                season=season, week=i // 6 + 1,
                home_team=local, away_team=visitante,
                home_score=20.0 + margen, away_score=20.0,
                spread_line=float("nan"), total_line=float("nan"),
            ))
    crudo = pd.DataFrame(filas)
    return crudo, datos._preparar(crudo)


def calendario_largo(temporadas=8):
    """Temporadas sintéticas de 17 semanas (2 partidos/semana, 4 equipos).

    Dan para 272 partidos: suficiente para que el sigma walk-forward (mínimo
    100 errores) tenga valores reales y se pueda comprobar que se congela al
    empezar cada jornada. Devuelve (crudo, preparado), igual que el corto.
    """
    fuerzas = {"AAA": 7.0, "BBB": 3.0, "CCC": -3.0, "DDD": -7.0}
    parejas = [("AAA", "BBB"), ("CCC", "DDD")]
    filas = []
    for t in range(temporadas):
        for week in range(1, 18):
            for i, (local, visitante) in enumerate(parejas):
                margen = fuerzas[local] - fuerzas[visitante] + 3 + ((week + i) % 5) - 2
                filas.append(fila_partido(
                    season=2020 + t, week=week,
                    home_team=local, away_team=visitante,
                    home_score=22.0 + margen, away_score=22.0,
                    spread_line=float("nan"), total_line=float("nan"),
                ))
    crudo = pd.DataFrame(filas)
    return crudo, datos._preparar(crudo)


# ---------------------------------------------------------------------------
class ProbabilidadYVig(unittest.TestCase):
    def test_cuota_negativa(self):
        p = datos._prob_implicita(pd.Series([-110.0]))
        self.assertAlmostEqual(p.iloc[0], 110 / 210, places=6)

    def test_cuota_positiva(self):
        p = datos._prob_implicita(pd.Series([150.0]))
        self.assertAlmostEqual(p.iloc[0], 100 / 250, places=6)

    def test_sin_cuota_es_vacio(self):
        p = datos._prob_implicita(pd.Series([0.0, float("nan")]))
        self.assertTrue(p.isna().all())

    def test_hold_del_spread(self):
        # Dos cuotas -110 suman 104.76%: la casa se queda ~4.76%
        df = preparar({})
        self.assertAlmostEqual(float(df["hold_spread"].iloc[0]), 0.0476, places=3)

    def test_prob_sin_vig_reparte_el_hold(self):
        # -150 / +130: sin vig, el local debe quedar por debajo de su 60% bruto
        df = preparar({"home_moneyline": -150.0, "away_moneyline": 130.0})
        esperado = (150 / 250) / ((150 / 250) + (100 / 230))
        self.assertAlmostEqual(float(df["prob_local_sin_vig"].iloc[0]), esperado, places=6)


class SpreadPushYUnderdog(unittest.TestCase):
    def test_local_favorito_cubre(self):
        # Línea 3 (local favorito), gana por 4 → cubre el favorito
        df = preparar({"home_score": 24.0, "away_score": 20.0, "spread_line": 3.0})
        self.assertTrue(bool(df["cubre_local"].iloc[0]))
        self.assertTrue(bool(df["cubre_favorito"].iloc[0]))

    def test_push_es_apuesta_nula(self):
        # Gana justo por 3 → push: no cuenta como acierto ni fallo
        df = preparar({"home_score": 23.0, "away_score": 20.0, "spread_line": 3.0})
        self.assertTrue(bool(df["push_spread"].iloc[0]))
        self.assertTrue(pd.isna(df["cubre_favorito"].iloc[0]))

    def test_underdog_cubre(self):
        # Local favorito por 3 y gana solo por 2 → cubre el visitante (underdog)
        df = preparar({"home_score": 22.0, "away_score": 20.0, "spread_line": 3.0})
        self.assertTrue(bool(df["cubre_visitante"].iloc[0]))
        self.assertFalse(bool(df["cubre_favorito"].iloc[0]))

    def test_local_underdog_gana(self):
        # Local underdog (línea negativa) que gana el partido
        df = preparar({"home_score": 27.0, "away_score": 20.0, "spread_line": -6.0})
        self.assertTrue(bool(df["local_underdog"].iloc[0]))
        self.assertTrue(bool(df["gano_underdog"].iloc[0]))

    def test_pickem_no_se_evalua(self):
        df = preparar({"spread_line": 0.0, "home_score": 24.0, "away_score": 20.0})
        self.assertTrue(bool(df["pickem"].iloc[0]))
        self.assertTrue(pd.isna(df["cubre_favorito"].iloc[0]))


class Totales(unittest.TestCase):
    def test_over(self):
        df = preparar({"total_line": 44.5, "home_score": 28.0, "away_score": 24.0})
        self.assertTrue(bool(df["over"].iloc[0]))

    def test_under(self):
        df = preparar({"total_line": 44.5, "home_score": 20.0, "away_score": 17.0})
        self.assertFalse(bool(df["over"].iloc[0]))

    def test_push_del_total(self):
        df = preparar({"total_line": 44.0, "home_score": 24.0, "away_score": 20.0})
        self.assertTrue(bool(df["push_total"].iloc[0]))
        self.assertTrue(pd.isna(df["over"].iloc[0]))


class Primetime(unittest.TestCase):
    def chequeo(self, resultado_esperado, *filas):
        df = preparar(*filas)
        self.assertEqual(bool(df["primetime"].iloc[0]), resultado_esperado)

    def test_nocturno_normal(self):
        self.chequeo(True, {"gametime": "20:15", "weekday": "Monday"})

    def test_tarde_no_es_primetime(self):
        self.chequeo(False, {"gametime": "16:30", "weekday": "Thursday"})

    def test_2000_a_2005_se_corrige_0900(self):
        # En la fuente, 21:00 de 2000–2005 viene como "09:00" (AM/PM perdido)
        self.chequeo(True, {"season": 2003, "gametime": "09:00", "weekday": "Monday"})

    def test_2006_en_adelante_0900_no_se_toca(self):
        self.chequeo(False, {"season": 2010, "gametime": "09:00", "weekday": "Sunday"})

    def test_1999_lunes_sin_hora_es_nocturno(self):
        self.chequeo(True, {"season": 1999, "gametime": float("nan"), "weekday": "Monday"})

    def test_1999_jueves_sin_hora_no_se_asume(self):
        self.chequeo(False, {"season": 1999, "gametime": float("nan"), "weekday": "Thursday"})


class PartidosSinJugar(unittest.TestCase):
    def test_flags_vacios(self):
        df = preparar({"home_score": float("nan"), "away_score": float("nan"),
                       "spread_line": 3.0, "total_line": 44.5})
        self.assertFalse(bool(df["jugado"].iloc[0]))
        self.assertTrue(pd.isna(df["cubre_local"].iloc[0]))
        self.assertTrue(pd.isna(df["over"].iloc[0]))
        self.assertTrue(pd.isna(df["gano_local"].iloc[0]))


class RespaldoSinInternet(unittest.TestCase):
    def test_carga_desde_el_respaldo(self):
        original = datos._descargar
        datos._descargar = lambda *a, **k: False
        try:
            calendario = datos.cargar_calendario()
            jugados = datos.cargar_partidos()
        finally:
            datos._descargar = original

        self.assertGreater(len(calendario), 0)
        columnas = {"jugado", "margen", "primetime", "hold_spread", "interior",
                    "cubre_favorito", "over", "total_puntos"}
        self.assertTrue(columnas.issubset(set(calendario.columns)))
        self.assertTrue((calendario["season"] == 0).all())
        self.assertEqual(len(jugados), int(calendario["jugado"].sum()))


class ResumenPorTemporada(unittest.TestCase):
    """La vista comparada: una fila por temporada con ROI, overs y ATS."""

    def _calendario(self):
        return preparar(
            # 2024 · favorito local cubre; total clavado (push, no cuenta)
            {"season": 2024, "home_score": 24.0, "away_score": 20.0,
             "spread_line": 3.0, "total_line": 44.0},
            # 2024 · el favorito falla; el underdog gana a cuota +115
            {"season": 2024, "week": 2, "home_score": 22.0, "away_score": 20.0,
             "spread_line": 3.0, "total_line": 40.0,
             "home_spread_odds": -105.0, "away_spread_odds": 115.0},
            # 2024 · favorito visitante (línea -6) cubre; cuota -125
            {"season": 2024, "week": 3, "home_score": 17.0, "away_score": 27.0,
             "spread_line": -6.0, "total_line": 43.5,
             "home_spread_odds": 105.0, "away_spread_odds": -125.0},
            # 2024 · push contra la línea (no cuenta en ATS); under
            {"season": 2024, "week": 4, "home_score": 23.0, "away_score": 20.0,
             "spread_line": 3.0, "total_line": 45.0},
            # 2025 · sin cuotas → se asume la estándar -110
            {"season": 2025, "home_score": 30.0, "away_score": 10.0,
             "spread_line": 7.0, "total_line": 38.0,
             "home_spread_odds": float("nan"), "away_spread_odds": float("nan")},
        )

    def test_metricas_de_2024(self):
        r = datos.resumen_por_temporada(self._calendario()).set_index("temporada")
        fila = r.loc[2024]
        self.assertEqual(int(fila["partidos"]), 4)
        self.assertAlmostEqual(fila["puntos_por_partido"], 43.25, places=2)
        # overs: 2 de 3 (el push del total no cuenta)
        self.assertAlmostEqual(fila["pct_overs"], 200 / 3, places=1)
        # favoritos: cubrió, falló, cubrió (el push no cuenta) → 2 de 3
        self.assertAlmostEqual(fila["pct_favoritos"], 200 / 3, places=1)
        # ROI favoritos: +100/110, −1 y +100/125 → media de 3 apuestas
        esperado_fav = (100 / 110 - 1 + 100 / 125) / 3 * 100
        self.assertAlmostEqual(fila["roi_favoritos"], esperado_fav, places=2)
        # ROI underdogs: −1, +115/100 y −1 (cada lado cobra SU cuota)
        esperado_dog = (-1 + 115 / 100 - 1) / 3 * 100
        self.assertAlmostEqual(fila["roi_underdogs"], esperado_dog, places=2)

    def test_2025_sin_cuota_usa_menos_110(self):
        r = datos.resumen_por_temporada(self._calendario()).set_index("temporada")
        fila = r.loc[2025]
        self.assertAlmostEqual(fila["roi_favoritos"], 100 / 110 * 100, places=2)
        self.assertAlmostEqual(fila["roi_underdogs"], -100.0, places=2)

    def test_filtro_desde(self):
        r = datos.resumen_por_temporada(self._calendario(), desde=2025)
        self.assertEqual(list(r["temporada"]), [2025])

    def test_sin_datos_devuelve_tabla_vacia(self):
        r = datos.resumen_por_temporada(self._calendario(), desde=2030)
        self.assertTrue(r.empty)
        self.assertIn("temporada", r.columns)


class PreciosEntreCasas(unittest.TestCase):
    """Cuotas de la próxima jornada en varias casas (The Odds API)."""

    @staticmethod
    def _payload():
        """Respuesta de laboratorio: 1 partido, 3 casas, spreads y totales."""
        return [{
            "id": "juego1",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2026-10-18T17:00:00Z",
            "home_team": "Kansas City Chiefs",
            "away_team": "Buffalo Bills",
            "bookmakers": [
                {"key": "draftkings", "title": "DraftKings", "markets": [
                    {"key": "spreads", "outcomes": [
                        {"name": "Kansas City Chiefs", "price": -110, "point": -3.0},
                        {"name": "Buffalo Bills", "price": -110, "point": 3.0},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": -110, "point": 48.5},
                        {"name": "Under", "price": -110, "point": 48.5},
                    ]},
                ]},
                {"key": "fanduel", "title": "FanDuel", "markets": [
                    {"key": "spreads", "outcomes": [
                        {"name": "Kansas City Chiefs", "price": -105, "point": -3.0},
                        {"name": "Buffalo Bills", "price": -115, "point": 3.0},
                    ]},
                ]},
                {"key": "betmgm", "title": "BetMGM", "markets": [
                    {"key": "spreads", "outcomes": [
                        {"name": "Kansas City Chiefs", "price": -112, "point": -3.0},
                        {"name": "Buffalo Bills", "price": -108, "point": 3.0},
                    ]},
                ]},
            ],
        }]

    def _analisis(self):
        return datos.analizar_precios_casas(
            datos.parsear_precios_casas(self._payload()))

    def test_parsear_tabla_larga(self):
        tabla = datos.parsear_precios_casas(self._payload())
        self.assertEqual(len(tabla), 8)
        self.assertEqual(set(tabla["mercado"]), {"spreads", "totals"})
        self.assertEqual(set(tabla["casa"]),
                         {"DraftKings", "FanDuel", "BetMGM"})
        # una casa sin totales se parsea igual (no rompe nada)
        self.assertEqual(len(tabla[tabla["casa"] == "FanDuel"]), 2)
        self.assertTrue(pd.api.types.is_numeric_dtype(tabla["cuota"]))
        self.assertEqual(tabla["linea"].dropna().iloc[0], -3.0)

    def test_parsear_sin_juegos(self):
        tabla = datos.parsear_precios_casas([])
        self.assertTrue(tabla.empty)
        self.assertIn("cuota", tabla.columns)

    def test_mejor_y_peor_precio(self):
        mejores = self._analisis()["mejores"]
        kc = mejores[(mejores["lado"] == "Kansas City Chiefs")
                     & (mejores["mercado"] == "spreads")].iloc[0]
        self.assertEqual(kc["mejor_cuota"], -105)
        self.assertEqual(kc["casa_mejor"], "FanDuel")
        self.assertEqual(kc["peor_cuota"], -112)
        self.assertEqual(kc["casa_peor"], "BetMGM")
        self.assertAlmostEqual(kc["pago_mejor"], 100 / 105, places=4)
        self.assertAlmostEqual(kc["pago_peor"], 100 / 112, places=4)
        buf = mejores[(mejores["lado"] == "Buffalo Bills")
                      & (mejores["mercado"] == "spreads")].iloc[0]
        self.assertEqual(buf["mejor_cuota"], -108)
        self.assertEqual(buf["casa_mejor"], "BetMGM")

    def test_vig_por_casa(self):
        por_casa = self._analisis()["por_casa"].set_index("casa")
        dfu = (105 / 205 + 115 / 215 - 1) * 100
        self.assertAlmostEqual(por_casa.loc["FanDuel", "vig_medio"], dfu,
                               places=2)
        self.assertAlmostEqual(
            por_casa.loc["DraftKings", "vig_medio"], (110 / 210) * 2 * 100 - 100,
            places=2)
        # DraftKings cubre spreads y totales (2 mercados)
        self.assertEqual(por_casa.loc["DraftKings", "partidos"], 2)
        # ordenada de la casa más barata a la más cara
        self.assertEqual(list(por_casa.index),
                         ["FanDuel", "BetMGM", "DraftKings"])

    def test_vig_juego_y_mejor_precio(self):
        analisis = self._analisis()
        vj = analisis["vig_juego"].set_index("mercado")
        v_mejor_spread = (105 / 205 + 108 / 208 - 1) * 100
        self.assertAlmostEqual(vj.loc["spreads", "vig_mejor"], v_mejor_spread,
                               places=2)
        self.assertAlmostEqual(
            vj.loc["spreads", "vig_medio"],
            ((110 / 210) * 2 * 100 - 100 + (105 / 205 + 115 / 215 - 1) * 100
             + (112 / 212 + 108 / 208 - 1) * 100) / 3,
            places=2)
        self.assertEqual(vj.loc["spreads", "n_casas"], 3)
        # totales: solo DraftKings publica los dos lados
        self.assertEqual(vj.loc["totals", "n_casas"], 1)
        self.assertAlmostEqual(vj.loc["totals", "vig_mejor"],
                               (110 / 210) * 2 * 100 - 100, places=2)
        r = analisis["resumen"]
        self.assertEqual(r["juegos"], 1)
        self.assertEqual(r["casas"], 3)
        self.assertLess(r["vig_mejor"], r["vig_medio"])  # comparar ayuda

    def test_abreviatura_de(self):
        equipos = pd.DataFrame({
            "team_abbr": ["KC", "WAS", "LAR", "STL"],
            "team_name": ["Kansas City Chiefs", "Washington Commanders",
                          "Los Angeles Rams", "St. Louis Rams"],
            "team_nick": ["Chiefs", "Commanders", "Rams", "Rams"],
        })
        self.assertEqual(
            datos.abreviatura_de("Kansas City Chiefs", equipos), "KC")
        # solo el apodo (nombre que no está exacto) también vale
        self.assertEqual(datos.abreviatura_de("Commanders", equipos), "WAS")
        self.assertIsNone(datos.abreviatura_de("Toronto Raptors", equipos))
        self.assertIsNone(datos.abreviatura_de("Chiefs", None))

    def test_analizar_sin_datos(self):
        vacio = datos.analizar_precios_casas(pd.DataFrame())
        self.assertEqual(vacio["resumen"]["juegos"], 0)
        self.assertTrue(vacio["mejores"].empty)

    def test_cargar_clave_invalida(self):
        class Respuesta:
            status_code = 401
            headers = {}
            text = ""

        with mock.patch.object(datos.requests, "get", return_value=Respuesta()):
            with self.assertRaises(ValueError) as caso:
                datos.cargar_precios_casas("clave_mala")
        self.assertIn("no es válida", str(caso.exception))

    def test_cargar_ok_con_encabezados(self):
        payload = self._payload()

        class Respuesta:
            status_code = 200
            headers = {"x-requests-used": "2",
                       "x-requests-remaining": "498",
                       "x-requests-last": "2"}
            text = ""

            def json(self):
                return payload

        with mock.patch.object(datos.requests, "get",
                               return_value=Respuesta()) as falso:
            tabla, uso = datos.cargar_precios_casas("clave_de_prueba")

        self.assertEqual(len(tabla), 8)
        self.assertEqual(uso["restantes"], "498")
        self.assertEqual(falso.call_args.kwargs["params"]["regions"], "us")


class ModeloDePronosticos(unittest.TestCase):
    def test_walk_forward_sin_ver_el_futuro(self):
        """Cambiar el resultado del ÚLTIMO partido no puede cambiar el pasado."""
        crudo, cal = calendario_sintetico()
        salida1 = datos.pronosticos_historicos(cal, minimo_partidos=10)

        crudo2 = crudo.copy()
        crudo2.loc[crudo2.index[-1], "home_score"] = 120.0  # escándalo final
        cal2 = datos._preparar(crudo2)
        salida2 = datos.pronosticos_historicos(cal2, minimo_partidos=10)

        np.testing.assert_allclose(
            salida1["margen_modelo"].to_numpy()[:-1],
            salida2["margen_modelo"].to_numpy()[:-1],
            equal_nan=True,
        )

    def test_hay_historia_minima_y_luego_pronostica(self):
        _, cal = calendario_sintetico()
        salida = datos.pronosticos_historicos(cal, minimo_partidos=10)
        self.assertTrue(salida["margen_modelo"].iloc[:5].isna().all())
        self.assertGreater(int(salida["margen_modelo"].notna().sum()), 5)

    def test_el_fuerte_puntua_mas_que_el_flojo(self):
        _, cal = calendario_sintetico()
        salida = datos.pronosticos_historicos(cal, minimo_partidos=10)
        ultima = salida[salida["season"] == 2025]
        fuerte = ultima[ultima["home_team"] == "AAA"]["margen_modelo"].mean()
        flojo = ultima[ultima["home_team"] == "DDD"]["margen_modelo"].mean()
        self.assertGreater(fuerte, flojo + 10)

    def test_futuros_pronostica_y_tolera_desconocidos(self):
        _, cal = calendario_sintetico()
        pendiente = datos._preparar(pd.DataFrame([
            fila_partido(season=2026, week=1, home_team="AAA", away_team="DDD",
                         home_score=float("nan"), away_score=float("nan")),
        ]))
        fut = datos.pronosticos_futuros(cal, pendiente)
        self.assertTrue(np.isfinite(fut["margen_modelo"].iloc[0]))
        self.assertGreater(fut["margen_modelo"].iloc[0], 10)

        raro = datos._preparar(pd.DataFrame([
            fila_partido(season=2026, week=1, home_team="ZZZ", away_team="AAA",
                         home_score=float("nan"), away_score=float("nan")),
        ]))
        fut_raro = datos.pronosticos_futuros(cal, raro)
        self.assertTrue(np.isnan(fut_raro["margen_modelo"].iloc[0]))

    def test_parametros_por_defecto_son_los_del_modelo_validado(self):
        """Los defectos son los del srs-v2 (ventana 2, rigidez 8): validadas
        en el Bloque 3 con selección 2006–2017 y holdout 2018–2025."""
        _, cal = calendario_sintetico()
        por_defecto = datos.pronosticos_historicos(cal, minimo_partidos=10)
        explicito = datos.pronosticos_historicos(
            cal, ventana=2, rigidez=8.0, minimo_partidos=10)
        np.testing.assert_allclose(
            por_defecto["margen_modelo"].to_numpy(),
            explicito["margen_modelo"].to_numpy(),
            equal_nan=True,
        )
        self.assertEqual(datos.VERSION_MODELO, "srs-v2")

    def test_mas_rigidez_encoge_los_pronosticos(self):
        """Rigidez alta = ratings más prudentes: los pronósticos se acercan
        al centro en vez de dispararse con poca historia."""
        _, cal = calendario_sintetico()
        blando = datos.pronosticos_historicos(cal, rigidez=1.0, minimo_partidos=10)
        duro = datos.pronosticos_historicos(cal, rigidez=32.0, minimo_partidos=10)
        self.assertLess(
            duro["margen_modelo"].abs().max(),
            blando["margen_modelo"].abs().max(),
        )


class PicksMoneylineYRegistro(unittest.TestCase):
    """Probabilidades del moneyline, picks ML y el registro (¿pegó o no?)."""

    def _juego_ml(self, margen_modelo=6.0, sigma_modelo=13.0, **cambios):
        """Un partido preparado con pronóstico del modelo ya puesto."""
        d = preparar(cambios)
        d["margen_modelo"] = margen_modelo
        d["sigma_modelo"] = sigma_modelo
        return d

    # --- probabilidades ---------------------------------------------------
    def test_probabilidades_ml_simetria_y_crecimiento(self):
        p50, v50 = datos.probabilidades_ml(pd.Series([0.0]), pd.Series([13.0]))
        self.assertAlmostEqual(float(p50.iloc[0]), 0.5, places=6)
        self.assertAlmostEqual(float(v50.iloc[0]), 0.5, places=6)

        p1s, _ = datos.probabilidades_ml(pd.Series([13.0]), pd.Series([13.0]))
        self.assertGreater(float(p1s.iloc[0]), 0.80)  # +1σ ≈ 84%

        p2n, v2n = datos.probabilidades_ml(pd.Series([-26.0]), pd.Series([13.0]))
        self.assertLess(float(p2n.iloc[0]), 0.03)    # −2σ ≈ 2%
        self.assertAlmostEqual(
            float(p2n.iloc[0]) + float(v2n.iloc[0]), 1.0, places=10)

        sin_sigma, _ = datos.probabilidades_ml(pd.Series([5.0]), pd.Series([float("nan")]))
        self.assertTrue(np.isnan(float(sin_sigma.iloc[0])))

    # --- evaluación de picks ML ------------------------------------------
    def test_pick_ml_local_gana(self):
        # El mercado da ~58% al local (sin vig) y el modelo cree ~82%: pick AAA.
        d = self._juego_ml(margen_modelo=12.0)
        ml = datos.evaluar_picks_ml(d, umbral=0.04)
        self.assertEqual(len(ml), 1)
        self.assertTrue(bool(ml["al_local"].iloc[0]))
        self.assertEqual(ml["pick"].iloc[0], "AAA")
        self.assertEqual(float(ml["cuota"].iloc[0]), -150.0)
        self.assertTrue(bool(ml["gano"].iloc[0]))  # AAA ganó 24-20
        self.assertAlmostEqual(float(ml["ganancia"].iloc[0]), 100 / 150, places=6)

    def test_pick_ml_visitante_falla(self):
        d = self._juego_ml(margen_modelo=-12.0)
        ml = datos.evaluar_picks_ml(d, umbral=0.04)
        self.assertEqual(len(ml), 1)
        self.assertFalse(bool(ml["al_local"].iloc[0]))
        self.assertEqual(ml["pick"].iloc[0], "BBB")
        self.assertEqual(float(ml["cuota"].iloc[0]), 130.0)
        self.assertFalse(bool(ml["gano"].iloc[0]))  # BBB perdió 20-24
        self.assertEqual(float(ml["ganancia"].iloc[0]), -1.0)

    def test_umbral_y_cuotas_obligatorias(self):
        # Edge pequeño (margen 3 ≈ 59% vs 58% del mercado): no llega al umbral.
        d = self._juego_ml(margen_modelo=3.0)
        self.assertTrue(datos.evaluar_picks_ml(d, umbral=0.04).empty)
        # Sin cuotas reales no hay pick posible.
        d2 = self._juego_ml(margen_modelo=12.0,
                            home_moneyline=float("nan"), away_moneyline=float("nan"))
        self.assertTrue(datos.evaluar_picks_ml(d2, umbral=0.04).empty)

    def test_empate_en_ml_es_push(self):
        d = self._juego_ml(margen_modelo=12.0, home_score=20.0, away_score=20.0)
        ml = datos.evaluar_picks_ml(d, umbral=0.04)
        self.assertEqual(len(ml), 1)
        self.assertTrue(pd.isna(ml["gano"].iloc[0]))
        self.assertEqual(float(ml["ganancia"].iloc[0]), 0.0)

    def test_pendiente_queda_pendiente(self):
        d = self._juego_ml(margen_modelo=12.0,
                           home_score=float("nan"), away_score=float("nan"))
        ml = datos.evaluar_picks_ml(d, umbral=0.04)
        self.assertEqual(len(ml), 1)
        self.assertTrue(pd.isna(ml["gano"].iloc[0]))
        estado = datos.estado_picks(ml["gano"], ml["jugado"])
        self.assertEqual(estado.iloc[0], "Pendiente")

    # --- sigma walk-forward -----------------------------------------------
    def test_sigma_margen_matematicas(self):
        self.assertTrue(np.isnan(datos._sigma_margen([1.0, 2.0], minimo=5)))
        residuos = [1.0, -1.0, 1.0, -1.0, 2.0]
        self.assertAlmostEqual(
            datos._sigma_margen(residuos, minimo=3),
            float(np.std(residuos, ddof=1)), places=10)
        # Solo mira la ventana reciente.
        largos = [0.0] * 50 + [3.0, 3.0]
        self.assertAlmostEqual(datos._sigma_margen(largos, ventana=2, minimo=2), 0.0)

    def test_sigma_sale_en_pronosticos_y_no_ve_el_futuro(self):
        crudo, cal = calendario_sintetico()
        s1 = datos.pronosticos_historicos(cal, minimo_partidos=10)
        self.assertIn("sigma_modelo", s1.columns)
        # Con tan pocos partidos aún no hay 100 errores acumulados: vacío.
        self.assertTrue(s1["sigma_modelo"].isna().all())

        crudo2 = crudo.copy()
        crudo2.loc[crudo2.index[-1], "home_score"] = 120.0
        s2 = datos.pronosticos_historicos(datos._preparar(crudo2), minimo_partidos=10)
        np.testing.assert_allclose(
            s1["sigma_modelo"].to_numpy()[:-1],
            s2["sigma_modelo"].to_numpy()[:-1],
            equal_nan=True,
        )

    # --- registro ----------------------------------------------------------
    def test_estado_picks_cuatro_casos(self):
        gano = pd.Series([True, False, pd.NA, pd.NA], dtype="boolean")
        jugado = pd.Series([True, True, True, False])
        estados = datos.estado_picks(gano, jugado)
        self.assertEqual(list(estados), ["Pegó", "No pegó", "Push", "Pendiente"])
        # Con el flag escalar (partidos ya jugados) debe alinear, no perderse.
        estados2 = datos.estado_picks(gano, True)
        self.assertEqual(len(estados2), 4)
        self.assertEqual(list(estados2), ["Pegó", "No pegó", "Push", "Push"])

    def test_resumen_picks_matematicas(self):
        registro = pd.DataFrame({
            "mercado": ["Spread"] * 4,
            "estado": ["Pegó", "No pegó", "Push", "Pendiente"],
            "ganancia": [0.909, -1.0, 0.0, 0.0],
        })
        res = datos.resumen_picks(registro)
        self.assertEqual(len(res), 1)
        fila = res.iloc[0]
        self.assertEqual(int(fila["picks"]), 4)
        self.assertEqual(int(fila["pegados"]), 1)
        self.assertEqual(int(fila["fallados"]), 1)
        self.assertEqual(int(fila["push"]), 1)
        self.assertEqual(int(fila["pendientes"]), 1)
        self.assertAlmostEqual(float(fila["pct_acierto"]), 50.0)
        self.assertAlmostEqual(
            float(fila["roi"]), (0.909 - 1.0 + 0.0) / 3 * 100, places=6)

    def test_resumen_picks_vacio_y_pendientes(self):
        vacio = datos.resumen_picks(pd.DataFrame(columns=["mercado", "estado", "ganancia"]))
        self.assertTrue(vacio.empty)
        self.assertIn("pct_acierto", vacio.columns)

        solo_pendientes = datos.resumen_picks(pd.DataFrame({
            "mercado": ["Total", "Total"],
            "estado": ["Pendiente", "Pendiente"],
            "ganancia": [0.0, 0.0],
        }))
        fila = solo_pendientes.iloc[0]
        self.assertEqual(int(fila["pendientes"]), 2)
        self.assertTrue(np.isnan(float(fila["pct_acierto"])))
        self.assertTrue(np.isnan(float(fila["roi"])))


class MetricasDeProbabilidad(unittest.TestCase):
    """Brier, Log Loss, calibración y la probabilidad de cubrir (Fase 6).

    Una probabilidad que no dice la verdad no vale nada: estas utilidades son
    las que permiten medirlo y compararlo con el mercado.
    """

    def test_probabilidad_supera_normal(self):
        p = datos.probabilidad_supera(
            pd.Series([3.0, 16.0, 3.0, float("nan")]),
            pd.Series([3.0, 3.0, 6.0, 3.0]),
            pd.Series([13.0, 13.0, 13.0, 13.0]),
        )
        self.assertAlmostEqual(float(p.iloc[0]), 0.5, places=6)  # clava la línea
        self.assertGreater(float(p.iloc[1]), 0.80)               # +1σ ≈ 84%
        self.assertLess(float(p.iloc[2]), 0.45)                  # por debajo
        self.assertTrue(np.isnan(float(p.iloc[3])))              # sin pronóstico
        # Sin sigma válido no hay probabilidad.
        vacio = datos.probabilidad_supera(
            pd.Series([3.0]), pd.Series([3.0]), pd.Series([0.0]))
        self.assertTrue(np.isnan(float(vacio.iloc[0])))

    def test_brier_matematicas(self):
        self.assertAlmostEqual(
            datos.brier_score(pd.Series([1.0, 0.0]), pd.Series([1.0, 0.0])), 0.0)
        self.assertAlmostEqual(
            datos.brier_score(pd.Series([0.0]), pd.Series([1.0])), 1.0)
        self.assertAlmostEqual(
            datos.brier_score(pd.Series([0.5, 0.5]), pd.Series([1, 0])), 0.25)
        # Vacíos (push / pendiente) se descartan; sin casos evaluables: NaN.
        self.assertAlmostEqual(
            datos.brier_score(pd.Series([0.5, pd.NA]), pd.Series([1, pd.NA])), 0.25)
        self.assertTrue(np.isnan(
            datos.brier_score(pd.Series([0.5]), pd.Series([pd.NA]))))

    def test_log_loss_matematicas(self):
        self.assertAlmostEqual(
            datos.log_loss(pd.Series([0.5]), pd.Series([1])), math.log(2), places=10)
        self.assertAlmostEqual(
            datos.log_loss(pd.Series([1.0]), pd.Series([1])), 0.0)
        # Extremos recortados (no explota con 0 o 1).
        self.assertTrue(np.isfinite(datos.log_loss(pd.Series([1.0]), pd.Series([0]))))

    def test_tabla_calibracion(self):
        p = pd.Series([0.4] * 10 + [0.6] * 10)
        y = pd.Series([1, 1, 1, 1, 0, 0, 0, 0, 0, 0] + [1, 1, 1, 1, 1, 1, 0, 0, 0, 0])
        tabla = datos.tabla_calibracion(p, y, cortes=(0.0, 0.5, 1.0))
        self.assertEqual(len(tabla), 2)
        primera, segunda = tabla.iloc[0], tabla.iloc[1]
        self.assertEqual(int(primera["n"]), 10)
        self.assertAlmostEqual(float(primera["prob_media"]), 0.4)
        self.assertAlmostEqual(float(primera["real"]), 0.4)
        self.assertAlmostEqual(float(primera["diferencia"]), 0.0)
        self.assertAlmostEqual(float(primera["desde"]), 0.0)
        self.assertAlmostEqual(float(segunda["prob_media"]), 0.6)
        self.assertAlmostEqual(float(segunda["real"]), 0.6)
        # Vacíos fuera y tabla vacía sin filas.
        self.assertEqual(int(datos.tabla_calibracion(
            pd.Series([0.9, pd.NA]), pd.Series([1, 1]),
            cortes=(0.0, 0.95, 1.0))["n"].sum()), 1)
        self.assertTrue(datos.tabla_calibracion(
            pd.Series([pd.NA]), pd.Series([pd.NA])).empty)

    def test_sigma_total_walk_forward_y_congelado_por_jornada(self):
        crudo, cal = calendario_largo()
        hist = datos.pronosticos_historicos(cal, minimo_partidos=10)
        self.assertIn("sigma_total_modelo", hist.columns)
        for columna in ("sigma_modelo", "sigma_total_modelo"):
            con_sigma = hist[hist[columna].notna()]
            self.assertGreater(len(con_sigma), 0)
            # Congelado al empezar la jornada: un solo valor por (temporada, semana).
            por_jornada = con_sigma.groupby(["season", "week"])[columna].nunique()
            self.assertTrue((por_jornada <= 1).all())
        # No ver el futuro: falsear el ÚLTIMO resultado no cambia ningún sigma.
        crudo2 = crudo.copy()
        crudo2.loc[crudo2.index[-1], "home_score"] += 40.0
        s2 = datos.pronosticos_historicos(datos._preparar(crudo2), minimo_partidos=10)
        np.testing.assert_allclose(
            hist["sigma_modelo"].to_numpy(), s2["sigma_modelo"].to_numpy(),
            equal_nan=True)
        np.testing.assert_allclose(
            hist["sigma_total_modelo"].to_numpy(), s2["sigma_total_modelo"].to_numpy(),
            equal_nan=True)

    def test_sigma_actual_usa_todos_los_errores(self):
        _, cal = calendario_largo()
        hist = datos.pronosticos_historicos(cal, minimo_partidos=10)
        s_margen, s_total = datos.sigma_actual(hist)
        self.assertTrue(np.isfinite(s_margen) and s_margen > 0)
        self.assertTrue(np.isfinite(s_total) and s_total > 0)
        esperado = datos._sigma_margen(
            (hist["margen"] - hist["margen_modelo"]).dropna().tolist())
        self.assertAlmostEqual(s_margen, esperado, places=10)
        esperado_t = datos._sigma_margen(
            (hist["total_puntos"] - hist["total_modelo"]).dropna().tolist())
        self.assertAlmostEqual(s_total, esperado_t, places=10)


class RegistroFielDePicks(unittest.TestCase):
    """Captura congelada al emitir, inmutabilidad y evaluación honesta.

    La promesa central: una vez capturado un pick, aunque el mercado mueva la
    línea, su selección, línea, cuota y probabilidad NO cambian; el resultado
    se decide con la línea CONGELADA.
    """

    def _fila_registro(self, **cambios) -> dict:
        """Una fila con las columnas comunes que la app manda al registro."""
        base = {
            "temporada": 2026, "semana": 6, "game_id": "2026_06_AAA_BBB",
            "equipo_local": "AAA", "equipo_visitante": "BBB",
            "mercado": "Spread", "lado": "local", "seleccion": "AAA -3.5",
            "linea_num": -3.5, "cuota": -110.0, "prob_modelo": 0.62,
            "prob_mercado": 0.52, "edge_num": 2.0,
        }
        base.update(cambios)
        return base

    def test_registro_desde_picks_columnas_y_derivados(self):
        entrada = pd.DataFrame([self._fila_registro()])
        reg = datos.registro_desde_picks(entrada, momento="2026-10-16T10:00:00")
        self.assertEqual(list(reg.columns), datos.COLUMNAS_REGISTRO_PICKS)
        fila = reg.iloc[0]
        self.assertEqual(fila["id"], "2026|6|2026_06_AAA_BBB|Spread|local")
        self.assertEqual(fila["capturado_en"], "2026-10-16T10:00:00")
        self.assertEqual(fila["version_modelo"], datos.VERSION_MODELO)
        self.assertAlmostEqual(float(fila["prob_implicita"]), 110.0 / 210.0, places=6)
        self.assertAlmostEqual(
            float(fila["ev"]), 0.62 * (100.0 / 110.0) - 0.38, places=6)
        self.assertAlmostEqual(float(fila["linea"]), -3.5)
        self.assertAlmostEqual(float(fila["prob_sin_vig"]), 0.52)

        # Sin cuota real: ni probabilidad implícita ni EV inventados.
        sin_cuota = datos.registro_desde_picks(
            pd.DataFrame([self._fila_registro(cuota=float("nan"))]))
        self.assertTrue(np.isnan(float(sin_cuota["prob_implicita"].iloc[0])))
        self.assertTrue(np.isnan(float(sin_cuota["ev"].iloc[0])))

        # Entrada vacía → vacío con columnas; columnas que faltan → error claro.
        self.assertTrue(datos.registro_desde_picks(pd.DataFrame()).empty)
        with self.assertRaises(ValueError):
            datos.registro_desde_picks(pd.DataFrame([{"temporada": 2026}]))

    def test_registro_usa_ev_num_del_motor_si_viene(self):
        """El EV del motor F5 (push explícito) se guarda TAL CUAL."""
        fila = self._fila_registro(ev_num=-0.0123)
        reg = datos.registro_desde_picks(
            pd.DataFrame([fila]), momento="2026-10-16T10:00:00")
        self.assertAlmostEqual(float(reg["ev"].iloc[0]), -0.0123, places=12)

    def test_registro_sin_ev_num_conserva_la_formula_aproximada(self):
        """Sin `ev_num` (histórico/pruebas) no cambia nada: fórmula de siempre."""
        fila = self._fila_registro(ev_num=float("nan"))
        reg = datos.registro_desde_picks(
            pd.DataFrame([fila]), momento="2026-10-16T10:00:00")
        self.assertAlmostEqual(
            float(reg["ev"].iloc[0]), 0.62 * (100.0 / 110.0) - 0.38, places=12)

    def test_registro_mezcla_ev_num_y_fallback(self):
        f1 = self._fila_registro(ev_num=-0.01)
        f2 = self._fila_registro(game_id="2026_06_AAA_CCC",
                                 ev_num=float("nan"))
        reg = datos.registro_desde_picks(
            pd.DataFrame([f1, f2]), momento="2026-10-16T10:00:00")
        self.assertAlmostEqual(float(reg["ev"].iloc[0]), -0.01, places=12)
        self.assertAlmostEqual(
            float(reg["ev"].iloc[1]), 0.62 * (100.0 / 110.0) - 0.38, places=12)

    def test_captura_dedupe_y_congelacion(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "registro.csv"
            original = datos.registro_desde_picks(
                pd.DataFrame([self._fila_registro()]), momento="2026-10-16T10:00:00")
            total, nuevos, repetidos = datos.capturar_registro_picks(original, ruta=ruta)
            self.assertEqual((len(total), nuevos, repetidos), (1, 1, 0))
            # El mercado mueve la línea: recapturar NO reescribe lo congelado.
            cambiada = datos.registro_desde_picks(
                pd.DataFrame([self._fila_registro(
                    linea_num=-2.5, cuota=-115.0, edge_num=3.1)]),
                momento="2026-10-17T18:00:00")
            total2, nuevos2, repetidos2 = datos.capturar_registro_picks(cambiada, ruta=ruta)
            self.assertEqual((len(total2), nuevos2, repetidos2), (1, 0, 1))
            self.assertAlmostEqual(float(total2["linea"].iloc[0]), -3.5)
            self.assertAlmostEqual(float(total2["cuota"].iloc[0]), -110.0)
            self.assertEqual(total2["capturado_en"].iloc[0], "2026-10-16T10:00:00")
            # El archivo en disco conserva la primera captura.
            leido = datos.cargar_registro_picks(ruta=ruta)
            self.assertAlmostEqual(float(leido["linea"].iloc[0]), -3.5)

    def test_resultado_usa_la_linea_congelada(self):
        reg = datos.registro_desde_picks(pd.DataFrame([self._fila_registro()]))
        calendario = pd.DataFrame([
            {"game_id": "2026_06_AAA_BBB", "home_score": 23.0, "away_score": 20.0}])
        resultado = datos.evaluar_registro_fiel(reg, calendario)
        # AAA ganó por 3: con la línea congelada (-3.5) NO cubre…
        self.assertEqual(resultado["estado"].iloc[0], "No pegó")
        self.assertAlmostEqual(float(resultado["ganancia"].iloc[0]), -1.0)
        # …aunque la línea de HOY (-2.5) diría que sí: da igual, manda la capturada.
        con_linea_actual = reg.assign(linea=-2.5)
        self.assertEqual(
            datos.evaluar_registro_fiel(con_linea_actual, calendario)["estado"].iloc[0],
            "Pegó")
        # Sin marcador (pendiente): ni resultado ni ganancia.
        pendiente = datos.evaluar_registro_fiel(
            reg, pd.DataFrame(columns=["game_id", "home_score", "away_score"]))
        self.assertEqual(pendiente["estado"].iloc[0], "Pendiente")
        self.assertTrue(np.isnan(float(pendiente["ganancia"].iloc[0])))

    def test_evaluar_registro_tres_mercados_push_y_sin_cuota(self):
        filas = pd.DataFrame([
            self._fila_registro(lado="visitante", linea_num=3.5, seleccion="BBB +3.5"),
            self._fila_registro(mercado="Total", lado="under", linea_num=44.0,
                                seleccion="Menos de 44.0"),
            self._fila_registro(mercado="Moneyline", lado="visitante",
                                linea_num=float("nan"), seleccion="BBB gana"),
            self._fila_registro(game_id="2026_06_CCC_DDD", linea_num=-3.0,
                                seleccion="CCC -3.0"),
            self._fila_registro(game_id="2026_06_EEE_FFF", cuota=float("nan"),
                                linea_num=-3.5, seleccion="EEE -3.5"),
        ])
        calendario = pd.DataFrame([
            {"game_id": "2026_06_AAA_BBB", "home_score": 23.0, "away_score": 20.0},
            {"game_id": "2026_06_CCC_DDD", "home_score": 23.0, "away_score": 20.0},
            {"game_id": "2026_06_EEE_FFF", "home_score": 23.0, "away_score": 20.0},
        ])
        res = datos.evaluar_registro_fiel(datos.registro_desde_picks(filas), calendario)
        self.assertEqual(list(res["estado"]),
                         ["Pegó", "Pegó", "No pegó", "Push", "No pegó"])
        self.assertAlmostEqual(float(res["ganancia"].iloc[0]), 100.0 / 110.0, places=6)
        self.assertAlmostEqual(float(res["ganancia"].iloc[3]), 0.0)  # push: $0
        self.assertTrue(np.isnan(float(res["ganancia"].iloc[4])))    # sin cuota

    def test_guardar_y_cargar_ida_y_vuelta(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "sub" / "registro.csv"
            reg = datos.registro_desde_picks(
                pd.DataFrame([
                    self._fila_registro(),
                    self._fila_registro(mercado="Total", lado="over", linea_num=44.0,
                                        seleccion="Más de 44.0", edge_num=-2.1),
                ]),
                momento="2026-10-16T10:00:00")
            datos.guardar_registro_picks(reg, ruta=ruta)
            leido = datos.cargar_registro_picks(ruta=ruta)
            self.assertEqual(len(leido), 2)
            self.assertEqual(list(leido["id"]), list(reg["id"]))
            self.assertAlmostEqual(float(leido["linea"].iloc[0]), -3.5)
            self.assertEqual(leido["game_id"].iloc[0], "2026_06_AAA_BBB")
            # Escribir lo leído y volver a leerlo no cambia nada (estable).
            datos.guardar_registro_picks(leido, ruta=ruta)
            pd.testing.assert_frame_equal(leido, datos.cargar_registro_picks(ruta=ruta))


if __name__ == "__main__":
    unittest.main()
