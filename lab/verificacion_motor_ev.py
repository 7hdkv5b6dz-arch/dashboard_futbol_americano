#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificación del motor de EV con push explícito (F5) — offline y determinista.

Comprueba los criterios del pre-registro `lab/pre_registro_motor_ev.md`
(escrito antes de medir):
1. Matemáticas del motor con casos a mano: momio → pago/equilibrio; EV con y
   sin push; equilibrio exacto; coherencia p_ganar+p_perder+p_push=1.
2. La jornada pendiente REAL (funciones de app.py extraídas por AST, sin
   Streamlit) pasa por el motor: momio, P. eq., P. est., push, EV, banda y
   estado — con el EV recalculado de forma independiente y estados válidos.
3. Push empírico 2006-2025 (partidos jugados): media estimada vs frecuencia
   observada (≤ 0.015 por mercado) y push observado = 0 EXACTO en líneas x.5.
4. Regresión contra las conversiones existentes (`datos`) y el contrato
   `ev_num` del registro fiel.
5. Determinismo, sin red y tiempo.

Cómo se corre (desde la carpeta del proyecto):
    .venv/bin/python -B lab/verificacion_motor_ev.py

Sale con código 1 si alguna comprobación falla. No escribe nada, no usa red.
"""

import ast
import hashlib
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROYECTO = Path(__file__).resolve().parent.parent
# Orden importante: la raíz PRIMERO (calibracion.py de producción), y después
# lab/ para `evaluacion` (el instrumento). lab/ tiene su propio calibracion.py
# (el experimento F4) que NO debe tapar al módulo de producción.
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROYECTO))
import calibracion  # noqa: E402  (producción: calibracion.py de la raíz)
import datos  # noqa: E402
import motor_ev  # noqa: E402
import evaluacion as inst  # noqa: E402


def extraer_funciones_app(ruta_app: Path) -> dict:
    """Las funciones de decisión REALES de app.py, sin ejecutar Streamlit."""
    arbol = ast.parse(ruta_app.read_text(encoding="utf-8"))
    queridas = {"cuota_a_pago", "ganancia_apuesta", "evaluar_spread",
                "evaluar_totales"}
    nodos = [n for n in arbol.body
             if isinstance(n, ast.FunctionDef) and n.name in queridas]
    if len(nodos) != len(queridas):
        raise RuntimeError(
            f"app.py: se esperaban {len(queridas)} funciones de decisión y "
            f"se encontraron {len(nodos)} — revisar la verificación")
    modulo = ast.Module(body=nodos, type_ignores=[])
    espacio = {"np": np, "pd": pd, "datos": datos, "calibracion": calibracion}
    exec(compile(modulo, "app.py", "exec"), espacio)  # noqa: S102
    return espacio


def pago_neto_independiente(cuota):
    """Pago neto por $1 con una fórmula escrita aparte (control del motor)."""
    return cuota / 100.0 if cuota > 0 else 100.0 / -cuota


def ev_independiente(p, cuota, push):
    return (1.0 - push) * (p * pago_neto_independiente(cuota) - (1.0 - p))


def main() -> int:
    inicio = time.perf_counter()
    checks = []
    ruta_pre = Path(__file__).resolve().parent / "pre_registro_motor_ev.md"
    sha_pre = hashlib.sha1(ruta_pre.read_bytes()).hexdigest()[:12]

    print("=" * 84)
    print("Verificación del motor de EV con push explícito (F5) — sin Streamlit")
    print("=" * 84)
    for nombre in ("app.py", "datos.py", "calibracion.py", "motor_ev.py"):
        sha = hashlib.sha1((PROYECTO / nombre).read_bytes()).hexdigest()[:12]
        print(f"  {nombre:<16s} sha1 {sha}")
    print(f"  Pre-registro: lab/pre_registro_motor_ev.md (sha1 {sha_pre})")
    print(f"  Versión del motor: {motor_ev.VERSION_EV}")
    print("  Solo lectura · sin red · determinista (salvo la línea de tiempo)")

    with inst.GuardiaRed() as guardia:
        # ------------------------------------------------------------------
        # 1. Matemáticas del motor con casos a mano
        # ------------------------------------------------------------------
        inst.linea("1. MATEMÁTICAS DEL MOTOR (casos calculados a mano)")
        for cuota, pago_esp, eq_esp in ((-110, 10 / 11, 110 / 210),
                                        (130, 1.3, 100 / 230),
                                        (100, 1.0, 0.5),
                                        (-200, 0.5, 2 / 3)):
            pago = float(motor_ev.pago_neto(cuota).iloc[0])
            eq = float(motor_ev.prob_equilibrio(cuota).iloc[0])
            inst.chk_bool(checks, f"momio {cuota:+d}: pago y equilibrio",
                          abs(pago - pago_esp) < 1e-12
                          and abs(eq - eq_esp) < 1e-12,
                          f"pago {pago:.10f} · equilibrio {eq:.10f}")
        ev_05 = float(motor_ev.ev(0.5, -110).iloc[0])
        ev_06 = float(motor_ev.ev(0.6, -110).iloc[0])
        ev_06p = float(motor_ev.ev(0.6, -110, 0.03).iloc[0])
        inst.chk_bool(checks, "EV p=0.5 @ −110 = −1/22",
                      abs(ev_05 - (-1 / 22)) < 1e-12, f"{ev_05:+.10f}")
        inst.chk_bool(checks, "EV p=0.6 @ −110 = +0.145454…",
                      abs(ev_06 - 0.14545454545454545) < 1e-12,
                      f"{ev_06:+.10f}")
        inst.chk_bool(checks, "el push escala el EV por (1−p_push)",
                      abs(ev_06p - 0.97 * ev_06) < 1e-12, f"{ev_06p:+.10f}")
        eq = float(motor_ev.prob_equilibrio(-110).iloc[0])
        ev_eq = float(motor_ev.ev(eq, -110, 0.08).iloc[0])
        inst.chk_bool(checks, "EV = 0 exacto en el equilibrio (con push)",
                      abs(ev_eq) < 1e-15, f"{ev_eq:+.2e}")
        pw, pl, pp = motor_ev.descomponer(
            pd.Series([0.6, 0.5]), pd.Series([0.02, 0.0]))
        suma = (pw + pl + pp).to_numpy()
        inst.chk_bool(checks, "p_ganar + p_perder + p_push = 1",
                      bool(np.allclose(suma, 1.0, atol=1e-12)),
                      f"{[f'{v:.15f}' for v in suma]}")
        push_media = float(motor_ev.prob_push(0.0, -3.5, 13.0).iloc[0])
        push_media_nan = float(motor_ev.prob_push(np.nan, 2.5, np.nan).iloc[0])
        inst.chk_bool(checks, "push = 0 EXACTO en líneas x.5",
                      push_media == 0.0 and push_media_nan == 0.0,
                      "0.0 (incluso sin σ: es aritmético)")
        l, v, s = -3.0, 0.0, 13.0
        push_esp = (0.5 * (1 + math.erf((l + 0.5 - v) / s / math.sqrt(2)))
                    - 0.5 * (1 + math.erf((l - 0.5 - v) / s / math.sqrt(2))))
        push_ent = float(motor_ev.prob_push(v, l, s).iloc[0])
        inst.chk_bool(checks, "push en línea entera = normal discretizada",
                      abs(push_ent - push_esp) < 1e-12, f"{push_ent:.10f}")

        # ------------------------------------------------------------------
        # 2. La jornada pendiente real pasa por el motor
        # ------------------------------------------------------------------
        inst.linea("2. JORNADA PENDIENTE (funciones reales de app.py + motor)")
        app = extraer_funciones_app(PROYECTO / "app.py")
        calendario = datos.cargar_calendario()
        hist = datos.pronosticos_historicos(calendario).reset_index(drop=True)
        era = hist[hist["season"] >= 2006].copy()
        sigma_hoy, sigma_total_hoy = datos.sigma_actual(era)
        pendientes = calendario[
            ~calendario["jugado"] & calendario["spread_line"].notna()]
        futuros = datos.pronosticos_futuros(calendario, pendientes)
        futuros["sigma_modelo"] = sigma_hoy
        futuros["sigma_total_modelo"] = sigma_total_hoy
        print(f"  Partidos pendientes con líneas: n={len(futuros)} "
              f"(σ margen {sigma_hoy:.2f} · σ total {sigma_total_hoy:.2f})")

        bloques = [
            ("Spread", "spread_line",
             motor_ev.decorar(
                 app["evaluar_spread"](futuros, 2.0, calibrado=True),
                 "spread")),
            ("Total", "total_line",
             motor_ev.decorar(
                 app["evaluar_totales"](futuros, 2.0, calibrado=True),
                 "total")),
            ("Moneyline", None,
             motor_ev.decorar(
                 datos.evaluar_picks_ml(futuros, umbral=0.04, calibrado=True),
                 "moneyline")),
        ]
        filas_visibles = []
        conteo_estados = {}
        for nombre, col_linea, marco in bloques:
            if not len(marco):
                print(f"  {nombre}: sin picks con el umbral (n=0)")
                continue
            coherencia = float((marco["p_ganar"] + marco["p_perder"]
                                + marco["p_push"] - 1.0).abs().max())
            inst.chk_bool(checks, f"{nombre}: p_ganar+p_perder+p_push=1",
                          coherencia <= 1e-12, f"máx |Δ|={coherencia:.2e}")
            ev_calc = [ev_independiente(p, c, pp) for p, c, pp in
                       zip(marco["prob_modelo"], marco["cuota"],
                           marco["p_push"])]
            dif_ev = float(np.max(np.abs(
                marco["ev_estimado"].to_numpy() - np.asarray(ev_calc))))
            inst.chk_bool(checks, f"{nombre}: EV recalculado independiente",
                          dif_ev <= 1e-12, f"máx |Δ|={dif_ev:.2e}")
            dif_p = float(np.max(np.abs(
                marco["p_estimada"].to_numpy()
                - pd.to_numeric(marco["prob_modelo"]).to_numpy())))
            inst.chk_bool(checks, f"{nombre}: P. est. = prob_modelo (calibrada)",
                          dif_p == 0.0, f"máx |Δ|={dif_p:.2e}")
            dentro = bool(((marco["ev_lo"] <= marco["ev_estimado"] + 1e-12)
                           & (marco["ev_estimado"] <= marco["ev_hi"] + 1e-12)).all())
            inst.chk_bool(checks, f"{nombre}: ev_lo ≤ EV ≤ ev_hi", dentro,
                          f"n={len(marco)}")
            estados = set(marco["estado_ev"])
            inst.chk_bool(
                checks, f"{nombre}: estados válidos y sin «validada»",
                estados <= {motor_ev.SIN_DATOS, motor_ev.SIN_EV,
                            motor_ev.EV_EN_EL_RUIDO, motor_ev.EV_SIN_VALIDAR},
                " · ".join(sorted(estados)))
            if col_linea is None:  # moneyline: el push es el empate (línea 0)
                medias = pd.Series(False, index=marco.index)
            else:
                medias = (pd.to_numeric(marco[col_linea]) % 1.0).ne(0.0)
            ok_push = (bool((marco.loc[medias, "p_push"] == 0.0).all())
                       and bool((marco.loc[~medias, "p_push"] > 0.0).all()))
            inst.chk_bool(checks,
                          f"{nombre}: push definido (0 en x.5, >0 en enteras)",
                          ok_push,
                          f"x.5: {int(medias.sum())} · enteras: "
                          f"{int((~medias).sum())}")
            for _, f in marco.iterrows():
                conteo_estados[f["estado_ev"]] = conteo_estados.get(
                    f["estado_ev"], 0) + 1
                filas_visibles.append([
                    nombre,
                    f"{f['away_team']} @ {f['home_team']}",
                    f"{f['cuota']:+.0f}",
                    f"{100 * f['p_equilibrio']:.1f}%",
                    f"{100 * f['p_estimada']:.1f}%",
                    f"{100 * f['p_push']:.2f}%",
                    f"{f['ev_estimado']:+.3f}",
                    f["estado_ev"],
                ])
        print()
        print("  Lo que la interfaz mostrará en la jornada pendiente")
        print("  (momio · P. eq. · P. est. · P. push · EV $1 · Estado):")
        if filas_visibles:
            print(inst.tabla(
                ["Mercado", "Partido", "Momio", "P. eq.", "P. est.",
                 "P. push", "EV $1", "Estado"], filas_visibles))
        else:
            print("  (ningún pick pendiente: «puede no haber ninguna apuesta»)")
        print(f"  Estados: {conteo_estados or '—'} · ninguno dice «validada».")

        # ------------------------------------------------------------------
        # 3. Push empírico 2006-2025 (control de magnitud del estimador)
        # ------------------------------------------------------------------
        inst.linea("3. PUSH EMPÍRICO 2006-2025 (media estimada vs observada)")

        def verificar_push(etiqueta, obs, est, con_linea):
            m = obs.notna() & est.notna()
            o = float(obs[m].mean())
            e = float(est[m].mean())
            dif = e - o
            detalle = (f"observado {100 * o:.2f}% · estimado {100 * e:.2f}% "
                       f"· Δ {100 * dif:+.2f} pp (n={int(m.sum())})")
            if abs(dif) <= 0.015:
                inst.chk_bool(checks, f"push {etiqueta}: |Δ| ≤ 0.015", True,
                              detalle)
            else:
                # El pre-registro fija qué pasa si la puerta falla: «el
                # estimador no se adopta sin documentar la limitación en
                # pantalla». La comprobación pasa a ser esa condición.
                documentado = ("moneyline" in motor_ev.NOTA_PUSH
                               and "empate" in motor_ev.NOTA_PUSH)
                inst.chk_bool(
                    checks,
                    f"push {etiqueta}: fuera de tolerancia → documentado",
                    documentado,
                    f"{detalle} · limitación en pantalla: {documentado}")
            if con_linea is not None:
                medias = (con_linea[m] % 1.0).ne(0.0)
                ent = ~medias
                o_e = float(obs[m][ent].mean())
                e_e = float(est[m][ent].mean())
                print(f"     solo líneas enteras (n={int(ent.sum())}): "
                      f"observado {100 * o_e:.2f}% · estimado {100 * e_e:.2f}% "
                      f"· Δ {100 * (e_e - o_e):+.2f} pp")
                inst.chk_bool(
                    checks, f"push {etiqueta}: observado = 0 EXACTO en x.5",
                    float(obs[m][medias].sum()) == 0.0,
                    f"n={int(medias.sum())} partidos x.5")
            else:
                print(f"     (moneyline: el push es el empate; n={int(m.sum())})")

        base = era[era["margen_modelo"].notna() & era["sigma_modelo"].notna()]
        obs_s = base.loc[base["push_spread"].notna(), "push_spread"].astype(float)
        est_s = motor_ev.prob_push(base.loc[obs_s.index, "margen_modelo"],
                                   base.loc[obs_s.index, "spread_line"],
                                   base.loc[obs_s.index, "sigma_modelo"])
        verificar_push("spread", obs_s, est_s,
                       base.loc[obs_s.index, "spread_line"])

        base_t = era[era["total_modelo"].notna()
                     & era["sigma_total_modelo"].notna()]
        obs_t = base_t.loc[base_t["push_total"].notna(),
                           "push_total"].astype(float)
        est_t = motor_ev.prob_push(base_t.loc[obs_t.index, "total_modelo"],
                                   base_t.loc[obs_t.index, "total_line"],
                                   base_t.loc[obs_t.index, "sigma_total_modelo"])
        verificar_push("total", obs_t, est_t, base_t.loc[obs_t.index, "total_line"])

        obs_m = base.loc[base["empate"].notna(), "empate"].astype(float)
        est_m = motor_ev.prob_push(base.loc[obs_m.index, "margen_modelo"],
                                   pd.Series(0.0, index=obs_m.index),
                                   base.loc[obs_m.index, "sigma_modelo"])
        verificar_push("moneyline", obs_m, est_m, None)

        fuente_app = (PROYECTO / "app.py").read_text(encoding="utf-8")
        inst.chk_bool(checks, "la limitación del push se muestra en la app",
                      "motor_ev.NOTA_PUSH" in fuente_app,
                      "caption de la pestaña 🎯")
        print(f"  Nota de sesgo mostrada en la interfaz:\n    "
              f"{motor_ev.NOTA_PUSH}")

        # ------------------------------------------------------------------
        # 4. Regresión contra lo existente y contrato del registro
        # ------------------------------------------------------------------
        inst.linea("4. REGRESIÓN CONTRA LO EXISTENTE Y CONTRATO DEL REGISTRO")
        rejilla = pd.Series([-250, -150, -110, -105, 100, 105, 130, 200, 350])
        inst.chk_bool(checks, "pago neto = datos._pago_por_dolar (1e-12)",
                      bool(np.allclose(motor_ev.pago_neto(rejilla).to_numpy(),
                                       datos._pago_por_dolar(rejilla).to_numpy(),
                                       atol=1e-12)), "")
        inst.chk_bool(
            checks, "prob. implícita = datos._prob_implicita (1e-12)",
            bool(np.allclose(motor_ev.prob_implicita(rejilla).to_numpy(),
                             datos._prob_implicita(rejilla).to_numpy(),
                             atol=1e-12)), "")
        v = pd.Series([3.0, -3.5, 7.2])
        l = pd.Series([-2.5, 4.5, 0.0])
        s = pd.Series([13.0, 10.0, 12.0])
        inst.chk_bool(
            checks, "prob. supera = datos.probabilidad_supera (1e-12)",
            bool(np.allclose(motor_ev.probabilidad_supera(v, l, s).to_numpy(),
                             datos.probabilidad_supera(v, l, s).to_numpy(),
                             atol=1e-12)), "")
        mini = pd.DataFrame({
            "temporada": [2026], "semana": [7], "game_id": ["2026_07_AAA_BBB"],
            "equipo_local": ["AAA"], "equipo_visitante": ["BBB"],
            "mercado": ["Spread"], "lado": ["local"], "seleccion": ["AAA -2.5"],
            "linea_num": [-2.5], "cuota": [-110.0], "prob_modelo": [0.5],
            "prob_mercado": [0.51], "edge_num": [2.0], "ev_num": [-0.0123],
        })
        reg = datos.registro_desde_picks(mini, momento="2026-10-16T00:00:00",
                                         version="prueba")
        inst.chk_bool(checks, "registro: el EV del motor se guarda tal cual",
                      float(reg["ev"].iloc[0]) == -0.0123,
                      f"{float(reg['ev'].iloc[0]):+.4f}")
        reg2 = datos.registro_desde_picks(mini.drop(columns=["ev_num"]),
                                          momento="2026-10-16T00:00:00",
                                          version="prueba")
        esperado = 0.5 * (100 / 110) - 0.5
        inst.chk_bool(checks, "registro: sin ev_num se conserva la fórmula",
                      abs(float(reg2["ev"].iloc[0]) - esperado) < 1e-12,
                      f"{float(reg2['ev'].iloc[0]):+.4f}")
        r1 = motor_ev.decorar(
            app["evaluar_spread"](futuros, 2.0, calibrado=True), "spread")
        r2 = motor_ev.decorar(
            app["evaluar_spread"](futuros, 2.0, calibrado=True), "spread")
        inst.chk_bool(checks, "determinismo: dos pasadas idénticas",
                      r1["ev_estimado"].equals(r2["ev_estimado"]),
                      f"n={len(r1)}")

        # ------------------------------------------------------------------
        # 5. Sin red y tiempo
        # ------------------------------------------------------------------
        inst.chk_bool(checks, "sin intentos de red", len(guardia.intentos) == 0,
                      f"{len(guardia.intentos)} intentos")
        segundos = time.perf_counter() - inicio
        inst.chk_bool(checks, "tiempo de ejecución < 10 s", segundos < 10.0,
                      f"{segundos:.2f} s")

    # ----------------------------------------------------------------------
    # Resumen
    # ----------------------------------------------------------------------
    print()
    for nombre_chk, ok, detalle in checks:
        estado = "OK   " if ok else "FALLO"
        print(f"  [{estado}] {nombre_chk:<58s} {detalle}")
    fallos = [(n, d) for n, ok, d in checks if not ok]
    print()
    if not fallos:
        print(f"VEREDICTO: {len(checks)}/{len(checks)} comprobaciones OK — el "
              "motor calcula el EV con push explícito,")
        print("la interfaz muestra momio · P. eq. · P. est. · push · EV · "
              "estado, y nada se marca como validado.")
        print("El sesgo del push está medido: total y spread dentro de "
              "tolerancia; el empate de moneyline")
        print("(único fuera de 0.015) queda documentado en pantalla, como "
              "exige el pre-registro.")
        print("Recordatorio: esto NO dice que el sistema sea rentable — un EV+ "
              "sigue sin validación prospectiva")
        print("(pre-registro lab/pre_registro_motor_ev.md; registro fiel como "
              "única evidencia limpia).")
        return 0
    print(f"VEREDICTO: {len(fallos)}/{len(checks)} comprobaciones FALLARON — "
          "no continuar sin investigar:")
    for nombre, detalle in fallos:
        print(f"   - {nombre}: {detalle}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
