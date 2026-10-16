#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Calibración de probabilidades del modelo (F4 — adoptada el 16/10/2026).

Contexto
--------
La auditoría F4 (pre-registro en `lab/pre_registro_calibracion.md`, evidencia
en `lab/salida_calibracion.txt`) midió que las probabilidades BRUTAS de
srs-v2 estaban sobreconfiadas: decían 60-70% donde la realidad ronda el 50%
(spread y totales), y cualquier "valor esperado" calculado con ellas engañaba.
La recalibración walk-forward corrigió esa falsa confianza (puertas G1-G5
superadas con IC95%) pero NO creó ventaja nueva: tras calibrar, las
probabilidades quedan a la par del mercado sin vig (spread y moneyline) o una
pizca detrás (total). Eso es lo que hay, medido.

Qué se adoptó (por mercado)
---------------------------
- spread    → Platt:  p_cal = sigmoide(a + b·logit(p_bruta))
- total     → Platt:  p_cal = sigmoide(a + b·logit(p_bruta))
- moneyline → mezcla: p_cal = sigmoide(a + b1·logit(p_bruta) + b2·logit(p_mercado))
  El peso del modelo en la mezcla es ≈ 0.006 (b1): la mezcla sigue al mercado.
  No hay evidencia de que el modelo aporte información propia en moneyline;
  por eso los edges calibrados de ML son ~0 y esa vía queda, en la práctica,
  sin picks. Es el resultado medido, no un fallo.

Orientación y contrato
----------------------
- Entrada y salida van en la orientación del ajuste: "el local cubre el
  spread", "over del total", "gana el local". Para el otro lado, usar `1 − p`.
- Los vacíos (NaN) se propagan; aquí no se inventa nada.
- moneyline exige `p_mercado` (probabilidad sin vig del mercado, orientación
  local); sin ella no hay calibración posible (ValueError).

Coeficientes congelados
-----------------------
Ajustados con el universo estricto de la era 2006+ (pronóstico del modelo Y
probabilidad de mercado Y resultado decidido; push y empates fuera) sobre las
temporadas 2006-2025, con la MISMA aritmética del laboratorio (Newton con
ridge 1e-6, mismo orden de datos). `tests/test_calibracion.py` los re-ajusta
desde el CSV real y verifica que coinciden al 1e-9: si ese test falla, no usar
la app hasta investigar.

Covarianza congelada
--------------------
`COVARIANZAS` es la matriz H⁻¹ en el óptimo de ESE MISMO ajuste (Hessiana con
el ridge mínimo 1e-6). No es una inferencia exacta: sirve para poner una banda
honesta al calibrado por error de estimación de los coeficientes
(`intervalo_prob`, delta method) — no cubre cambio de régimen ni error de
modelo. El test de re-ajuste la verifica junto con los coeficientes.

Refit (al cerrar una temporada nueva)
-------------------------------------
1) Re-ejecutar `lab/calibracion.py` con la temporada recién cerrada y aplicar
   las mismas puertas pre-registradas (si cambian las reglas, nuevo
   pre-registro antes de mirar resultados).
2) Actualizar `COEFICIENTES`, `COVARIANZAS` y `VERSION_CALIBRACION` aquí, los
   anclajes de `tests/test_calibracion.py` y anotarlo en `ESTADO_ACTUAL.md`.
"""

import numpy as np
import pandas as pd

VERSION_CALIBRACION = "cal-f4-1"
VENTANA_AJUSTE = "temporadas 2006-2025 (universo estricto; walk-forward)"

# Coeficientes congelados (ajuste 2006-2025). No editar sin el procedimiento
# de refit de la cabecera.
COEFICIENTES = {
    "spread": {"metodo": "platt", "a": -0.044183918568597,
               "b": 0.06425197510485653},
    "total": {"metodo": "platt", "a": -0.01033506925540498,
              "b": 0.061696330096654144},
    "moneyline": {"metodo": "mezcla", "a": -0.04783784626848224,
                  "b1": 0.005876234783138599, "b2": 1.030927042008087},
}
MERCADOS = tuple(COEFICIENTES)

# Covarianza (H⁻¹) del MISMO ajuste 2006-2025 de `COEFICIENTES`, en el orden
# (a, b) o (a, b1, b2). Solo para `intervalo_prob` (delta method). No editar
# sin el procedimiento de refit de la cabecera.
COVARIANZAS = {
    "spread": ((0.000775951707561257, 4.166184148567369e-05),
               (4.1661841485673696e-05, 0.003533664624384492)),
    "total": ((0.0007710052679816182, 0.0001265882517724089),
              (0.0001265882517724089, 0.0040398262314243795)),
    "moneyline": ((0.0010116503330762686, -0.0002550355703228503,
                   -0.00024105961882250405),
                  (-0.0002550355703228505, 0.004979449406227101,
                   -0.003095880026503321),
                  (-0.00024105961882250394, -0.0030958800265033213,
                   0.0035278391655153714)),
}


def logit(p):
    """logit con recorte a [1e-6, 1−1e-6] (evita ±infinito en 0 y 1)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1.0 - 1e-6)
    return np.log(p / (1.0 - p))


