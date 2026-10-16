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
import unittest
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


if __name__ == "__main__":
    unittest.main()
