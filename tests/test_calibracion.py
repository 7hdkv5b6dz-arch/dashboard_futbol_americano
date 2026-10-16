"""
Pruebas de la calibración de probabilidades (`calibracion.py`) — sin internet.

Cubren: la aritmética de `calibrar` (contra una fórmula independiente y
anclajes congelados), monotonía, propagación de vacíos, el contrato de
moneyline (exige la probabilidad de mercado), el modo calibrado de
`datos.evaluar_picks_ml`, la versión compuesta del registro
(`srs-v2+cal-f4-1`), la banda del calibrado (`intervalo_prob`, delta method) y
—las pruebas fuertes— que los coeficientes y las covarianzas congeladas se
reproducen re-ajustando el universo estricto 2006–2025 del CSV real (offline
y determinista).

Cómo correrlas (desde la carpeta del proyecto):
    .venv/bin/python -B -m unittest discover -s tests -t .
"""

import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import calibracion
import datos


def _sigmoide_independiente(z):
    return 1.0 / (1.0 + math.exp(-z))


def _logit_independiente(p):
    p = min(max(float(p), 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _fila_partido(**cambios) -> dict:
    """Un partido crudo con valores razonables (mismo patrón que test_datos)."""
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


class TestCalibrar(unittest.TestCase):
    """La aritmética de `calibrar`, contra una fórmula independiente."""

    def test_spread_formula_independiente(self):
        coef = calibracion.COEFICIENTES["spread"]
        for p in (0.35, 0.5, 0.6, 0.7, 0.85):
            esperado = _sigmoide_independiente(
                coef["a"] + coef["b"] * _logit_independiente(p))
            obtenido = float(calibracion.calibrar("spread", p).iloc[0])
            self.assertAlmostEqual(obtenido, esperado, places=12, msg=f"p={p}")

    def test_total_formula_independiente(self):
        coef = calibracion.COEFICIENTES["total"]
        for p in (0.35, 0.5, 0.55, 0.65, 0.8):
            esperado = _sigmoide_independiente(
                coef["a"] + coef["b"] * _logit_independiente(p))
            obtenido = float(calibracion.calibrar("total", p).iloc[0])
            self.assertAlmostEqual(obtenido, esperado, places=12, msg=f"p={p}")

    def test_moneyline_formula_independiente(self):
        coef = calibracion.COEFICIENTES["moneyline"]
        for p, pk in ((0.6, 0.5), (0.65, 0.45), (0.4, 0.55)):
            esperado = _sigmoide_independiente(
                coef["a"] + coef["b1"] * _logit_independiente(p)
                + coef["b2"] * _logit_independiente(pk))
            obtenido = float(calibracion.calibrar("moneyline", p, pk).iloc[0])
            self.assertAlmostEqual(obtenido, esperado, places=12,
                                   msg=f"p={p} p_mer={pk}")

    def test_anclajes_congelados(self):
        """Anclajes de `cal-f4-1` (valores congelados del ajuste 2006–2025).

        Si algún día se re-ajustan los coeficientes con el procedimiento de la
        cabecera de `calibracion.py`, actualizar también estos números y
        `VERSION_CALIBRACION`: el cambio debe ser deliberado y documentado.
        """
        casos = [
            ("spread", 0.5, None, 0.4889558170210683),
            ("spread", 0.7, None, 0.5025641381372197),
            ("total", 0.55, None, 0.500511393874816),
            ("total", 0.65, None, 0.5069638941768515),
            ("moneyline", 0.6, 0.5, 0.48863814670999556),
            ("moneyline", 0.65, 0.45, 0.4375584125099322),
        ]
        for mercado, p, pk, esperado in casos:
            obtenido = float(calibracion.calibrar(mercado, p, pk).iloc[0])
            self.assertAlmostEqual(obtenido, esperado, places=12,
                                   msg=f"{mercado} p={p} p_mer={pk}")

    def test_monotonia(self):
        ps = pd.Series(np.linspace(0.05, 0.95, 19))
        for mercado in ("spread", "total"):
            vals = calibracion.calibrar(mercado, ps).to_numpy()
            self.assertTrue(np.all(np.diff(vals) > 0), mercado)
        # moneyline con mercado fijo: crece con la probabilidad del modelo
        vals = calibracion.calibrar(
            "moneyline", ps, pd.Series(np.full(19, 0.5))).to_numpy()
        self.assertTrue(np.all(np.diff(vals) > 0))

    def test_vacios_se_propagan(self):
        r = calibracion.calibrar("spread",
                                 pd.Series([np.nan, 0.5, None], dtype=float))
        self.assertTrue(np.isnan(r.iloc[0]))
        self.assertTrue(np.isfinite(r.iloc[1]))
        self.assertTrue(np.isnan(r.iloc[2]))
        r_ml = calibracion.calibrar("moneyline", pd.Series([0.6, 0.6]),
                                    pd.Series([0.5, np.nan]))
        self.assertTrue(np.isfinite(r_ml.iloc[0]))
        self.assertTrue(np.isnan(r_ml.iloc[1]))

    def test_extremos_recortados(self):
        # 0 y 1 exactos no explotan: se recortan antes del logit
        r = calibracion.calibrar("spread", pd.Series([0.0, 1.0]))
        self.assertTrue(np.isfinite(r.to_numpy()).all())
        self.assertTrue(bool(((r > 0) & (r < 1)).all()))

    def test_moneyline_sin_mercado_error(self):
        with self.assertRaises(ValueError):
            calibracion.calibrar("moneyline", 0.6)

    def test_mercado_desconocido_error(self):
        with self.assertRaises(ValueError):
            calibracion.calibrar("nba", 0.6)

    def test_series_conserva_indice(self):
        s = pd.Series([0.5, 0.6], index=[10, 20])
        r = calibracion.calibrar("total", s)
        self.assertEqual(list(r.index), [10, 20])


class TestPicksMlCalibrado(unittest.TestCase):
    """El modo calibrado de `datos.evaluar_picks_ml` (jornada pendiente)."""

    def _juego(self, margen_modelo=12.0, sigma_modelo=13.0):
        d = datos._preparar(pd.DataFrame([_fila_partido()]))
        d["margen_modelo"] = margen_modelo
        d["sigma_modelo"] = sigma_modelo
        return d

    def test_bruto_emite_pick_y_calibrado_lo_suprime(self):
        d = self._juego()
        bruto = datos.evaluar_picks_ml(d, umbral=0.04)
        self.assertEqual(len(bruto), 1)
        self.assertGreater(float(bruto["edge"].iloc[0]), 0.2)
        # La mezcla de moneyline sigue al mercado: el edge calibrado ≈ 0 y el
        # pick bruto de 4+ puntos ya no pasa el umbral. Es el resultado medido.
        cal = datos.evaluar_picks_ml(d, umbral=0.04, calibrado=True)
        self.assertTrue(cal.empty)

    def test_calibrado_columnas_y_lado(self):
        d = self._juego()
        cal = datos.evaluar_picks_ml(d, umbral=0.0, calibrado=True)
        self.assertEqual(len(cal), 1)
        p_bruta_local = 0.5 * (1.0 + math.erf((12.0 / 13.0) / math.sqrt(2.0)))
        p_mer = float(d["prob_local_sin_vig"].iloc[0])
        esperado_local = float(calibracion.calibrar(
            "moneyline", p_bruta_local, pd.Series([p_mer])).iloc[0])
        self.assertAlmostEqual(
            float(cal["prob_local_calibrada"].iloc[0]), esperado_local,
            places=12)
        lado_local = esperado_local > p_mer
        self.assertEqual(bool(cal["al_local"].iloc[0]), lado_local)
        esperado_prob = esperado_local if lado_local else 1.0 - esperado_local
        self.assertAlmostEqual(
            float(cal["prob_modelo"].iloc[0]), esperado_prob, places=12)
        self.assertAlmostEqual(
            float(cal["edge"].iloc[0]), esperado_local - p_mer, places=12)


class TestVersionRegistro(unittest.TestCase):
    """La versión compuesta que la app sella en el registro fiel."""

    def test_version_compuesta_srs_v2_cal_f4_1(self):
        picks = pd.DataFrame({
            "temporada": [2026], "semana": [7],
            "game_id": ["2026_07_AAA_BBB"],
            "equipo_local": ["AAA"], "equipo_visitante": ["BBB"],
            "mercado": ["Spread"], "lado": ["local"],
            "seleccion": ["AAA -2.5"], "linea_num": [-2.5],
            "cuota": [-110.0], "prob_modelo": [0.4988],
            "prob_mercado": [0.51], "edge_num": [2.3],
        })
        version = f"{datos.VERSION_MODELO}+{calibracion.VERSION_CALIBRACION}"
        reg = datos.registro_desde_picks(
            picks, momento="2026-10-16T00:00:00", version=version)
        self.assertEqual(reg["version_modelo"].iloc[0], "srs-v2+cal-f4-1")
        self.assertEqual(reg["prob_modelo"].iloc[0], 0.4988)


class TestCoeficientesCongelados(unittest.TestCase):
    """Prueba fuerte: re-ajustar el universo estricto 2006–2025 del CSV real
    debe reproducir los coeficientes congelados (offline y determinista).

    Mismos filtros que el laboratorio (`lab/calibracion.py`): era 2006+,
    pronóstico del modelo Y probabilidad de mercado Y resultado decidido;
    push y empates fuera. El ajuste usa las temporadas < 2026 (la ventana
    congelada en `calibracion.py`).
    """

    @classmethod
    def setUpClass(cls):
        ruta = Path(datos.BASE) / "nfl_games.csv"
        if not ruta.exists():
            raise unittest.SkipTest(
                "falta data/nfl_games.csv (las pruebas no descargan nada)")
        cal = datos._preparar(pd.read_csv(ruta, low_memory=False))
        hist = datos.pronosticos_historicos(cal).reset_index(drop=True)
        era = hist[hist["season"] >= 2006].reset_index(drop=True)
        era["p_local_modelo"] = datos.probabilidad_supera(
            era["margen_modelo"], era["spread_line"], era["sigma_modelo"])
        era["p_over_modelo"] = datos.probabilidad_supera(
            era["total_modelo"], era["total_line"], era["sigma_total_modelo"])
        po = datos._prob_implicita(era["over_odds"])
        pu = datos._prob_implicita(era["under_odds"])
        p_ml_mod = datos.probabilidades_ml(
            era["margen_modelo"], era["sigma_modelo"])[0]

        def flot(serie):
            return pd.Series(serie).astype("Float64").astype(float)

        cls.universos = {
            "spread": pd.DataFrame({
                "season": era["season"], "p_mod": era["p_local_modelo"],
                "p_mer": era["prob_local_spread_sin_vig"],
                "y": flot(era["cubre_local"].mask(
                    era["push_spread"].fillna(False))),
            }).dropna().reset_index(drop=True),
            "total": pd.DataFrame({
                "season": era["season"], "p_mod": era["p_over_modelo"],
                "p_mer": po / (po + pu), "y": flot(era["over"]),
            }).dropna().reset_index(drop=True),
            "moneyline": pd.DataFrame({
                "season": era["season"], "p_mod": p_ml_mod,
                "p_mer": era["prob_local_sin_vig"],
                "y": flot(era["gano_local"].mask(
                    era["empate"].fillna(False))),
            }).dropna().reset_index(drop=True),
        }

    def _ventana(self, mercado):
        frame = self.universos[mercado]
        return frame[frame["season"] < 2026]

    def test_universos_no_vacios(self):
        for mercado, frame in self.universos.items():
            self.assertGreater(len(frame), 5000, mercado)
            self.assertEqual(
                int(self._ventana(mercado)["season"].max()), 2025, mercado)

    def test_platt_reproduce_los_congelados(self):
        for mercado in ("spread", "total"):
            tr = self._ventana(mercado)
            a, b = calibracion.ajustar_platt(tr["p_mod"], tr["y"])
            self.assertAlmostEqual(
                a, calibracion.COEFICIENTES[mercado]["a"], places=9,
                msg=mercado)
            self.assertAlmostEqual(
                b, calibracion.COEFICIENTES[mercado]["b"], places=9,
                msg=mercado)

    def test_mezcla_reproduce_los_congelados(self):
        tr = self._ventana("moneyline")
        a, b1, b2 = calibracion.ajustar_mezcla(tr["p_mod"], tr["p_mer"], tr["y"])
        coef = calibracion.COEFICIENTES["moneyline"]
        self.assertAlmostEqual(a, coef["a"], places=9)
        self.assertAlmostEqual(b1, coef["b1"], places=9)
        self.assertAlmostEqual(b2, coef["b2"], places=9)

    def test_covarianzas_reproducen_las_congeladas(self):
        """La covarianza (H⁻¹) del mismo ajuste también se congela y se
        verifica: de ella sale la banda del calibrado (delta method)."""
        for mercado in ("spread", "total"):
            tr = self._ventana(mercado)
            _, _, cov = calibracion.ajustar_platt_cov(tr["p_mod"], tr["y"])
            np.testing.assert_allclose(
                cov, np.asarray(calibracion.COVARIANZAS[mercado], dtype=float),
                rtol=1e-9, atol=0.0, err_msg=mercado)

    def test_covarianza_mezcla_reproduce_la_congelada(self):
        tr = self._ventana("moneyline")
        _, _, _, cov = calibracion.ajustar_mezcla_cov(
            tr["p_mod"], tr["p_mer"], tr["y"])
        np.testing.assert_allclose(
            cov, np.asarray(calibracion.COVARIANZAS["moneyline"], dtype=float),
            rtol=1e-9, atol=0.0)


class TestIntervaloProb(unittest.TestCase):
    """La banda del calibrado por error de estimación (delta method)."""

    def test_contiene_el_punto_y_no_es_degenerada(self):
        for mercado, pm in (("spread", None), ("total", None),
                            ("moneyline", 0.5)):
            for p in (0.35, 0.5, 0.65, 0.8):
                lo, hi = calibracion.intervalo_prob(
                    mercado, pd.Series([p]),
                    None if pm is None else pd.Series([pm]))
                punto = float(calibracion.calibrar(mercado, p, pm).iloc[0])
                ancho = float(hi.iloc[0]) - float(lo.iloc[0])
                self.assertLess(float(lo.iloc[0]), punto,
                                msg=f"{mercado} p={p}")
                self.assertGreater(float(hi.iloc[0]), punto,
                                   msg=f"{mercado} p={p}")
                self.assertGreater(ancho, 0.0)
                self.assertLess(ancho, 0.15)

    def test_banda_mas_ancha_en_los_extremos(self):
        lo_c, hi_c = calibracion.intervalo_prob("spread", pd.Series([0.5]))
        lo_x, hi_x = calibracion.intervalo_prob("spread", pd.Series([0.8]))
        ancho_c = float(hi_c.iloc[0]) - float(lo_c.iloc[0])
        ancho_x = float(hi_x.iloc[0]) - float(lo_x.iloc[0])
        self.assertGreater(ancho_x, ancho_c)

    def test_vacios_se_propagan_y_contrato(self):
        lo, hi = calibracion.intervalo_prob(
            "spread", pd.Series([np.nan, 0.5]))
        self.assertTrue(np.isnan(float(lo.iloc[0])))
        self.assertTrue(np.isnan(float(hi.iloc[0])))
        self.assertTrue(np.isfinite(float(lo.iloc[1])))
        lo_ml, hi_ml = calibracion.intervalo_prob(
            "moneyline", pd.Series([0.6]), pd.Series([np.nan]))
        self.assertTrue(np.isnan(float(lo_ml.iloc[0])))
        with self.assertRaises(ValueError):
            calibracion.intervalo_prob("moneyline", 0.6)
        with self.assertRaises(ValueError):
            calibracion.intervalo_prob("nba", 0.6)

    def test_extremos_recortados(self):
        lo, hi = calibracion.intervalo_prob(
            "total", pd.Series([0.0, 1.0]))
        self.assertTrue(np.isfinite(lo.to_numpy()).all())
        self.assertTrue(np.isfinite(hi.to_numpy()).all())
