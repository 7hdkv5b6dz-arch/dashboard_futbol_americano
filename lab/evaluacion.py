#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Instrumento de evaluación v3 — dashboard_futbol_americano.

QUÉ ES
------
La herramienta ÚNICA para medir el modelo srs-v2 y compararlo con el mercado:
mismos partidos, mismas reglas de push, segmentos separados (temporada
regular / postemporada, con / sin temporada en curso) e incertidumbre
estadística (bootstrap). Es el suelo sobre el que se apoyan las fases
siguientes (calibración, EV, variables nuevas), para que ninguna comparación
vuelva a hacerse entre conjuntos de partidos distintos.

GARANTÍAS
---------
- SOLO LECTURA: no escribe el registro ni ningún archivo del proyecto.
- SIN RED: bloquea sockets durante todo el cálculo; usa la caché local.
- DETERMINISTA: bootstrap con semilla fija; dos ejecuciones dan lo mismo
  (salvo la línea de tiempo de ejecución).
- AUTOVERIFICABLE: reproduce la línea base congelada del 16/10/2026
  (laboratorio de auditoría, salida_base_srs_v2.txt) con tolerancias de
  medio dígito impreso, y devuelve código de salida 1 si alguna
  comprobación falla. Si falla, NO se debe usar para decidir.

USO
---
    cd dashboard_futbol_americano
    .venv/bin/python -B lab/evaluacion.py

CONVENIOS DE MEDICIÓN (fijados en la auditoría del 16/10/2026)
--------------------------------------------------------------
- Era de evaluación: temporada 2006+ (antes de 2006 no hay cuotas reales).
- Conjunto ESTRICTO para comparar modelo vs mercado: partidos con pronóstico
  del modelo Y probabilidad de mercado Y resultado decidido; push (spread /
  total) y empate (moneyline) FUERA para los dos lados.
- dBrier = Brier(modelo) − Brier(mercado) sobre los MISMOS partidos:
  > 0 ⇒ el modelo es peor. IC95% por bootstrap pareado (semilla fija).
- La convención del reporte anterior (push contado como 0 en spread y
  empate como 0 en moneyline) se imprime aparte como sensibilidad, para
  no perder la trazabilidad de por qué cambian los números.
- Los ROI de picks usan la cuota real del CSV; si falta, −110 (igual que
  la app). El IC95% del ROI es bootstrap de la ganancia por $1.