def sigmoide(z):
    """1/(1+e^−z) estable (sin desbordar con |z| grande)."""
    z = np.asarray(z, dtype=float)
    salida = np.empty_like(z)
    pos = z >= 0
    salida[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    salida[~pos] = ez / (1.0 + ez)
    return salida


def _newton(X, y, l2=1e-6, max_iter=100, tol=1e-10):
    """Logística por Newton-Raphson (intercepto + pendientes), determinista.

    Misma aritmética que `lab/calibracion.py` (de ahí salieron los coeficientes
    congelados). `l2` es el ridge mínimo sobre las pendientes. Devuelve
    `(beta, cov)`: la covarianza es H⁻¹ en el óptimo (H = XᵀWX + ridge).
    """
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
    p = sigmoide(Xd @ beta)
    w = p * (1.0 - p)
    hess = (Xd.T * w) @ Xd + l2 * np.diag(penal)
    try:
        cov = np.linalg.inv(hess)
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(hess)
    return beta, cov


def ajustar_platt(p, y):
    """(a, b) de `p_cal = sigmoide(a + b·logit(p))` para datos 0/1 `y`."""
    a, b, _ = ajustar_platt_cov(p, y)
    return a, b


def ajustar_platt_cov(p, y):
    """(a, b, cov) del ajuste Platt; `cov` es H⁻¹ en el óptimo (2×2)."""
    beta, cov = _newton(logit(p), np.asarray(y, dtype=float))
    return float(beta[0]), float(beta[1]), cov


def ajustar_mezcla(p, p_mercado, y):
    """(a, b1, b2) de la mezcla logística modelo + mercado (moneyline)."""
    a, b1, b2, _ = ajustar_mezcla_cov(p, p_mercado, y)
    return a, b1, b2


def ajustar_mezcla_cov(p, p_mercado, y):
    """(a, b1, b2, cov) de la mezcla; `cov` es H⁻¹ en el óptimo (3×3)."""
    X = np.column_stack([logit(p), logit(p_mercado)])
    beta, cov = _newton(X, np.asarray(y, dtype=float))
    return float(beta[0]), float(beta[1]), float(beta[2]), cov


def calibrar(mercado, p_modelo, p_mercado=None):
    """Probabilidad calibrada, en la misma orientación que la entrada.

    `p_modelo` es la probabilidad bruta (local cubre / over / gana local) y
    `p_mercado` solo hace falta en moneyline (probabilidad sin vig, local).
    Devuelve una `pd.Series` con el índice de `p_modelo`; los vacíos quedan
    vacíos. Los valores se recortan antes del logit, así que 0 y 1 exactos
    también devuelven un número finito (el calibrador decide cuánto valen).
    """
    if mercado not in COEFICIENTES:
        raise ValueError(
            f"Mercado desconocido: {mercado!r} (usa: {', '.join(MERCADOS)}).")
    p = pd.to_numeric(pd.Series(p_modelo), errors="coerce").astype(float)
    coef = COEFICIENTES[mercado]
    if coef["metodo"] == "platt":
        z = coef["a"] + coef["b"] * logit(p.to_numpy())
    else:
        if p_mercado is None:
            raise ValueError(
                "La calibración de moneyline necesita la probabilidad sin vig "
                "del mercado (`p_mercado`).")
        pm = pd.to_numeric(pd.Series(p_mercado), errors="coerce").astype(float)
        z = (coef["a"] + coef["b1"] * logit(p.to_numpy())
             + coef["b2"] * logit(pm.to_numpy()))
    return pd.Series(sigmoide(z), index=p.index).mask(p.isna())


def intervalo_prob(mercado, p_modelo, p_mercado=None, z=1.96):
    """Banda del calibrado por error de estimación de los coeficientes.

    Delta method sobre el ajuste congelado: en la escala logit, el desvío es
    `se = sqrt(J·Cov·Jᵀ)` con `COVARIANZAS` (H⁻¹ del ajuste 2006-2025) y la
    banda es `sigmoide(z_cal ± z·se)`. Devuelve `(lo, hi)` en la MISMA
    orientación que la entrada (local cubre / over / gana local); para el otro
    lado, invertir: `(1−hi, 1−lo)`.

    Cubre SOLO el error de estimación de los coeficientes: NO incluye cambio
    de régimen, error de modelo ni incertidumbre del push (ver el pre-registro
    `lab/pre_registro_motor_ev.md`). Los vacíos se propagan; moneyline exige
    `p_mercado` (ValueError si falta).
    """
    if mercado not in COEFICIENTES:
        raise ValueError(
            f"Mercado desconocido: {mercado!r} (usa: {', '.join(MERCADOS)}).")
    p = pd.to_numeric(pd.Series(p_modelo), errors="coerce").astype(float)
    coef = COEFICIENTES[mercado]
    cov = np.asarray(COVARIANZAS[mercado], dtype=float)
    x = logit(p.to_numpy())
    if coef["metodo"] == "platt":
        J = np.column_stack([np.ones_like(x), x])
        zc = coef["a"] + coef["b"] * x
        vacio = p.isna()
    else:
        if p_mercado is None:
            raise ValueError(
                "La banda de moneyline necesita la probabilidad sin vig del "
                "mercado (`p_mercado`).")
        pm = pd.to_numeric(pd.Series(p_mercado), errors="coerce").astype(float)
        x2 = logit(pm.to_numpy())
        J = np.column_stack([np.ones_like(x), x, x2])
        zc = coef["a"] + coef["b1"] * x + coef["b2"] * x2
        vacio = p.isna() | pm.isna()
    se2 = np.einsum("ij,jk,ik->i", J, cov, J)
    se = np.sqrt(np.clip(se2, 0.0, None))
    lo = pd.Series(sigmoide(zc - z * se), index=p.index).mask(vacio)
    hi = pd.Series(sigmoide(zc + z * se), index=p.index).mask(vacio)
    return lo, hi
