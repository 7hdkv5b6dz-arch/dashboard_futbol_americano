#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificación de la integración de la calibración (F4) — offline y determinista.

Qué comprueba
-------------
La ruta de decisión de la jornada pendiente de la app (app.py), ejecutando las
funciones REALES extraídas de app.py por AST (sin arrancar Streamlit):
- spread/totales: la selección por edge en PUNTOS no cambia; lo que cambia es
  `prob_modelo`, que pasa a ser la calibrada (F4).
- moneyline: la selección usa la probabilidad; con la mezcla calibrada los
  edges ≈ 0 y no se emiten picks (resultado medido en F4).
- la versión que la app sella en el registro fiel: `srs-v2+cal-f4-1`.
Además imprime un ejemplo de EV bruto vs calibrado para el registro.

Cómo se corre (desde la carpeta del proyecto):
    .venv/bin/python -B lab/verificacion_integracion.py

Sale con código 1 si alguna comprobación falla. No escribe nada, no usa red.
"""

import ast
import hashlib
import socket
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROYECTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROYECTO))
import calibracion  # noqa: E402  (producción: calibracion.py de la raíz)
import datos  # noqa: E402


def extraer_funciones_app(ruta_app: Path) -> dict:
    """Las funciones de decisión REALES de app.py, sin ejecutar Streamlit.

    Extrae por AST solo las definiciones necesarias (nada de código de UI) y
    las compila en un espacio con `np`, `pd`, `datos` y `calibracion`.
    """
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


def chk_bool(checks, nombre, ok, detalle=""):
    checks.append((nombre, bool(ok), detalle))


def ev_por_dolar(p, cuota):
    """EV ($ por $1) con una probabilidad y una cuota americanas."""
    pago = (cuota / 100.0) if cuota > 0 else (100.0 / -cuota)
    return p * pago - (1.0 - p)


class GuardiaRed:
    """Bloquea sockets: si algo intenta red, falla ruidosamente y se anota."""

    def __enter__(self):
        self._socket = socket.socket
        self.intentos = []

        def _prohibido(*args, **kwargs):
            self.intentos.append(1)
            raise RuntimeError("Esta verificación no usa red.")

        socket.socket = _prohibido
        socket.create_connection = _prohibido
        return self

    def __exit__(self, *exc):
        socket.socket = self._socket
        return False


def main() -> int:
    inicio = time.perf_counter()
    checks = []

    print("=" * 84)
    print("Verificación de la integración de la calibración (F4) — "
          "funciones reales de app.py")
    print("=" * 84)
    for nombre in ("app.py", "datos.py", "calibracion.py"):
        sha = hashlib.sha1((PROYECTO / nombre).read_bytes()).hexdigest()[:12]
        print(f"  {nombre:<16s} sha1 {sha}")
    print()

    with GuardiaRed() as guardia:
        app = extraer_funciones_app(PROYECTO / "app.py")

        # --- Datos, igual que la app ---------------------------------------
        calendario = datos.cargar_calendario()
        hist = datos.pronosticos_historicos(calendario).reset_index(drop=True)
        era = hist[hist["season"] >= 2006].copy()
        sigma_hoy, sigma_total_hoy = datos.sigma_actual(era)
        pendientes = calendario[
            ~calendario["jugado"] & calendario["spread_line"].notna()]
        futuros = datos.pronosticos_futuros(calendario, pendientes)
        futuros["sigma_modelo"] = sigma_hoy
        futuros["sigma_total_modelo"] = sigma_total_hoy
        print(f"Jornada pendiente con líneas: n={len(futuros)} "
              f"(sigma margen {sigma_hoy:.2f} · sigma total "
              f"{sigma_total_hoy:.2f})")

        # --- Muestra determinista del histórico ----------------------------
        muestra = era.tail(300).copy()
        print(f"Muestra de comportamiento: últimos {len(muestra)} partidos "
              f"de la era (temporadas "
              f"{int(muestra['season'].min())}-{int(muestra['season'].max())})")
        print()

        # --- 1) Spread y totales: la selección no cambia; la prob sí --------
        print("-- Spread y totales (selección por edge en puntos, umbral 2.0)")
        for mercado, funcion, campo, sigma_col in (
            ("Spread", app["evaluar_spread"], "spread_line", "sigma_modelo"),
            ("Total", app["evaluar_totales"], "total_line",
             "sigma_total_modelo"),
        ):
            bruto = funcion(muestra, 2.0, calibrado=False)
            cal = funcion(muestra, 2.0, calibrado=True)
            chk_bool(checks, f"{mercado}: selección idéntica (puntos) "
                             f"bruto vs calibrado",
                     len(bruto) == len(cal),
                     f"n bruto={len(bruto)} · n calibrado={len(cal)}")
            if len(cal):
                dif = (cal["prob_modelo"]
                       - bruto.loc[cal.index, "prob_modelo"]).abs()
                chk_bool(checks, f"{mercado}: la probabilidad congelada "
                                 f"cambia (calibrada)",
                         float(dif.max()) > 1e-6,
                         f"|Δp| máx={float(dif.max()):.4f}")
                bruta = bruto.loc[cal.index, "prob_modelo"]
                aplanado_b = float((bruta - 0.5).abs().mean())
                aplanado_c = float((cal["prob_modelo"] - 0.5).abs().mean())
                chk_bool(checks, f"{mercado}: la calibrada aplana la falsa "
                                 f"confianza",
                         aplanado_c < aplanado_b,
                         f"|p−0.5| medio {aplanado_b:.4f} → {aplanado_c:.4f}")
                # Fórmula independiente (lado del pick) con el módulo real:
                p_local = datos.probabilidad_supera(
                    muestra.loc[cal.index, "margen_modelo" if mercado == "Spread"
                                else "total_modelo"],
                    muestra.loc[cal.index, campo],
                    muestra.loc[cal.index, sigma_col])
                lado = cal["al_local"] if mercado == "Spread" else cal["al_over"]
                esperado = calibracion.calibrar(
                    "spread" if mercado == "Spread" else "total", p_local)
                esperado = esperado.where(lado, 1.0 - esperado)
                chk_bool(checks, f"{mercado}: prob del lado = calibrar(bruta)",
                         np.allclose(cal["prob_modelo"], esperado,
                                     atol=1e-12),
                         f"máx |Δ|={float((cal['prob_modelo'] - esperado).abs().max()):.2e}")

        # --- 2) Moneyline: el bruto emite, el calibrado suprime -------------
        print()
        print("-- Moneyline (selección por edge de probabilidad, umbral 4 pp)")
        ml_bruto = datos.evaluar_picks_ml(muestra, umbral=0.04)
        ml_cal = datos.evaluar_picks_ml(muestra, umbral=0.04, calibrado=True)
        chk_bool(checks, "Moneyline bruto: emite picks en la muestra",
                 len(ml_bruto) > 0, f"n={len(ml_bruto)}")
        chk_bool(checks, "Moneyline calibrado: 0 picks (la mezcla sigue al "
                         "mercado)",
                 len(ml_cal) == 0, f"n={len(ml_cal)}")

        # --- 3) Jornada pendiente: qué congelaría el registro fiel ----------
        print()
        print("-- Jornada pendiente (lo que la app congelaría hoy)")
        if len(futuros):
            for mercado, funcion in (("Spread", app["evaluar_spread"]),
                                     ("Total", app["evaluar_totales"])):
                fs = funcion(futuros, 2.0, calibrado=True)
                print(f"   {mercado}: {len(fs)} picks pendientes")
                for _, fila in fs.head(3).iterrows():
                    print(f"      {fila['away_team']} @ {fila['home_team']} · "
                          f"edge {fila['edge']:+.1f} pts · p_cal "
                          f"{fila['prob_modelo']:.4f}")
            fm = datos.evaluar_picks_ml(futuros, umbral=0.04, calibrado=True)
            fm_bruto = datos.evaluar_picks_ml(futuros, umbral=0.04)
            print(f"   Moneyline: bruto {len(fm_bruto)} → calibrado "
                  f"{len(fm)} picks")
        else:
            print("   (sin partidos pendientes con líneas publicadas)")

        # --- 4) Ejemplo de EV bruto vs calibrado ----------------------------
        print()
        print("-- Ejemplo de EV ($ por $1) que quedaría en el registro fiel")
        bruto = app["evaluar_spread"](muestra, 2.0, calibrado=False)
        cal = app["evaluar_spread"](muestra, 2.0, calibrado=True)
        if len(cal):
            fila = cal.iloc[0]
            p_b = float(bruto.loc[cal.index[0], "prob_modelo"])
            p_c = float(fila["prob_modelo"])
            cuota = float(fila["cuota"])
            print(f"   {fila['away_team']} @ {fila['home_team']} · "
                  f"cuota {cuota:+.0f} · p bruta {p_b:.4f} → "
                  f"p calibrada {p_c:.4f}")
            print(f"   EV bruto {ev_por_dolar(p_b, cuota):+.4f} → "
                  f"EV calibrado {ev_por_dolar(p_c, cuota):+.4f} $ por $1")
            chk_bool(checks, "El EV congelado ya no está inflado por la "
                             "falsa confianza",
                     ev_por_dolar(p_c, cuota) < ev_por_dolar(p_b, cuota),
                     f"{ev_por_dolar(p_c, cuota):+.4f} < "
                     f"{ev_por_dolar(p_b, cuota):+.4f}")

        # --- 5) Versión del registro ----------------------------------------
        version = f"{datos.VERSION_MODELO}+{calibracion.VERSION_CALIBRACION}"
        chk_bool(checks, "Versión compuesta del registro fiel",
                 version == "srs-v2+cal-f4-1", version)

        # --- 6) Sin red y tiempo --------------------------------------------
        chk_bool(checks, "sin intentos de red", len(guardia.intentos) == 0,
                 f"{len(guardia.intentos)} intentos")
        segundos = time.perf_counter() - inicio
        chk_bool(checks, "tiempo de ejecución < 10 s", segundos < 10.0,
                 f"{segundos:.2f} s")

    # --- Resumen ------------------------------------------------------------
    print()
    for nombre, ok, detalle in checks:
        estado = "OK   " if ok else "FALLO"
        print(f"  [{estado}] {nombre:<52s} {detalle}")
    fallos = [(n, d) for n, ok, d in checks if not ok]
    print()
    if not fallos:
        print(f"VEREDICTO: {len(checks)}/{len(checks)} comprobaciones OK — "
              "la integración hace lo que F4 midió: selección intacta, "
              "probabilidad congelada calibrada, moneyline sin picks.")
        return 0
    print(f"VEREDICTO: {len(fallos)}/{len(checks)} comprobaciones FALLARON — "
          "no continuar sin investigar:")
    for nombre, detalle in fallos:
        print(f"   - {nombre}: {detalle}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
