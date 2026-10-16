#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F4 — Calibración walk-forward de las probabilidades del modelo (medición).

Compara, sobre los MISMOS partidos y por mercado (spread, total, moneyline):
  A) modelo crudo · B) mercado sin vig · C1) Platt · C2) isotónica (PAVA)
  D) mezcla logística (modelo + mercado),
ajustando cada calibrador SOLO con temporadas anteriores a la evaluada.

Las reglas y puertas están pre-registradas en:
    lab/pre_registro_calibracion.md  (escrito antes de medir)

Solo lectura · sin red · determinista (salvo la línea de tiempo).
Reutiliza convenciones y utilidades del instrumento v3 (lab/evaluacion.py).
"""

import hashlib
import math
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROYECTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROYECTO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import datos  # noqa: E402
import evaluacion as inst  # noqa: E402

pd.set_option("display.width", 170)

SEMILLA = inst.SEMILLA_BOOTSTRAP          # mismo compromiso de reproducibilidad
TEMPORADAS_EVAL = list(range(2014, 2026))
MIN_AJUSTE_ISOTONA = 3000
UMBRAL = -0.001                            # G1/G2: Δ ≤ −0.001

ETIQUETAS = {"A": "A crudo", "B": "B mercado", "C1": "C1 Platt",
             "C2": "C2 Isótona", "D": "D mezcla"}
PARAMETROS = {"C1": 2, "D": 3, "C2": 10**6}  # para el desempate pre-registrado


# ---------------------------------------------------------------------------
# Herramientas de calibración (deterministas, sin dependencias nuevas)
# ---------------------------------------------------------------------------
def logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(p / (1.0 - p))


def sigmoide(z):
    z = np.asarray(z, dtype=float)
    salida = np.empty_like(z)
    pos = z >= 0
    salida[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    salida[~pos] = ez / (1.0 + ez)
    return salida


def ajustar_logistica(X, y, l2=1e-6, max_iter=100, tol=1e-10):
    """Logística por Newton-Raphson (intercepto + pendientes), determinista."""
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    y = np.asarray(y, dtype=float)
    n, k = X.shape
    Xd = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    penal = np.r_[0.0, np.ones(k)]
    for _ in range(max_iter):
        p = sigmoide(Xd @ beta)
        grad = Xd.T @ (p - y) + l2 * penal * beta
        w = p * (1.0 - p)
        hess = (Xd.T * w) @ Xd + l2 * np.diag(penal)
        try:
            paso = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            paso, *_ = np.linalg.lstsq(hess, grad, rcond=None)
        beta = beta - paso
        if np.max(np.abs(paso)) < tol:
            break
    return beta


def ajustar_isotona(p, y):
    """PAVA sobre (p, y); devuelve una función p → probabilidad calibrada."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    orden = np.argsort(p, kind="stable")
    ps, ys = p[orden], y[orden]
    vals, pesos, cuentas = [], [], []
    for yi in ys:
        vals.append(float(yi))
        pesos.append(1.0)
        cuentas.append(1)
        while len(vals) >= 2 and vals[-2] > vals[-1]:
            v2, w2, c2 = vals.pop(), pesos.pop(), cuentas.pop()
            v1, w1, c1 = vals.pop(), pesos.pop(), cuentas.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            pesos.append(w1 + w2)
            cuentas.append(c1 + c2)
    ajuste = np.repeat(np.asarray(vals, dtype=float), cuentas)
    xu, inv = np.unique(ps, return_inverse=True)
    fit_u = np.bincount(inv, weights=ajuste) / np.bincount(inv)

    def predecir(p_test):
        return np.clip(np.interp(np.asarray(p_test, dtype=float), xu, fit_u),
                       1e-6, 1.0 - 1e-6)

    return predecir


def brier_filas(p, y):
    return (np.asarray(p, dtype=float) - np.asarray(y, dtype=float)) ** 2


def ll_filas(p, y, e=1e-12):
    p = np.clip(np.asarray(p, dtype=float), e, 1.0 - e)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def metricas(p, y):
    """(n, Brier, LogLoss) sobre las filas donde p está definida."""
    m = ~np.isnan(p)
    return inst._brier_ll(pd.Series(p[m]), pd.Series(y[m]))


