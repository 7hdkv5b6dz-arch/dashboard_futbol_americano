#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificaciones de apoyo para el informe F4 (evidencia complementaria).

Se ejecuta DESPUÉS de lab/calibracion.py y no cambia nada: solo profundiza en
tres puntos que el informe F4 necesita demostrar.

1) Regenera las predicciones walk-forward por mercado y compara los candidatos
   en una ventana COMÚN (la de la isótona) para el mercado Spread — la regla
   de selección pre-registrada no fijó ventana de comparación entre candidatos
   con coberturas distintas.
2) Resume ΔBrier de cada candidato frente al MERCADO (B) por mercado
   (¿queda algo mejor que el mercado tras calibrar?).
3) Rejilla de verosimilitud (con intercepto óptimo en cada punto) para
   comprobar que el óptimo de Platt (b≈0.06 en spread/total, b≈0.96 en
   moneyline) es el auténtico MLE y no un error del ajuste.

Solo lectura · sin red · determinista (semilla del instrumento).
Este archivo es evidencia de apoyo, no forma parte del pipeline de la app.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROYECTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROYECTO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import datos  # noqa: E402
import evaluacion as inst  # noqa: E402
import calibracion as cal  # noqa: E402

gen = np.random.default_rng(inst.SEMILLA_BOOTSTRAP)

calendario = datos.cargar_calendario()
hist = datos.pronosticos_historicos(calendario).reset_index(drop=True)
era = hist[hist["season"] >= 2006].reset_index(drop=True)
era["p_local_modelo"] = datos.probabilidad_supera(
    era["margen_modelo"], era["spread_line"], era["sigma_modelo"])
era["p_over_modelo"] = datos.probabilidad_supera(
    era["total_modelo"], era["total_line"], era["sigma_total_modelo"])
po = datos._prob_implicita(era["over_odds"])
pu = datos._prob_implicita(era["under_odds"])
p_ml_mod = datos.probabilidades_ml(era["margen_modelo"], era["sigma_modelo"])[0]

frames = {
    "Spread": pd.DataFrame({
        "season": era["season"], "p_mod": era["p_local_modelo"],
        "p_mer": era["prob_local_spread_sin_vig"],
        "y": inst.flot(era["cubre_local"].mask(era["push_spread"].fillna(False))),
    }).dropna().reset_index(drop=True),
    "Total": pd.DataFrame({
        "season": era["season"], "p_mod": era["p_over_modelo"],
        "p_mer": po / (po + pu), "y": inst.flot(era["over"]),
    }).dropna().reset_index(drop=True),
    "Moneyline": pd.DataFrame({
        "season": era["season"], "p_mod": p_ml_mod,
        "p_mer": era["prob_local_sin_vig"],
        "y": inst.flot(era["gano_local"].mask(era["empate"].fillna(False))),
    }).dropna().reset_index(drop=True),
}


def generar(frame):
    """Mismo walk-forward que lab/calibracion.py (copia fiel del bucle)."""
    evaluados = frame[(frame["season"] >= 2014) & (frame["season"] <= 2025)].reset_index(drop=True)
    seasons = evaluados["season"].to_numpy()
    y = evaluados["y"].to_numpy()
    n = len(evaluados)
    preds = {c: np.full(n, np.nan) for c in ("A", "B", "C1", "C2", "D")}
    preds["A"] = evaluados["p_mod"].to_numpy()
    preds["B"] = evaluados["p_mer"].to_numpy()
    iso_seasons = []
    for s in range(2014, 2026):
        tr = frame[frame["season"] < s]
        te = frame[frame["season"] == s]
        idx = seasons == s
        if not idx.any() or len(tr) < 100 or not len(te):
            continue
        beta1 = cal.ajustar_logistica(cal.logit(tr["p_mod"]), tr["y"].to_numpy())
        preds["C1"][idx] = cal.sigmoide(beta1[0] + beta1[1] * cal.logit(te["p_mod"].to_numpy()))
        if len(tr) >= cal.MIN_AJUSTE_ISOTONA:
            f = cal.ajustar_isotona(tr["p_mod"].to_numpy(), tr["y"].to_numpy())
            preds["C2"][idx] = f(te["p_mod"].to_numpy())
            iso_seasons.append(s)
        Xtr = np.column_stack([cal.logit(tr["p_mod"]), cal.logit(tr["p_mer"])])
        bD = cal.ajustar_logistica(Xtr, tr["y"].to_numpy())
        Xte = np.column_stack([cal.logit(te["p_mod"]), cal.logit(te["p_mer"])])
        preds["D"][idx] = cal.sigmoide(bD[0] + Xte @ bD[1:])
    return seasons, y, preds, iso_seasons