"""

import math
import socket
import sys
import time
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROYECTO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROYECTO))
import datos  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)
pd.set_option("display.width", 160)

SEMILLA_BOOTSTRAP = 20261016
N_BOOTSTRAP = 2000

# ---------------------------------------------------------------------------
# Valores congelados de la línea base srs-v2 (salida_base_srs_v2.txt, 16/10/2026).
# Tolerancias: medio dígito de lo impreso (Brier/LogLoss 4 dec., % 1 dec., t 2
# dec.). Los conteos (n, push) se exigen exactos.
# ---------------------------------------------------------------------------
ESPERADO = {
    "sigma_margen_ultimo": 13.35,
    "sigma_total_ultimo": 13.77,
    "era_n": 5511,
    "picks": {
        "Spread (umbral 2.0)": {"n": 3230, "push": 87, "acierto": 50.7, "roi": -1.4, "t": -0.83},
        "Total (umbral 2.0)": {"n": 3207, "push": 40, "acierto": 51.4, "roi": -0.1, "t": -0.04},
        "Moneyline (umbral 4pp)": {"n": 3858, "push": 8, "acierto": 37.3, "roi": -4.8, "t": -2.09},
    },
    "cuota_real": {"spread_n": 3142, "spread_roi": -1.5, "total_n": 3131, "total_roi": 0.4},
    "ml_picks_2006": 141,
    "ml_picks_2007": 217,
    "brier_juegos": {
        "spread_modelo": (5511, 0.2607, 0.7163),
        "spread_mercado": (5375, 0.2501, 0.6933),
        "total_modelo": (5432, 0.2596, 0.7139),
        "total_mercado": (5296, 0.2501, 0.6934),
        "ml_modelo": (5511, 0.2254, 0.6417),
        "ml_mercado": (5375, 0.2117, 0.6108),
    },
    "brier_picks": {
        "spread_modelo": (3143, 0.2660, 0.7283),
        "spread_mercado": (3058, 0.2499, 0.6930),
        "total_modelo": (3167, 0.2657, 0.7273),
        "total_mercado": (3092, 0.2502, 0.6935),
        "ml_modelo": (3850, 0.2270, 0.6453),
        "ml_mercado": (3850, 0.2081, 0.6030),
    },
}
TOL_BRIER = 6e-5   # medio dígito de 4 decimales
TOL_PCT = 0.055    # medio dígito de 1 decimal
TOL_T = 0.006      # medio dígito de 2 decimales


# ---------------------------------------------------------------------------
# Utilidades de presentación
# ---------------------------------------------------------------------------
def linea(titulo):
    print("\n" + "=" * 78)
    print(titulo)
    print("=" * 78)


def tabla(columnas, filas):
    """Tabla ASCII determinista (primera columna a la izquierda)."""
    filas = [[str(c) for c in fila] for fila in filas]
    anchos = []
    for i, col in enumerate(columnas):
        anchos.append(max([len(str(col))] + [len(f[i]) for f in filas]))
    def fmt(fila):
        partes = [
            (v.ljust(a) if i == 0 else v.rjust(a))
            for i, (v, a) in enumerate(zip(fila, anchos))
        ]
        return "  ".join(partes)
    salida = [fmt(list(columnas)), "  ".join("-" * a for a in anchos)]
    salida += [fmt(f) for f in filas]
    return "\n".join(salida)


# ---------------------------------------------------------------------------
# Copias congeladas del laboratorio (idénticas a base_actual.py, que a su vez
# copia app.py y datos.py). Se usan como referencia de reproducción; las
# funciones de producción se comparan aparte en la verificación interna.
# ---------------------------------------------------------------------------
def cuota_a_pago(cuotas):
    """Copia de app.py::cuota_a_pago (sin cuota → −110)."""
    c = pd.to_numeric(cuotas, errors="coerce").fillna(-110)
    return (c / 100).where(c > 0, 100 / -c)


def ganancia_apuesta(cuotas, gano):
    """Copia de app.py::ganancia_apuesta."""
    gano_f = pd.Series(gano, index=pd.Series(cuotas).index).astype("boolean").fillna(False)
    return cuota_a_pago(cuotas).where(gano_f.astype(bool), -1.0)


def evaluar_spread(df, umbral=2.0):
    """Copia literal de app.py::evaluar_spread + probabilidad del lado."""
    d = df[df["margen_modelo"].notna() & df["spread_line"].notna()].copy()
    d["edge"] = d["margen_modelo"] - d["spread_line"]
    d = d[d["edge"].abs() >= umbral].copy()
    d["al_local"] = d["edge"] > 0
    d["pick"] = d["home_team"].where(d["al_local"], d["away_team"])
    d["linea_pick"] = np.where(d["al_local"], -d["spread_line"], d["spread_line"])
    d["gano"] = d["cubre_local"].where(d["al_local"], d["cubre_visitante"])
    d["gano"] = d["gano"].mask(d["push_spread"].fillna(False))
    d["cuota"] = d["home_spread_odds"].where(d["al_local"], d["away_spread_odds"])
    d["ganancia"] = ganancia_apuesta(d["cuota"], d["gano"]).where(d["gano"].notna(), 0.0)
    p_local = datos.probabilidad_supera(
        d["margen_modelo"], d["spread_line"], d["sigma_modelo"])
    d["prob_modelo"] = p_local.where(d["al_local"], 1.0 - p_local)
    pm = d["prob_local_spread_sin_vig"]
    d["prob_mercado"] = pm.where(d["al_local"], 1.0 - pm)
    return d


def evaluar_totales(df, umbral=2.0):
    """Copia literal de app.py::evaluar_totales + probabilidad del lado."""
    d = df[df["total_modelo"].notna() & df["total_line"].notna()].copy()
    d["edge"] = d["total_modelo"] - d["total_line"]
    d = d[d["edge"].abs() >= umbral].copy()
    d["al_over"] = d["edge"] > 0
    d["pick"] = np.where(d["al_over"], "Más de " + d["total_line"].astype(str),
                         "Menos de " + d["total_line"].astype(str))
    d["gano"] = d["over"].where(d["al_over"], ~d["over"])
    d["cuota"] = d["over_odds"].where(d["al_over"], d["under_odds"])
    d["ganancia"] = ganancia_apuesta(d["cuota"], d["gano"]).where(d["gano"].notna(), 0.0)
    p_over = datos.probabilidad_supera(
        d["total_modelo"], d["total_line"], d["sigma_total_modelo"])
    d["prob_modelo"] = p_over.where(d["al_over"], 1.0 - p_over)
    po = datos._prob_implicita(d["over_odds"])
    pu = datos._prob_implicita(d["under_odds"])
    p_merc = po / (po + pu)
    d["prob_mercado"] = p_merc.where(d["al_over"], 1.0 - p_merc)
    return d


def sigma_por_jornada(jugados_df, residuos, ventana=500, minimo=100):
    """Réplica del sigma congelado por jornada (semántica de datos.py)."""
    d = pd.DataFrame({
        "season": jugados_df["season"].to_numpy(),
        "week": jugados_df["week"].to_numpy(),
        "r": pd.Series(residuos).to_numpy(),
    })
    previos, sigmas = [], []
    for _, g in d.groupby(["season", "week"], sort=False):
        sig = (float(np.std(np.asarray(previos[-ventana:], dtype=float), ddof=1))
               if len(previos) >= minimo else float("nan"))
        sigmas.extend([sig] * len(g))
        previos.extend(g["r"].dropna().astype(float).tolist())
    return pd.Series(sigmas)


def _brier_ll(prob, y):
    """Réplica exacta del cálculo Brier/LogLoss del laboratorio congelado."""
    p = pd.to_numeric(pd.Series(prob), errors="coerce")
    y = pd.to_numeric(pd.Series(y), errors="coerce")
    m = p.notna() & y.notna()
    p, y = p[m].astype(float), y[m].astype(float)
    if not len(p):
        return 0, float("nan"), float("nan")
    b = float(((p - y) ** 2).mean())
    e = 1e-12
    ll = float(-(y * np.log(p.clip(e, 1 - e))
                 + (1 - y) * np.log((1 - p).clip(e, 1 - e))).mean())
    return int(len(p)), b, ll


def flot(serie):
    """Serie booleana (posiblemente con NA) → float 0.0 / 1.0 / NaN."""
    return pd.Series(serie).astype("Float64").astype(float)


def resumen_seg(picks):
    """n, push, acierto (%) y ROI (%) de un conjunto de picks."""
    g = picks["gano"]
    n = len(picks)
    push = int(g.isna().sum())
    dec = g.dropna().astype(float)
    acierto = float(100 * dec.mean()) if len(dec) else float("nan")
    roi = float(100 * picks["ganancia"].astype(float).mean()) if n else float("nan")
    return {"n": n, "push": push, "acierto": acierto, "roi": roi}


def met(picks, nombre):
    """Imprime estilo del reporte congelado y devuelve las métricas."""
    r = resumen_seg(picks)
    n, push, acierto, roi = r["n"], r["push"], r["acierto"], r["roi"]
    dec = picks["gano"].dropna().astype(float)
    se_pct = (float(100 * math.sqrt((acierto / 100) * (1 - acierto / 100) / len(dec)))
              if len(dec) else float("nan"))
    gan = picks["ganancia"].astype(float)
    se_roi = float(100 * gan.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    t = float(roi / se_roi) if se_roi else float("nan")
    print(f"  {nombre:24s} n={n:5d} push={push:3d} | acierto={acierto:5.1f}% ±{se_pct:4.1f} | "
          f"ROI={roi:+6.1f}% ±{se_roi:4.1f} (t={t:+.2f})")
    return {"n": n, "push": push, "acierto": acierto, "roi": roi, "t": t}


# ---------------------------------------------------------------------------
# Herramientas nuevas (el aporte del instrumento v3)
# ---------------------------------------------------------------------------
def ic_media(gen, valores, n_boot=N_BOOTSTRAP):
    """Media e IC95% bootstrap (percentiles) de una serie. Semilla fija."""
    v = np.asarray(pd.Series(valores).dropna(), dtype=float)
    if v.size == 0:
        return float("nan"), float("nan"), float("nan")
    medias = np.empty(n_boot)
    for i in range(0, n_boot, 500):
        bloque = min(500, n_boot - i)
        idx = gen.integers(0, v.size, size=(bloque, v.size))
        medias[i:i + bloque] = v[idx].mean(axis=1)
    lo, hi = np.percentile(medias, [2.5, 97.5])
    return float(v.mean()), float(lo), float(hi)


def comparar_par(gen, p_mod, p_mer, y):
    """Brier/LogLoss modelo vs mercado sobre los MISMOS partidos + IC95% del Δ.

    Δ = Brier(modelo) − Brier(mercado), pareado por partido (> 0 ⇒ peor el
    modelo). También devuelve la verificación contra las funciones de
    producción de datos.py (brier_score / log_loss).
    """
    m = p_mod.notna() & p_mer.notna() & y.notna()
    pm = pd.Series(p_mod[m], dtype="float64")
    pk = pd.Series(p_mer[m], dtype="float64")
    yy = pd.Series(y[m], dtype="float64")
    n, b_mod, ll_mod = _brier_ll(pm, yy)
    _, b_mer, ll_mer = _brier_ll(pk, yy)
    difs = (pm - yy) ** 2 - (pk - yy) ** 2
    media, lo, hi = ic_media(gen, difs)
    return {
        "n": int(m.sum()),
        "b_mod": b_mod, "ll_mod": ll_mod,
        "b_mer": b_mer, "ll_mer": ll_mer,
        "delta": media, "lo": lo, "hi": hi,
        "b_prod": float(datos.brier_score(pm, yy)),
        "ll_prod": float(datos.log_loss(pm, yy)),
    }


def delta_punto(p_mod, p_mer, y):
    """Δ Brier punto (sin bootstrap) sobre el conjunto válido."""
    m = p_mod.notna() & p_mer.notna() & y.notna()
    pm = pd.Series(p_mod[m], dtype="float64")
    pk = pd.Series(p_mer[m], dtype="float64")
    yy = pd.Series(y[m], dtype="float64")
    return int(m.sum()), float((((pm - yy) ** 2) - ((pk - yy) ** 2)).mean())


def veredicto_delta(lo, hi):
    if lo > 0:
        return "el MODELO es peor (IC95% entero > 0)"
    if hi < 0:
        return "el MODELO es mejor (IC95% entero < 0)"
    return "sin diferencia clara (IC95% contiene 0)"


def veredicto_roi(lo, hi):
    if lo > 0:
        return "IC95% > 0 (ganancia posible)"
    if hi < 0:
        return "IC95% < 0 (pérdida con evidencia)"
    return "sin evidencia de rentabilidad (IC95% contiene 0)"


class GuardiaRed:
    """Bloquea (y cuenta) cualquier intento de conexión durante el cálculo."""

    def __init__(self):
        self.intentos = []
        self._original = None

    def __enter__(self):
        self._original = socket.socket.connect
        intentos = self.intentos

        def negar(sock, direccion, *args, **kwargs):
            intentos.append(direccion)
            raise RuntimeError(f"Red bloqueada por el instrumento: {direccion}")

        socket.socket.connect = negar
        return self

    def __exit__(self, *exc):
        socket.socket.connect = self._original
        return False


def chk_int(checks, nombre, actual, esperado):
    ok = int(actual) == int(esperado)
    checks.append((nombre, ok, f"{int(actual)}" if ok else f"{int(actual)} ≠ {int(esperado)}"))


def chk_num(checks, nombre, actual, esperado, tol, fmt="{:.2f}"):
    ok = abs(float(actual) - float(esperado)) <= tol
    detalle = fmt.format(actual) if ok else f"{fmt.format(actual)} ≠ {fmt.format(esperado)} (±{tol:g})"
    checks.append((nombre, ok, detalle))


def chk_bool(checks, nombre, ok, detalle):
    checks.append((nombre, bool(ok), detalle))


# ---------------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------------
def main():
    inicio = time.perf_counter()
    checks = []
    guardia = GuardiaRed()
    gen = np.random.default_rng(SEMILLA_BOOTSTRAP)

    with guardia:
        # ------------------------------------------------------------------
        # 1. CARGA, SIGMA Y ERA
        # ------------------------------------------------------------------
        linea("INSTRUMENTO DE EVALUACIÓN v3 — modelo srs-v2 — era 2006+")
        print(f"Fecha: {date.today().isoformat()} | semilla bootstrap: {SEMILLA_BOOTSTRAP} "
              f"| remuestreos: {N_BOOTSTRAP}")
        print("Solo lectura · sin red · determinista (salvo la línea de tiempo)")

        linea("1. CARGA, SIGMA Y ERA (sanidad)")
        calendario = datos.cargar_calendario()
        print(f"Partidos: {len(calendario)} | jugados: {int(calendario['jugado'].sum())} | "
              f"pendientes: {int((~calendario['jugado']).sum())} | "
              f"temporadas: {int(calendario['season'].min())}–{int(calendario['season'].max())}")
        hist = datos.pronosticos_historicos(calendario).reset_index(drop=True)

        sig_rep = sigma_por_jornada(hist, hist["margen"] - hist["margen_modelo"])
        sig_rep_t = sigma_por_jornada(hist, hist["total_puntos"] - hist["total_modelo"])
        dif_sig = float((sig_rep - hist["sigma_modelo"]).abs().max())
        dif_sig_t = float((sig_rep_t - hist["sigma_total_modelo"]).abs().max())
        print(f"max |sigma réplica − sigma datos.py| = {dif_sig:.2e} (margen) | {dif_sig_t:.2e} (total)")
        s_ok = hist["sigma_modelo"].dropna()
        s_tot = hist["sigma_total_modelo"].dropna()
        print(f"sigma margen (último) = {s_ok.iloc[-1]:.2f} | sigma total (último) = {s_tot.iloc[-1]:.2f}")

        era = hist[hist["season"] >= 2006].reset_index(drop=True)
        print(f"Era de evaluación (2006+): {len(era)} partidos jugados")

        era["p_local_modelo"] = datos.probabilidad_supera(
            era["margen_modelo"], era["spread_line"], era["sigma_modelo"])
        era["p_over_modelo"] = datos.probabilidad_supera(
            era["total_modelo"], era["total_line"], era["sigma_total_modelo"])

        # ------------------------------------------------------------------
        # 2. REPRODUCCIÓN DE LA LÍNEA BASE CONGELADA
        # ------------------------------------------------------------------
        linea("2. REPRODUCCIÓN DE LA LÍNEA BASE (picks por defecto y Brier)")
        print("Configuración por defecto: spread/total umbral 2.0 · moneyline umbral 4pp\n")
        ps = evaluar_spread(era, 2.0)
        pt = evaluar_totales(era, 2.0)
        pm = datos.evaluar_picks_ml(era, umbral=0.04).copy()
        m_ps = met(ps, "Spread (umbral 2.0)")
        m_pt = met(pt, "Total (umbral 2.0)")
        m_pm = met(pm, "Moneyline (umbral 4pp)")

        con_sp = ps[ps["cuota"].notna()]
        con_to = pt[pt["cuota"].notna()]
        roi_sp_real = float(100 * con_sp["ganancia"].mean())
        roi_to_real = float(100 * con_to["ganancia"].mean())
        print(f"  Spread: cuota real en {len(con_sp)}/{len(ps)} picks "
              f"({100 * len(con_sp) / len(ps):.1f}%); ROI solo con cuota real = {roi_sp_real:+.1f}%")
        print(f"  Total: cuota real en {len(con_to)}/{len(pt)} picks "
              f"({100 * len(con_to) / len(pt):.1f}%); ROI solo con cuota real = {roi_to_real:+.1f}%")
        n_ml_2006 = int((pm["season"] == 2006).sum())
        n_ml_2007 = int((pm["season"] == 2007).sum())
        print(f"  Moneyline: picks 2006={n_ml_2006} (2006 casi sin cuotas ML), 2007={n_ml_2007}")

        # Probabilidades (perspectiva local / over) para todos los evaluables:
        p_sp_mod = era["p_local_modelo"].where(era["margen_modelo"].notna())
        p_sp_mer = era["prob_local_spread_sin_vig"]
        po = datos._prob_implicita(era["over_odds"])
        pu = datos._prob_implicita(era["under_odds"])
        p_to_mer = po / (po + pu)
        p_to_mod = era["p_over_modelo"]
        p_ml_mod = datos.probabilidades_ml(era["margen_modelo"], era["sigma_modelo"])[0]
        p_ml_mer = era["prob_local_sin_vig"]

        # Convención del reporte anterior (para reproducirlo tal cual):
        y_sp_leg = flot(era["cubre_local"])   # push cuenta como 0
        y_to_leg = flot(era["over"])          # push ya excluido
        y_ml_leg = flot(era["gano_local"])    # empate cuenta como 0

        print("\nBrier/LogLoss — todos los evaluables (convención del reporte):")
        filas_rep = []
        brier_juegos = {}
        for clave, p, y in (
            ("spread_modelo", p_sp_mod, y_sp_leg),
            ("spread_mercado", p_sp_mer, y_sp_leg),
            ("total_modelo", p_to_mod, y_to_leg),
            ("total_mercado", p_to_mer, y_to_leg),
            ("ml_modelo", p_ml_mod, y_ml_leg),
            ("ml_mercado", p_ml_mer, y_ml_leg),
        ):
            n_, b_, ll_ = _brier_ll(p, y)
            brier_juegos[clave] = (n_, b_, ll_)
            filas_rep.append([clave.replace("_", " · "), str(n_), f"{b_:.4f}", f"{ll_:.4f}"])
        print(tabla(["conjunto", "n", "Brier", "LogLoss"], filas_rep))

        print("\nBrier/LogLoss — sobre los picks emitidos (prob. del lado apostado):")
        filas_rep2 = []
        brier_picks = {}
        for clave, p, y in (
            ("spread_modelo", ps["prob_modelo"], ps["gano"]),
            ("spread_mercado", ps["prob_mercado"], ps["gano"]),
            ("total_modelo", pt["prob_modelo"], pt["gano"]),
            ("total_mercado", pt["prob_mercado"], pt["gano"]),
            ("ml_modelo", pm["prob_modelo"], pm["gano"]),
            ("ml_mercado", pm["prob_mercado"], pm["gano"]),
        ):
            n_, b_, ll_ = _brier_ll(p, y)
            brier_picks[clave] = (n_, b_, ll_)
            filas_rep2.append([clave.replace("_", " · "), str(n_), f"{b_:.4f}", f"{ll_:.4f}"])
        print(tabla(["conjunto", "n", "Brier", "LogLoss"], filas_rep2))

        # -------- Verificación contra los valores congelados --------
        print("\nVerificación contra la línea base congelada (16/10/2026):")
        chk_num(checks, "sigma margen réplica vs datos.py", dif_sig, 0.0, 0.0, fmt="{:.2e}")
        chk_num(checks, "sigma total réplica vs datos.py", dif_sig_t, 0.0, 0.0, fmt="{:.2e}")
        chk_num(checks, "sigma margen último", s_ok.iloc[-1], ESPERADO["sigma_margen_ultimo"], TOL_T, fmt="{:.2f}")
        chk_num(checks, "sigma total último", s_tot.iloc[-1], ESPERADO["sigma_total_ultimo"], TOL_T, fmt="{:.2f}")
        chk_int(checks, "era 2006+ (n partidos)", len(era), ESPERADO["era_n"])
        for nombre, m in (("Spread (umbral 2.0)", m_ps), ("Total (umbral 2.0)", m_pt),
                          ("Moneyline (umbral 4pp)", m_pm)):
            e = ESPERADO["picks"][nombre]
            chk_int(checks, f"picks {nombre} · n", m["n"], e["n"])
            chk_int(checks, f"picks {nombre} · push", m["push"], e["push"])
            chk_num(checks, f"picks {nombre} · acierto %", m["acierto"], e["acierto"], TOL_PCT, fmt="{:.1f}")
            chk_num(checks, f"picks {nombre} · ROI %", m["roi"], e["roi"], TOL_PCT, fmt="{:+.1f}")
            chk_num(checks, f"picks {nombre} · t del ROI", m["t"], e["t"], TOL_T, fmt="{:+.2f}")
        chk_int(checks, "spread · picks con cuota real", len(con_sp), ESPERADO["cuota_real"]["spread_n"])
        chk_num(checks, "spread · ROI solo cuota real %", roi_sp_real, ESPERADO["cuota_real"]["spread_roi"], TOL_PCT, fmt="{:+.1f}")
        chk_int(checks, "total · picks con cuota real", len(con_to), ESPERADO["cuota_real"]["total_n"])
        chk_num(checks, "total · ROI solo cuota real %", roi_to_real, ESPERADO["cuota_real"]["total_roi"], TOL_PCT, fmt="{:+.1f}")
        chk_int(checks, "moneyline · picks 2006", n_ml_2006, ESPERADO["ml_picks_2006"])
        chk_int(checks, "moneyline · picks 2007", n_ml_2007, ESPERADO["ml_picks_2007"])
        for clave, (n_e, b_e, ll_e) in ESPERADO["brier_juegos"].items():
            n_, b_, ll_ = brier_juegos[clave]
            chk_int(checks, f"Brier juegos {clave} · n", n_, n_e)
            chk_num(checks, f"Brier juegos {clave} · Brier", b_, b_e, TOL_BRIER, fmt="{:.4f}")
            chk_num(checks, f"Brier juegos {clave} · LogLoss", ll_, ll_e, TOL_BRIER, fmt="{:.4f}")
        for clave, (n_e, b_e, ll_e) in ESPERADO["brier_picks"].items():
            n_, b_, ll_ = brier_picks[clave]
            chk_int(checks, f"Brier picks {clave} · n", n_, n_e)
            chk_num(checks, f"Brier picks {clave} · Brier", b_, b_e, TOL_BRIER, fmt="{:.4f}")
            chk_num(checks, f"Brier picks {clave} · LogLoss", ll_, ll_e, TOL_BRIER, fmt="{:.4f}")
        n_ok_rep = sum(1 for _, ok, _ in checks if ok)
        print(f"  → {n_ok_rep}/{len(checks)} comprobaciones de reproducción OK")

        # ------------------------------------------------------------------
        # 3. MISMOS PARTIDOS: MODELO vs MERCADO (CONJUNTO ESTRICTO)
        # ------------------------------------------------------------------
        linea("3. MISMOS PARTIDOS — MODELO vs MERCADO (estricto, IC95% bootstrap)")
        print("Conjunto estricto: pronóstico del modelo + probabilidad de mercado +")
        print("resultado decidido; push y empates FUERA para ambos lados.")
        print("Δ = Brier(modelo) − Brier(mercado) sobre los MISMOS partidos; Δ>0 ⇒ peor el modelo.\n")

        y_sp_est = flot(era["cubre_local"].mask(era["push_spread"].fillna(False)))
        y_to_est = flot(era["over"])
        y_ml_est = flot(era["gano_local"].mask(era["empate"].fillna(False)))

        mercados = (
            ("Spread", p_sp_mod, p_sp_mer, y_sp_est, y_sp_leg),
            ("Total", p_to_mod, p_to_mer, y_to_est, None),
            ("Moneyline", p_ml_mod, p_ml_mer, y_ml_est, y_ml_leg),
        )
        filas3 = []
        res3 = {}
        for nombre, p_mod, p_mer, y_est, y_leg in mercados:
            r = comparar_par(gen, p_mod, p_mer, y_est)
            res3[nombre] = r
            filas3.append([
                nombre, str(r["n"]), f"{r['b_mod']:.4f}", f"{r['b_mer']:.4f}",
                f"{r['delta']:+.4f}", f"{r['ll_mod']:.4f}", f"{r['ll_mer']:.4f}",
                f"[{r['lo']:+.4f}, {r['hi']:+.4f}]", veredicto_delta(r["lo"], r["hi"]),
            ])
        print(tabla(["Mercado", "n", "Brier mod", "Brier mer", "Δ", "LL mod", "LL mer",
                     "IC95% Δ", "Veredicto"], filas3))

        print("\nSensibilidad a la convención del reporte anterior (push/empate = 0):")
        for nombre, p_mod, p_mer, _, y_leg in mercados:
            if y_leg is None:
                print(f"  {nombre}: convención idéntica (los push ya estaban fuera).")
                continue
            n_leg, d_leg = delta_punto(p_mod, p_mer, y_leg)
            print(f"  {nombre}: n={n_leg}, ΔBrier={d_leg:+.4f} "
                  f"(vs estricto n={res3[nombre]['n']}, Δ={res3[nombre]['delta']:+.4f})")

        # ------------------------------------------------------------------
        # 4. TEMPORADA REGULAR vs POSTEMPORADA
        # ------------------------------------------------------------------
        linea("4. TEMPORADA REGULAR vs POSTEMPORADA")
        reg = era[era["game_type"].eq("REG")]
        post = era[era["game_type"].ne("REG")]
        print(f"Partidos: regular {len(reg)} | postemporada {len(post)} "
              f"({100 * len(post) / len(era):.1f}% de la era)")

        filas4 = []
        res4 = {}
        for seg_nombre, seg in (("Regular", reg), ("Postemporada", post)):
            idx = seg.index
            for nombre, p_mod, p_mer, y_est, _ in mercados:
                r = comparar_par(gen, p_mod.loc[idx], p_mer.loc[idx], y_est.loc[idx])
                res4[(seg_nombre, nombre)] = r
                filas4.append([
                    seg_nombre, nombre, str(r["n"]), f"{r['b_mod']:.4f}", f"{r['b_mer']:.4f}",
                    f"{r['delta']:+.4f}", f"[{r['lo']:+.4f}, {r['hi']:+.4f}]",
                    veredicto_delta(r["lo"], r["hi"]),
                ])
        print("\nBrier estricto por segmento (mismos partidos dentro de cada uno):")
        print(tabla(["Segmento", "Mercado", "n", "Brier mod", "Brier mer", "Δ", "IC95% Δ", "Veredicto"],
                    filas4))

        print("\nPicks por segmento (n / push / acierto% / ROI%):")
        filas4p = []
        res4p = {}
        for seg_nombre in ("Regular", "Postemporada"):
            for nombre, picks in (("Spread", ps), ("Total", pt), ("Moneyline", pm)):
                mascara = picks["game_type"].eq("REG") if seg_nombre == "Regular" \
                    else picks["game_type"].ne("REG")
                r = resumen_seg(picks[mascara])
                res4p[(seg_nombre, nombre)] = r
                filas4p.append([seg_nombre, nombre, str(r["n"]), str(r["push"]),
                                f"{r['acierto']:.1f}", f"{r['roi']:+.1f}"])
        print(tabla(["Segmento", "Mercado", "n", "push", "acierto%", "ROI%"], filas4p))

        # ------------------------------------------------------------------
        # 5. CON Y SIN TEMPORADA EN CURSO (2026)
        # ------------------------------------------------------------------
        linea("5. CON Y SIN TEMPORADA EN CURSO (2026)")
        idx_prev = era.index[era["season"] != 2026]
        idx_26 = era.index[era["season"] == 2026]
        print(f"Partidos: ≤2025 {len(idx_prev)} | 2026 (en curso) {len(idx_26)} "
              "— 2026 es muestra mínima: solo informativo, no decide nada.")

        filas5 = []
        res5 = {}
        for nombre, p_mod, p_mer, y_est, _ in mercados:
            r_prev = comparar_par(gen, p_mod.loc[idx_prev], p_mer.loc[idx_prev], y_est.loc[idx_prev])
            n26, d26 = delta_punto(p_mod.loc[idx_26], p_mer.loc[idx_26], y_est.loc[idx_26])
            res5[nombre] = {"n_prev": r_prev["n"], "n26": n26}
            filas5.append([
                nombre, str(r_prev["n"]), f"{r_prev['delta']:+.4f}",
                f"[{r_prev['lo']:+.4f}, {r_prev['hi']:+.4f}]",
                str(n26), f"{d26:+.4f}" if n26 else "-",
            ])
        print("\nΔBrier estricto sin 2026 (con IC) y en 2026 (punto, informativo):")
        print(tabla(["Mercado", "n ≤2025", "Δ ≤2025", "IC95% ≤2025", "n 2026", "Δ 2026"], filas5))

        filas5p = []
        for nombre, picks in (("Spread 2.0", ps), ("Total 2.0", pt), ("Moneyline 4pp", pm)):
            r_todo = resumen_seg(picks)
            r_prev = resumen_seg(picks[picks["season"] != 2026])
            r_26 = resumen_seg(picks[picks["season"] == 2026])
            filas5p.append([
                nombre, str(r_todo["n"]), f"{r_todo['roi']:+.1f}",
                str(r_prev["n"]), f"{r_prev['roi']:+.1f}",
                str(r_26["n"]), f"{r_26['roi']:+.1f}",
            ])
        print("\nPicks: aporte de 2026 (ROI%):")
        print(tabla(["Estrategia", "n era", "ROI era", "n ≤2025", "ROI ≤2025", "n 2026", "ROI 2026"],
                    filas5p))

        # ------------------------------------------------------------------
        # 6. ROBUSTEZ DEL ROI (BOOTSTRAP)
        # ------------------------------------------------------------------
        linea("6. ROBUSTEZ DEL ROI (IC95% bootstrap de la ganancia por $1)")
        for nombre, picks in (("Spread 2.0", ps), ("Total 2.0", pt), ("Moneyline 4pp", pm)):
            media, lo, hi = ic_media(gen, picks["ganancia"])
            m = resumen_seg(picks)
            print(f"  {nombre:<16s} n={m['n']:5d}  ROI={media * 100:+6.1f}%  "
                  f"IC95% [{lo * 100:+6.1f}, {hi * 100:+6.1f}]  "
                  f"→ {veredicto_roi(lo, hi)}")

        # ------------------------------------------------------------------
        # 7. VERIFICACIÓN INTERNA
        # ------------------------------------------------------------------
        linea("7. VERIFICACIÓN INTERNA (particiones, réplica vs producción, red, tiempo)")
        # Particiones de partidos:
        chk_int(checks, "partición partidos REG+POST", len(reg) + len(post), len(era))
        # Particiones del conjunto estricto por mercado:
        for nombre in ("Spread", "Total", "Moneyline"):
            n_r = res4[("Regular", nombre)]["n"]
            n_p = res4[("Postemporada", nombre)]["n"]
            chk_bool(checks, f"partición estricta REG+POST · {nombre}",
                     n_r + n_p == res3[nombre]["n"],
                     f"{n_r}+{n_p}={res3[nombre]['n']}")
            n_a = res5[nombre]["n_prev"]
            n_b = res5[nombre]["n26"]
            chk_bool(checks, f"partición estricta ≤2025 + 2026 · {nombre}",
                     n_a + n_b == res3[nombre]["n"],
                     f"{n_a}+{n_b}={res3[nombre]['n']}")
        # Réplica del instrumento vs funciones de producción (datos.py):
        for nombre, r in res3.items():
            chk_bool(checks, f"réplica vs datos.brier_score · {nombre}",
                     abs(r["b_prod"] - r["b_mod"]) <= 1e-12,
                     f"|{r['b_prod']:.10f} − {r['b_mod']:.10f}| ≤ 1e-12")
            chk_bool(checks, f"réplica vs datos.log_loss · {nombre}",
                     abs(r["ll_prod"] - r["ll_mod"]) <= 1e-12,
                     f"|{r['ll_prod']:.10f} − {r['ll_mod']:.10f}| ≤ 1e-12")
        # Red y tiempo:
        chk_bool(checks, "sin intentos de red", len(guardia.intentos) == 0,
                 f"{len(guardia.intentos)} intentos")
        segundos = time.perf_counter() - inicio
        chk_bool(checks, "tiempo de ejecución < 10 s", segundos < 10.0, f"{segundos:.2f} s (dentro del cálculo)")

    # ------------------------------------------------------------------
    # Resumen de comprobaciones
    # ------------------------------------------------------------------
    print()
    for nombre, ok, detalle in checks:
        estado = "OK   " if ok else "FALLO"
        print(f"  [{estado}] {nombre:<46s} {detalle}")

    fallos = [(n, d) for n, ok, d in checks if not ok]
    total = len(checks)
    linea("8. VEREDICTO")
    if not fallos:
        print(f"INSTRUMENTO VÁLIDO: {total}/{total} comprobaciones OK.")
        print("La línea base queda reproducida al medio dígito impreso y las particiones cuadran.")
        print("Uso permitido como instrumento de medición (fases siguientes).")
        print(f"Tiempo total: {time.perf_counter() - inicio:.2f} s. Ningún archivo del proyecto fue escrito.")
        return 0
    print(f"VEREDICTO: {len(fallos)}/{total} comprobaciones FALLARON — no continuar sin investigar:")
    for nombre, detalle in fallos:
        print(f"   - {nombre}: {detalle}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