def delta_ic(gen, p_cand, p_ref, y, metrica="brier"):
    """Δ medio pareado (candidato − referencia) y su IC95% bootstrap."""
    m = ~np.isnan(p_cand) & ~np.isnan(p_ref) & ~np.isnan(y)
    if metrica == "brier":
        d = brier_filas(p_cand[m], y[m]) - brier_filas(p_ref[m], y[m])
    else:
        d = ll_filas(p_cand[m], y[m]) - ll_filas(p_ref[m], y[m])
    return inst.ic_media(gen, d)


def consistencia(p_cand, p_ref, y, seasons):
    """Temporadas (con ≥50 partidos) en que el ΔBrier medio es < 0."""
    mejor = total = 0
    for s in np.unique(seasons):
        m = (seasons == s) & ~np.isnan(p_cand)
        if m.sum() < 50:
            continue
        total += 1
        if brier_filas(p_cand[m], y[m]).mean() < brier_filas(p_ref[m], y[m]).mean():
            mejor += 1
    return mejor, total


# ---------------------------------------------------------------------------
def main():
    inicio = time.perf_counter()
    checks = []
    gen = np.random.default_rng(SEMILLA)
    guardia = inst.GuardiaRed()
    ruta_pre = Path(__file__).resolve().parent / "pre_registro_calibracion.md"
    sha_pre = hashlib.sha1(ruta_pre.read_bytes()).hexdigest()[:12]

    with guardia:
        inst.linea("CALIBRACIÓN WALK-FORWARD (F4) — modelo srs-v2 — era 2006+")
        print(f"Fecha: {date.today().isoformat()} | semilla bootstrap: {SEMILLA} "
              f"| remuestreos: {inst.N_BOOTSTRAP}")
        print(f"Pre-registro: lab/pre_registro_calibracion.md (sha1 {sha_pre})")
        print("Evaluación: temporadas 2014–2025 | 2026 = informativo | solo lectura · sin red")

        # ------------------------------------------------------------------
        # Datos (mismas piezas y convenciones que el instrumento v3)
        # ------------------------------------------------------------------
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

        crudos = {
            "Spread": pd.DataFrame({
                "season": era["season"],
                "p_mod": era["p_local_modelo"],
                "p_mer": era["prob_local_spread_sin_vig"],
                "y": inst.flot(era["cubre_local"].mask(era["push_spread"].fillna(False))),
            }),
            "Total": pd.DataFrame({
                "season": era["season"],
                "p_mod": era["p_over_modelo"],
                "p_mer": po / (po + pu),
                "y": inst.flot(era["over"]),
            }),
            "Moneyline": pd.DataFrame({
                "season": era["season"],
                "p_mod": p_ml_mod,
                "p_mer": era["prob_local_sin_vig"],
                "y": inst.flot(era["gano_local"].mask(era["empate"].fillna(False))),
            }),
        }

        inst.linea("1. UNIVERSO (era 2006+, convención estricta del instrumento)")
        filas_u = []
        universos = {}
        for nombre, crudo in crudos.items():
            completo = crudo.dropna().reset_index(drop=True)
            universos[nombre] = completo
            prev = crudo[(crudo["season"] >= 2014) & (crudo["season"] <= 2025)]
            esperables = int((prev["p_mod"].notna() & prev["y"].notna()).sum())
            sin_cuota = int((prev["p_mod"].notna() & prev["y"].notna()
                             & prev["p_mer"].isna()).sum())
            filas_u.append([
                nombre,
                str(len(completo)),
                str(int((completo["season"] <= 2013).sum())),
                str(int(((completo["season"] >= 2014) & (completo["season"] <= 2025)).sum())),
                f"{sin_cuota} de {esperables}",
                str(int((completo["season"] == 2026).sum())),
            ])
        print(inst.tabla(["Mercado", "n universo", "ajuste inicial ≤2013",
                          "eval 2014–2025", "sin cuota en eval", "2026 (info)"], filas_u))
        print("\nPuertas pre-registradas: G1 ΔBrier≤−0.001 y IC95% sup.<0 · G2 ΔLogLoss≤−0.001 y IC95% sup.<0 ·")
        print("G3 cobertura≥98% · G5 mejora en ≥⌈2/3⌉ de temporadas evaluadas (y ≥5 temporadas) ·")
        print("desempate entre aprobados: mejor ΔBrier; a ≤0.0001, menos parámetros (C1 antes que D; D antes que C2).")

        # ------------------------------------------------------------------
        # 2. Evaluación walk-forward por mercado
        # ------------------------------------------------------------------
        inst.linea("2. RESULTADOS POR MERCADO (walk-forward; Δ pareado con IC95%)")
        resultados = {}
        for nombre, frame in universos.items():
            evaluados = frame[(frame["season"] >= 2014) & (frame["season"] <= 2025)] \
                .reset_index(drop=True)
            seasons = evaluados["season"].to_numpy()
            y = evaluados["y"].to_numpy()
            n_eval = len(evaluados)

            preds = {c: np.full(n_eval, np.nan) for c in ("A", "B", "C1", "C2", "D")}
            preds["A"] = evaluados["p_mod"].to_numpy()
            preds["B"] = evaluados["p_mer"].to_numpy()
            temporadas_iso = []
            for s in TEMPORADAS_EVAL:
                tr = frame[frame["season"] < s]
                te = frame[frame["season"] == s]
                idx = seasons == s
                if not idx.any() or len(tr) < 100 or not len(te):
                    continue
                beta1 = ajustar_logistica(logit(tr["p_mod"]), tr["y"].to_numpy())
                preds["C1"][idx] = sigmoide(beta1[0] + beta1[1] * logit(te["p_mod"].to_numpy()))
                if len(tr) >= MIN_AJUSTE_ISOTONA:
                    f_iso = ajustar_isotona(tr["p_mod"].to_numpy(), tr["y"].to_numpy())
                    preds["C2"][idx] = f_iso(te["p_mod"].to_numpy())
                    temporadas_iso.append(s)
                X_tr = np.column_stack([logit(tr["p_mod"]), logit(tr["p_mer"])])
                betaD = ajustar_logistica(X_tr, tr["y"].to_numpy())
                X_te = np.column_stack([logit(te["p_mod"]), logit(te["p_mer"])])
                preds["D"][idx] = sigmoide(betaD[0] + X_te @ betaD[1:])

            ventanas = {c: np.ones(n_eval, dtype=bool) for c in preds}
            if temporadas_iso:
                ventanas["C2"] = np.isin(seasons, temporadas_iso)
            else:
                ventanas["C2"] = np.zeros(n_eval, dtype=bool)

            res_cand = {}
            filas_cal = []
            for c in ("A", "B", "C1", "C2", "D"):
                p = preds[c]
                n_, b_, ll_ = metricas(p, y)
                if c == "A":
                    d_b = lo_b = hi_b = d_l = lo_l = hi_l = 0.0
                else:
                    d_b, lo_b, hi_b = delta_ic(gen, p, preds["A"], y, "brier")
                    d_l, lo_l, hi_l = delta_ic(gen, p, preds["A"], y, "ll")
                ventana = ventanas[c]
                cobertura = float(np.mean(~np.isnan(p[ventana]))) if ventana.any() else 0.0
                mejor, tot = consistencia(p, preds["A"], y, seasons)
                res_cand[c] = {
                    "n": n_, "b": b_, "ll": ll_,
                    "d_b": d_b, "lo_b": lo_b, "hi_b": hi_b,
                    "d_l": d_l, "lo_l": lo_l, "hi_l": hi_l,
                    "cobertura": cobertura, "mejor": mejor, "tot": tot,
                }
                if n_ == 0:
                    continue
                if c == "A":
                    filas_cal.append([ETIQUETAS[c], str(n_), f"{b_:.4f}", f"{ll_:.4f}",
                                      "—", "—", "—", "—"])
                else:
                    filas_cal.append([
                        ETIQUETAS[c], str(n_), f"{b_:.4f}", f"{ll_:.4f}",
                        f"{d_b:+.4f}", f"[{lo_b:+.4f}, {hi_b:+.4f}]",
                        f"{d_l:+.4f}", f"[{lo_l:+.4f}, {hi_l:+.4f}]",
                    ])

            print(f"\n--- Mercado: {nombre} ---")
            print(inst.tabla(["Candidato", "n", "Brier", "LogLoss", "ΔBrier",
                              "IC95% ΔBrier", "ΔLL", "IC95% ΔLL"], filas_cal))

            filas_puerta = []
            aprobados = []
            for c in ("C1", "C2", "D"):
                r = res_cand[c]
                if r["n"] == 0:
                    continue
                g1 = (r["d_b"] <= UMBRAL) and (r["hi_b"] < 0)
                g2 = (r["d_l"] <= UMBRAL) and (r["hi_l"] < 0)
                g3 = r["cobertura"] >= 0.98
                g5 = (r["tot"] >= 5) and (r["mejor"] >= math.ceil(2 * r["tot"] / 3))
                ok = g1 and g2 and g3 and g5
                r["puertas"] = {"G1": g1, "G2": g2, "G3": g3, "G5": g5}
                if ok:
                    aprobados.append(c)
                filas_puerta.append([
                    ETIQUETAS[c], f"{100 * r['cobertura']:.1f}%",
                    f"{r['mejor']}/{r['tot']}",
                    "sí" if g1 else "no", "sí" if g2 else "no",
                    "sí" if g3 else "no", "sí" if g5 else "no",
                    "ADOPTABLE" if ok else "no pasa",
                ])
            print(inst.tabla(["Candidato", "Cobertura", "Temp. mejor", "G1", "G2", "G3", "G5",
                              "Veredicto"], filas_puerta))

            # Regla de selección pre-registrada entre aprobados:
            elegido = None
            if aprobados:
                mejor_d = min(res_cand[c]["d_b"] for c in aprobados)
                finalistas = [c for c in aprobados if res_cand[c]["d_b"] <= mejor_d + 0.0001]
                finalistas.sort(key=lambda c: (PARAMETROS[c], res_cand[c]["d_b"], c))
                elegido = finalistas[0]

            # D vs B (¿el modelo añade sobre el mercado?) — informativa
            d_db, lo_db, hi_db = delta_ic(gen, preds["D"], preds["B"], y, "brier")
            if hi_db < 0:
                nota_db = "D es mejor que el mercado (IC95% < 0)"
            elif lo_db > 0:
                nota_db = "D es peor que el mercado (IC95% > 0)"
            else:
                nota_db = "sin evidencia de que el modelo añada sobre el mercado (IC95% contiene 0)"
            print(f"D vs B (ΔBrier = D − mercado): {d_db:+.4f} IC95% [{lo_db:+.4f}, {hi_db:+.4f}] → {nota_db}")

            resultados[nombre] = {"cand": res_cand, "elegido": elegido, "aprobados": aprobados}

            # verificación: A reproduce datos.brier_score
            b_prod = float(datos.brier_score(pd.Series(preds["A"]), pd.Series(y)))
            inst.chk_bool(checks, f"A reproduce datos.brier_score · {nombre}",
                          abs(b_prod - res_cand["A"]["b"]) <= 1e-12,
                          f"|{b_prod:.10f} − {res_cand['A']['b']:.10f}| ≤ 1e-12")
            for c in ("A", "C1", "D"):
                inst.chk_bool(checks, f"cobertura {c} · {nombre}",
                              abs(res_cand[c]["cobertura"] - 1.0) < 1e-12,
                              f"{100 * res_cand[c]['cobertura']:.1f}%")

            # Información de la última ventana (ajuste hasta 2025) y de 2026
            tr26 = frame[frame["season"] < 2026]
            te26 = frame[frame["season"] == 2026]
            beta1 = ajustar_logistica(logit(tr26["p_mod"]), tr26["y"].to_numpy())
            X26 = np.column_stack([logit(tr26["p_mod"]), logit(tr26["p_mer"])])
            betaD = ajustar_logistica(X26, tr26["y"].to_numpy())
            inst.chk_bool(checks, f"Platt converge · {nombre}",
                          np.all(np.isfinite(beta1)), f"a={beta1[0]:+.3f} b={beta1[1]:.3f}")
            print(f"Parámetros última ventana (2006–2025): Platt a={beta1[0]:+.3f} b={beta1[1]:.3f}"
                  f" | Mezcla a={betaD[0]:+.3f} b1={betaD[1]:.3f} b2={betaD[2]:.3f}")
            if len(te26):
                p26 = {
                    "A": te26["p_mod"].to_numpy(),
                    "B": te26["p_mer"].to_numpy(),
                    "C1": sigmoide(beta1[0] + beta1[1] * logit(te26["p_mod"].to_numpy())),
                    "D": sigmoide(betaD[0] + np.column_stack([
                        logit(te26["p_mod"]), logit(te26["p_mer"])]) @ betaD[1:]),
                }
                if len(tr26) >= MIN_AJUSTE_ISOTONA:
                    f_iso = ajustar_isotona(tr26["p_mod"].to_numpy(), tr26["y"].to_numpy())
                    p26["C2"] = f_iso(te26["p_mod"].to_numpy())
                y26 = te26["y"].to_numpy()
                filas_26 = []
                for c in ("A", "B", "C1", "C2", "D"):
                    if c not in p26:
                        continue
                    n26, b26, _ = metricas(p26[c], y26)
                    d26 = (float(np.mean(brier_filas(p26[c], y26)
                                         - brier_filas(p26["A"], y26)))
                           if c != "A" else 0.0)
                    filas_26.append([ETIQUETAS[c], str(n26), f"{b26:.4f}",
                                     "—" if c == "A" else f"{d26:+.4f}"])
                print(f"2026 (informativo, n pequeño):")
                print(inst.tabla(["Candidato", "n", "Brier", "ΔBrier vs A"], filas_26))

        # ------------------------------------------------------------------
        # 3. Verificación interna
        # ------------------------------------------------------------------
        inst.linea("3. VERIFICACIÓN INTERNA")
        for nombre, frame in universos.items():
            n13 = int((frame["season"] <= 2013).sum())
            n_eval = int(((frame["season"] >= 2014) & (frame["season"] <= 2025)).sum())
            n26 = int((frame["season"] == 2026).sum())
            inst.chk_bool(checks, f"partición por temporadas · {nombre}",
                          n13 + n_eval + n26 == len(frame),
                          f"{n13}+{n_eval}+{n26}={len(frame)}")
        inst.chk_bool(checks, "sin intentos de red", len(guardia.intentos) == 0,
                      f"{len(guardia.intentos)} intentos")
        segundos = time.perf_counter() - inicio
        inst.chk_bool(checks, "tiempo de ejecución < 10 s", segundos < 10.0,
                      f"{segundos:.2f} s (dentro del cálculo)")

    # ------------------------------------------------------------------
    # 4. Resumen de comprobaciones y veredicto
    # ------------------------------------------------------------------
    print()
    for nombre_chk, ok, detalle in checks:
        estado = "OK   " if ok else "FALLO"
        print(f"  [{estado}] {nombre_chk:<44s} {detalle}")

    inst.linea("4. VEREDICTO F4 (puertas pre-registradas)")
    for nombre, r in resultados.items():
        elegido = r["elegido"]
        if elegido:
            m = r["cand"][elegido]
            print(f"  {nombre}: ADOPTAR {ETIQUETAS[elegido]} — "
                  f"ΔBrier {m['d_b']:+.4f} IC95% [{m['lo_b']:+.4f}, {m['hi_b']:+.4f}]; "
                  f"ΔLogLoss {m['d_l']:+.4f} IC95% [{m['lo_l']:+.4f}, {m['hi_l']:+.4f}]; "
                  f"cobertura {100 * m['cobertura']:.1f}%; temporadas mejor {m['mejor']}/{m['tot']}")
        else:
            print(f"  {nombre}: ningún candidato pasa las puertas → se conserva el modelo "
                  f"crudo (A) y queda documentado el resultado negativo.")
    print("\nRecordatorio: 2014–2025 es retrospectivo y está contaminado en grado variable;")
    print("la adopción real (cableado en la app) será un bloque aparte con sus pruebas.")
    print(f"Tiempo total: {time.perf_counter() - inicio:.2f} s. Ningún archivo del proyecto fue escrito.")

    fallos = [n for n, ok, _ in checks if not ok]
    if fallos:
        print(f"\nVEREDICTO: {len(fallos)}/{len(checks)} comprobaciones internas FALLARON — "
              f"no usar estos resultados sin investigar:")
        for n in fallos:
            print(f"   - {n}")
        return 1
    print(f"Comprobaciones internas: {len(checks)}/{len(checks)} OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
