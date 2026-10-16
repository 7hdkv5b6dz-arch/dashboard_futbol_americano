"""
Pruebas básicas de `datos.py` (sin internet, sin Streamlit).

Cómo correrlas (desde la carpeta del proyecto):
    .venv/bin/python -m unittest discover -s tests -t .

Cubren: cuotas y vig, convención del spread, push, totales, primetime
(incluidas las correcciones de 1999–2005), el resumen por temporada, el
respaldo sin conexión y el modelo de pronósticos (que NO use información
del futuro: walk-forward).
"""

import itertools
import unittest

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


if __name__ == "__main__":
    unittest.main()