def delta(y, pc, pr, m):
    m = m & ~np.isnan(pc) & ~np.isnan(pr)
    d = (pc[m] - y[m]) ** 2 - (pr[m] - y[m]) ** 2
    return inst.ic_media(gen, d)


for nombre, frame in frames.items():
    seasons, y, preds, iso = generar(frame)
    mask_iso = np.isin(seasons, iso) if iso else np.zeros(len(y), bool)
    mask_full = np.ones(len(y), bool)
    print("=" * 84)
    print(f"Mercado: {nombre} | temporadas iso: {iso} | n ventana iso: {int(mask_iso.sum())} / {len(y)}")

    print("-- Ventana completa 2014–2025: ΔBrier vs A y vs B (IC95%)")
    for c in ("B", "C1", "C2", "D"):
        m1 = mask_full & ~np.isnan(preds[c])
        d_a = delta(y, preds[c], preds["A"], mask_full)
        d_b = delta(y, preds[c], preds["B"], mask_full)
        print(f"   {c:>3s} (n={int(m1.sum())}): vsA [{d_a[0]:+.4f} {d_a[1]:+.4f},{d_a[2]:+.4f}]"
              f"  vsB [{d_b[0]:+.4f} {d_b[1]:+.4f},{d_b[2]:+.4f}]")

    if iso:
        print("-- Ventana de la isótona (común): ΔBrier vs A y vs B (IC95%)")
        for c in ("A", "B", "C1", "C2", "D"):
            d_a = delta(y, preds[c], preds["A"], mask_iso)
            d_b = delta(y, preds[c], preds["B"], mask_iso)
            b_abs = float(np.mean((preds[c][mask_iso] - y[mask_iso]) ** 2))
            print(f"   {c:>3s}: Brier={b_abs:.4f}  vsA [{d_a[0]:+.4f} {d_a[1]:+.4f},{d_a[2]:+.4f}]"
                  f"  vsB [{d_b[0]:+.4f} {d_b[1]:+.4f},{d_b[2]:+.4f}]")
        b_05 = float(np.mean((0.5 - y[mask_iso]) ** 2))
        print(f"   const 0.5: Brier={b_05:.4f}")

    x = cal.logit(frame["p_mod"].to_numpy())
    yy = frame["y"].to_numpy()
    print("-- Rejilla NLL (intercepto óptimo por punto), ajuste 2006–2025:")
    for b in (0.0, 0.02, 0.05, 0.06, 0.064, 0.07, 0.08, 0.1, 0.15, 0.2, 0.3, 0.5, 0.8, 0.95, 1.0):
        a = 0.0
        for _ in range(200):
            p = cal.sigmoide(a + b * x)
            paso = np.sum(p - yy) / max(np.sum(p * (1 - p)), 1e-12)
            a -= paso
            if abs(paso) < 1e-12:
                break
        p = np.clip(cal.sigmoide(a + b * x), 1e-12, 1 - 1e-12)
        nll = -np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))
        print(f"     b={b:5.3f}  a={a:+.4f}  NLL medio={nll:.6f}")
    beta = cal.ajustar_logistica(x, yy)
    p = np.clip(cal.sigmoide(beta[0] + beta[1] * x), 1e-12, 1 - 1e-12)
    nll = -np.mean(yy * np.log(p) + (1 - yy) * np.log(1 - p))
    print(f"   MLE Newton: a={beta[0]:+.4f} b={beta[1]:.4f}  NLL medio={nll:.6f}")

print("\nFin de la verificación de apoyo F4 (no escribe nada).")
