"""
Pruebas del motor de EV con push explícito (`motor_ev.py`) — sin internet.

Cubren (criterios de `lab/pre_registro_motor_ev.md`): las conversiones de
momios (pago neto, probabilidad implícita y de equilibrio) contra casos
calculados a mano; la regresión contra `datos._pago_por_dolar` y
`datos._prob_implicita`; la probabilidad de push (0 exacto en líneas x.5,
normal discretizada en enteras y empates, vacíos propagados sin inventar);
el EV con y sin push (equilibrio exacto, monotonía, coherencia de la
descomposición); los estados (ninguno dice «validada»); la banda del
calibrado (delta method) y el decorador de marcos de picks con las funciones
reales de la app.

Cómo correrlas (desde la carpeta del proyecto):
    .venv/bin/python -B -m unittest discover -s tests -t .
"""

import math
import unittest

import numpy as np
import pandas as pd

import calibracion
import datos
import motor_ev


def _phi_independiente(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class TestConversionesDeMomios(unittest.TestCase):
    """Pago neto, probabilidad implícita y probabilidad de equilibrio."""

    def test_pago_neto_casos_conocidos(self):
        casos = [(-110, 10 / 11), (-150, 2 / 3), (-200, 0.5),
                 (100, 1.0), (130, 1.3), (250, 2.5), (-250, 0.4)]
        for cuota, esperado in casos:
            self.assertAlmostEqual(
                float(motor_ev.pago_neto(cuota).iloc[0]), esperado, places=12,
                msg=f"cuota {cuota}")

    def test_prob_equilibrio_casos_conocidos(self):
        casos = [(-110, 110 / 210), (130, 100 / 230), (100, 0.5),
                 (-200, 2 / 3), (250, 100 / 350)]
        for cuota, esperado in casos:
            self.assertAlmostEqual(
                float(motor_ev.prob_equilibrio(cuota).iloc[0]), esperado,
                places=12, msg=f"cuota {cuota}")

    def test_prob_implicita_y_equilibrio_coinciden(self):
        rejilla = pd.Series([-350, -250, -150, -110, -105, 100, 105, 130, 200])
        np.testing.assert_allclose(
            motor_ev.prob_implicita(rejilla).to_numpy(),
            motor_ev.prob_equilibrio(rejilla).to_numpy(), rtol=0, atol=1e-15)

    def test_vacios_no_se_inventan(self):
        r = motor_ev.pago_neto(pd.Series([np.nan, None, 0.0]))
        self.assertTrue(r.isna().all())
        r = motor_ev.prob_equilibrio(pd.Series([np.nan, 0.0]))
        self.assertTrue(r.isna().all())

    def test_regresion_contra_datos(self):
        rejilla = pd.Series([-250, -150, -110, -105, 100, 105, 130, 200, 350])
        np.testing.assert_allclose(
            motor_ev.pago_neto(rejilla).to_numpy(),
            datos._pago_por_dolar(rejilla).to_numpy(), rtol=0, atol=1e-12)
        np.testing.assert_allclose(
            motor_ev.prob_implicita(rejilla).to_numpy(),
            datos._prob_implicita(rejilla).to_numpy(), rtol=0, atol=1e-12)

    def test_diferencia_deliberada_con_el_roi_historico(self):
        """`datos._pago_por_dolar` rellena vacíos con −110 (ROI histórico);
        el motor NO rellena: sin cuota no hay EV (no se inventa nada)."""
        vacio = pd.Series([np.nan])
        self.assertTrue(np.isnan(float(motor_ev.pago_neto(vacio).iloc[0])))
        self.assertAlmostEqual(float(datos._pago_por_dolar(vacio).iloc[0]),
                               100 / 110, places=12)


class TestPush(unittest.TestCase):
    """La probabilidad de push: 0 exacto en x.5, modelo en enteras/empates."""

    def test_linea_media_es_cero_exacto(self):
        for linea in (-3.5, 2.5, 0.5, -0.5, 44.5, -10.5):
            self.assertEqual(float(motor_ev.prob_push(0.0, linea, 13.0).iloc[0]),
                             0.0, msg=f"línea {linea}")

    def test_linea_media_sin_modelo_sigue_siendo_cero(self):
        """El 0 de las líneas x.5 es aritmético: no necesita μ/σ."""
        self.assertEqual(
            float(motor_ev.prob_push(np.nan, 2.5, np.nan).iloc[0]), 0.0)

    def test_linea_entera_formula_independiente(self):
        v, l, s = 2.0, -3.0, 13.0
        esperado = (_phi_independiente((l + 0.5 - v) / s)
                    - _phi_independiente((l - 0.5 - v) / s))
        self.assertAlmostEqual(
            float(motor_ev.prob_push(v, l, s).iloc[0]), esperado, places=12)

    def test_empate_moneyline(self):
        """Moneyline: push = empate (línea 0)."""
        esperado = 2.0 * _phi_independiente(0.5 / 13.0) - 1.0
        self.assertAlmostEqual(
            float(motor_ev.prob_push(0.0, 0.0, 13.0).iloc[0]), esperado,
            places=12)

    def test_vacios(self):
        self.assertTrue(np.isnan(float(
            motor_ev.prob_push(np.nan, 3.0, 13.0).iloc[0])))
        self.assertTrue(np.isnan(float(
            motor_ev.prob_push(0.0, 3.0, np.nan).iloc[0])))
        self.assertTrue(np.isnan(float(
            motor_ev.prob_push(0.0, np.nan, 13.0).iloc[0])))

    def test_rango(self):
        v = pd.Series([-14.0, -7.0, 0.0, 7.0, 14.0])
        for linea in (-7.0, -3.0, 0.0, 3.0, 7.0):
            p = motor_ev.prob_push(v, linea, 13.0)
            self.assertTrue(bool(((p >= 0.0) & (p <= 1.0)).all()))


class TestEv(unittest.TestCase):
    """El EV por $1 con push explícito."""

    def test_casos_conocidos(self):
        self.assertAlmostEqual(float(motor_ev.ev(0.5, -110).iloc[0]),
                               -1 / 22, places=12)
        self.assertAlmostEqual(float(motor_ev.ev(0.6, -110).iloc[0]),
                               0.6 * (10 / 11) - 0.4, places=12)
        self.assertAlmostEqual(float(motor_ev.ev(0.4, 130).iloc[0]),
                               0.4 * 1.3 - 0.6, places=12)

    def test_el_push_escala_el_ev(self):
        for p, cuota, push in ((0.6, -110, 0.03), (0.45, 150, 0.02),
                               (0.5, -105, 0.08)):
            sin_push = float(motor_ev.ev(p, cuota).iloc[0])
            con_push = float(motor_ev.ev(p, cuota, push).iloc[0])
            self.assertAlmostEqual(con_push, (1.0 - push) * sin_push,
                                   places=12)

    def test_ev_cero_exacto_en_la_probabilidad_de_equilibrio(self):
        for cuota in (-250, -110, 105, 130, 250):
            p_eq = float(motor_ev.prob_equilibrio(cuota).iloc[0])
            for push in (0.0, 0.03, 0.1):
                self.assertAlmostEqual(
                    float(motor_ev.ev(p_eq, cuota, push).iloc[0]), 0.0,
                    places=12, msg=f"cuota {cuota} push {push}")

    def test_monotono_en_la_probabilidad(self):
        ps = pd.Series(np.linspace(0.1, 0.9, 17))
        vals = motor_ev.ev(ps, -110, 0.03).to_numpy()
        self.assertTrue(np.all(np.diff(vals) > 0))

    def test_vacios(self):
        self.assertTrue(np.isnan(float(
            motor_ev.ev(0.5, np.nan).iloc[0])))
        self.assertTrue(np.isnan(float(
            motor_ev.ev(np.nan, -110).iloc[0])))
        self.assertTrue(np.isnan(float(
            motor_ev.ev(0.5, -110, np.nan).iloc[0])))

    def test_descomposicion_coherente(self):
        pc = pd.Series([0.35, 0.5, 0.62, 0.8])
        pp = pd.Series([0.0, 0.02, 0.03, 0.05])
        p_ganar, p_perder, p_push = motor_ev.descomponer(pc, pp)
        np.testing.assert_allclose(
            (p_ganar + p_perder + p_push).to_numpy(), 1.0, rtol=0, atol=1e-12)
        np.testing.assert_allclose(
            p_ganar.to_numpy(), ((1 - pp) * pc).to_numpy(), rtol=0, atol=1e-15)
        np.testing.assert_allclose(
            p_perder.to_numpy(), ((1 - pp) * (1 - pc)).to_numpy(),
            rtol=0, atol=1e-15)


class TestEstados(unittest.TestCase):
    """Las etiquetas: honestas y sin «validada»."""

    def test_estados(self):
        ev = pd.Series([np.nan, -0.02, 0.0, 0.01, 0.01, 0.01])
        lo = pd.Series([np.nan, -0.03, -0.01, np.nan, -0.001, 0.001])
        r = list(motor_ev.estado_ev(ev, lo))
        self.assertEqual(r[0], motor_ev.SIN_DATOS)
        self.assertEqual(r[1], motor_ev.SIN_EV)
        self.assertEqual(r[2], motor_ev.SIN_EV)
        self.assertEqual(r[3], motor_ev.EV_EN_EL_RUIDO)   # sin banda: conservador
        self.assertEqual(r[4], motor_ev.EV_EN_EL_RUIDO)
        self.assertEqual(r[5], motor_ev.EV_SIN_VALIDAR)

    def test_sin_banda_es_conservador(self):
        r = motor_ev.estado_ev(pd.Series([0.05]))
        self.assertEqual(r.iloc[0], motor_ev.EV_EN_EL_RUIDO)

    def test_ninguna_etiqueta_dice_validada(self):
        etiquetas = [motor_ev.SIN_DATOS, motor_ev.SIN_EV,
                     motor_ev.EV_EN_EL_RUIDO, motor_ev.EV_SIN_VALIDAR,
                     motor_ev.ESTADO_ESTRATEGIA]
        for etiqueta in etiquetas:
            self.assertNotIn("validada", etiqueta.lower())

    def test_nota_push_documenta_el_sesgo_medido(self):
        """La limitación del push (medida contra 2006-2025) es parte del
        contrato del motor: menciona los tres mercados y el empate."""
        for palabra in ("spread", "total", "moneyline", "empate"):
            self.assertIn(palabra, motor_ev.NOTA_PUSH)


class TestEvaluarApuesta(unittest.TestCase):
    """El paquete completo (probabilidades, EV, banda y estado)."""

    def test_columnas_y_coherencia(self):
        cuadro = motor_ev.evaluar_apuesta(
            pd.Series([0.55, 0.5]), pd.Series([-110.0, 120.0]),
            pd.Series([0.02, 0.0]), pd.Series([0.53, 0.48]),
            pd.Series([0.57, 0.52]))
        self.assertEqual(list(cuadro.columns),
                         ["prob_equilibrio", "p_ganar", "p_perder", "p_push",
                          "ev", "ev_lo", "ev_hi", "estado"])
        np.testing.assert_allclose(
            (cuadro["p_ganar"] + cuadro["p_perder"] + cuadro["p_push"]).to_numpy(),
            1.0, rtol=0, atol=1e-12)
        self.assertLessEqual(float(cuadro["ev_lo"].iloc[0]),
                             float(cuadro["ev"].iloc[0]))
        self.assertLessEqual(float(cuadro["ev"].iloc[0]),
                             float(cuadro["ev_hi"].iloc[0]))

    def test_sin_banda_ev_lo_vacio(self):
        cuadro = motor_ev.evaluar_apuesta(0.6, -110, 0.0)
        self.assertTrue(np.isnan(float(cuadro["ev_lo"].iloc[0])))
        self.assertEqual(cuadro["estado"].iloc[0], motor_ev.EV_EN_EL_RUIDO)


class TestDecorar(unittest.TestCase):
    """El decorador de marcos de picks (mismas columnas que la app)."""

    @staticmethod
    def _marco_spread(al_local=True, margen=3.2, linea=-2.5, sigma=13.0,
                      cuota=-110.0):
        p_cubre = calibracion.calibrar(
            "spread", datos.probabilidad_supera(
                pd.Series([margen]), pd.Series([linea]), pd.Series([sigma])))
        p_lado = p_cubre if al_local else (1.0 - p_cubre)
        return pd.DataFrame({
            "margen_modelo": [margen], "spread_line": [linea],
            "sigma_modelo": [sigma], "cuota": [cuota],
            "al_local": [al_local],
            "prob_modelo": p_lado.to_numpy(),
            "prob_local_spread_sin_vig": [0.5],
        })

    def test_spread_coherente(self):
        marco = self._marco_spread()
        r = motor_ev.decorar(marco, "spread")
        self.assertEqual(float(r["p_estimada"].iloc[0]),
                         float(marco["prob_modelo"].iloc[0]))
        p_push = float(motor_ev.prob_push(3.2, -2.5, 13.0).iloc[0])
        self.assertEqual(float(r["p_push"].iloc[0]), p_push)
        self.assertAlmostEqual(
            float(r["ev_estimado"].iloc[0]),
            float(motor_ev.ev(float(marco["prob_modelo"].iloc[0]), -110.0,
                              p_push).iloc[0]), places=12)
        self.assertAlmostEqual(
            float(r["p_equilibrio"].iloc[0]),
            float(motor_ev.prob_equilibrio(-110.0).iloc[0]), places=12)
        self.assertLessEqual(float(r["ev_lo"].iloc[0]),
                             float(r["ev_estimado"].iloc[0]))
        self.assertLessEqual(float(r["ev_estimado"].iloc[0]),
                             float(r["ev_hi"].iloc[0]))

    def test_lado_visitante_invierte_probabilidades(self):
        marco = self._marco_spread(al_local=False)
        r = motor_ev.decorar(marco, "spread")
        p_local = calibracion.calibrar(
            "spread", datos.probabilidad_supera(
                pd.Series([3.2]), pd.Series([-2.5]), pd.Series([13.0])))
        self.assertAlmostEqual(float(r["p_estimada"].iloc[0]),
                               1.0 - float(p_local.iloc[0]), places=12)
        self.assertLessEqual(float(r["ev_lo"].iloc[0]),
                             float(r["ev_estimado"].iloc[0]))
        self.assertLessEqual(float(r["ev_estimado"].iloc[0]),
                             float(r["ev_hi"].iloc[0]))

    def test_total(self):
        p_over = calibracion.calibrar(
            "total", datos.probabilidad_supera(
                pd.Series([47.5]), pd.Series([44.0]), pd.Series([12.0])))
        marco = pd.DataFrame({
            "total_modelo": [47.5], "total_line": [44.0],
            "sigma_total_modelo": [12.0], "cuota": [105.0], "al_over": [True],
            "prob_modelo": p_over.to_numpy(),
            "prob_local_sin_vig": [0.5],
        })
        r = motor_ev.decorar(marco, "total")
        # Línea entera (44.0): el push es posible y se estima con el modelo.
        self.assertGreater(float(r["p_push"].iloc[0]), 0.0)
        self.assertLessEqual(float(r["ev_lo"].iloc[0]),
                             float(r["ev_estimado"].iloc[0]))
        self.assertLessEqual(float(r["ev_estimado"].iloc[0]),
                             float(r["ev_hi"].iloc[0]))

    def test_moneyline(self):
        margen, sigma, pm = 12.0, 13.0, 0.55
        p_local = datos.probabilidades_ml(pd.Series([margen]),
                                          pd.Series([sigma]))[0]
        p_cal = calibracion.calibrar("moneyline", p_local, pd.Series([pm]))
        marco = pd.DataFrame({
            "margen_modelo": [margen], "sigma_modelo": [sigma],
            "cuota": [-150.0], "al_local": [True],
            "prob_modelo": p_cal.to_numpy(),
            "prob_local_sin_vig": [pm],
        })
        r = motor_ev.decorar(marco, "moneyline")
        p_push = float(motor_ev.prob_push(margen, 0.0, sigma).iloc[0])
        self.assertAlmostEqual(float(r["p_push"].iloc[0]), p_push, places=12)
        self.assertGreater(float(r["p_push"].iloc[0]), 0.0)  # empate posible

    def test_vacios_no_producen_ev_inventado(self):
        marco = self._marco_spread()
        marco["cuota"] = np.nan
        r = motor_ev.decorar(marco, "spread")
        self.assertTrue(np.isnan(float(r["ev_estimado"].iloc[0])))
        self.assertEqual(r["estado_ev"].iloc[0], motor_ev.SIN_DATOS)

    def test_faltan_columnas_error(self):
        marco = self._marco_spread().drop(columns=["sigma_modelo"])
        with self.assertRaises(ValueError):
            motor_ev.decorar(marco, "spread")

    def test_mercado_desconocido_error(self):
        with self.assertRaises(ValueError):
            motor_ev.decorar(self._marco_spread(), "nba")

    def test_no_muta_el_original(self):
        marco = self._marco_spread()
        antes = marco.copy()
        motor_ev.decorar(marco, "spread")
        pd.testing.assert_frame_equal(marco, antes)


class TestProbabilidadSuperaMotor(unittest.TestCase):
    """La probabilidad bruta del motor = la de `datos` (regresión 1e-12)."""

    def test_regresion(self):
        v = pd.Series([3.0, -3.5, 7.2, -0.4])
        l = pd.Series([-2.5, 4.5, 0.0, 2.5])
        s = pd.Series([13.0, 10.0, 12.0, 11.5])
        np.testing.assert_allclose(
            motor_ev.probabilidad_supera(v, l, s).to_numpy(),
            datos.probabilidad_supera(v, l, s).to_numpy(),
            rtol=0, atol=1e-12)


class CoherenciaDeLaTerna(unittest.TestCase):
    """F2: alarma interna de p_ganar/p_perder/p_push (suma 1 y rangos)."""

    @staticmethod
    def _fila(**cambios):
        base = {"p_ganar": 0.55, "p_perder": 0.43, "p_push": 0.02}
        base.update(cambios)
        return base

    def test_terna_coherente_pasa(self):
        df = pd.DataFrame([self._fila()])
        self.assertEqual(len(motor_ev.problemas_coherencia(df)), 0)

    def test_vacios_no_se_revisan(self):
        df = pd.DataFrame([{"p_ganar": np.nan, "p_perder": np.nan,
                            "p_push": np.nan}])
        self.assertEqual(len(motor_ev.problemas_coherencia(df)), 0)

    def test_suma_rota_se_detecta(self):
        df = pd.DataFrame([self._fila(p_perder=0.30)])
        problemas = motor_ev.problemas_coherencia(df)
        self.assertEqual(len(problemas), 1)
        self.assertIn("≠ 1", problemas["problema"].iloc[0])

    def test_fuera_de_rango_se_detecta(self):
        df = pd.DataFrame([self._fila(p_ganar=-0.1, p_perder=-0.1, p_push=1.2)])
        problemas = motor_ev.problemas_coherencia(df)
        self.assertEqual(len(problemas), 3)  # una por probabilidad
        for problema in problemas["problema"]:
            self.assertIn("fuera de [0,1]", problema)

    def test_p_estimada_incoherente_se_detecta(self):
        df = pd.DataFrame([self._fila(p_estimada=0.90)])
        problemas = motor_ev.problemas_coherencia(df)
        self.assertEqual(len(problemas), 1)
        self.assertIn("p_estimada", problemas["problema"].iloc[0])

    def test_lo_que_produce_el_motor_es_coherente(self):
        marco = pd.DataFrame({
            "margen_modelo": [3.2, -1.5], "spread_line": [-2.5, 1.0],
            "sigma_modelo": [13.0, 13.0], "cuota": [-110.0, -105.0],
            "al_local": [True, False],
            "prob_modelo": [0.57, 0.48],
        })
        r = motor_ev.decorar(marco, "spread")
        self.assertEqual(len(motor_ev.problemas_coherencia(r)), 0)


if __name__ == "__main__":
    unittest.main()
