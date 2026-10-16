#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Motor de valor esperado con push explícito (F5 — 16/10/2026).

Qué hace
--------
Convierte momios americanos a pago neto y probabilidad de equilibrio, estima
la probabilidad de push de cada apuesta y calcula el valor esperado por dólar
apostado con la probabilidad CALIBRADA (F4, `calibracion.py`). No selecciona
nada por sí mismo: informa. El pre-registro de su evaluación está en
`lab/pre_registro_motor_ev.md` (escrito antes de medir).

Contrato y convenciones
-----------------------
- `p_condicional` = P(ganar | sin push) — la probabilidad calibrada del lado
  del pick (así se ajustó la calibración: push y empates fuera del universo).
- `p_push` = P(push) estimada aparte; el push DEVUELVE el importe apostado,
  así que en el EV pesa 0: EV = p_ganar·pago − p_perder.
- p_ganar = (1−p_push)·p_condicional y p_perder = (1−p_push)·(1−p_condicional):
  las tres suman 1 y son las que entran en el EV.
- Probabilidad de equilibrio = 1/(1+pago neto) = probabilidad implícita del
  momio. Es el valor de p_condicional donde EV = 0; el push solo escala el EV
  (no mueve el umbral) porque devuelve el importe.
- Sin cuota, sin probabilidad o sin datos para el push → vacío (aquí no se
  inventa −110 ni push = 0 «por defecto»).
- La incertidumbre del EV es la banda del calibrado por error de estimación
  de los coeficientes (delta method; `calibracion.intervalo_prob`) — NO
  incluye cambio de régimen, error de modelo ni incertidumbre del push.
- El push se ESTIMA con el modelo (no se observa); su sesgo está medido
  contra 2006-2025 (`NOTA_PUSH`): donde la tolerancia pre-registrada no se
  cumple (empate de moneyline) se adopta solo con la limitación documentada
  en pantalla, como fija `lab/pre_registro_motor_ev.md`.
- NINGÚN estado dice «validada»: un EV+ puede ser ruido o error de
  calibración; la validación de la estrategia es prospectiva (registro fiel).
  `ESTADO_ESTRATEGIA` lo dice explícitamente para mostrarlo en la interfaz.

Determinista, sin red, sin dependencias nuevas (numpy/pandas).
"""

import math

import numpy as np
import pandas as pd

import calibracion

VERSION_EV = "ev-f5-1"

ESTADO_ESTRATEGIA = (
    "Sin validación prospectiva: nada retrospectivo cuenta como validación "
    "(2018-2025 se consumió con srs-v2 y 2006-2017 con la rejilla del modelo). "
    "Un EV positivo puede ser ruido o error de calibración; la única evidencia "
    "limpia será el registro fiel hacia adelante."
)

# Sesgo medido del estimador de push (control empírico 2006-2025, agregado
# por mercado; evidencia en `lab/verificacion_motor_ev.py` y
# `lab/salida_motor_ev.txt`). La tolerancia pre-registrada era 0.015: el
# total y el spread agregado la cumplen; el empate de moneyline NO, así que
# se adopta solo con esta limitación documentada en pantalla (regla de
# `lab/pre_registro_motor_ev.md`). Se muestra en la pestaña 🎯.
NOTA_PUSH = (
    "Push estimado con el modelo (normal discretizada), no observado. Control "
    "2006-2025: total Δ −0.1 pp; spread Δ −1.1 pp agregado, pero subestima "
    "~2 pp en líneas enteras (los números clave concentran más pushes de los "
    "que captura la normal); empate de moneyline Δ +2.4 pp (la normal empata "
    "más de lo que empata la NFL de verdad; solo afectaría a picks de "
    "moneyline, hoy 0)."
)

# Estados posibles de una selección (ninguno es «validada»).
SIN_DATOS = "Sin datos"
SIN_EV = "Sin EV"
EV_EN_EL_RUIDO = "EV+ en el ruido"
EV_SIN_VALIDAR = "EV+ sin validar"


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------
def _a_serie(valor, indice=None):
    """Escalar/lista/Serie → Series float (NaN-safe).

    Si pasas una Serie, debe compartir índice con la referencia; una lista o
    un array se interpreta por POSICIÓN; un escalar se repite.
    """
    s = pd.to_numeric(pd.Series(valor), errors="coerce").astype(float)
    if indice is not None and not s.index.equals(indice):
        if len(s) == 1 and len(indice) != 1:
            s = pd.Series(np.full(len(indice), s.iloc[0]), index=indice)
        else:
            s = pd.Series(s.to_numpy(), index=indice)
    return s


def _phi(z):
    """Φ(z): acumulada normal estándar (sin scipy; misma que datos._phi)."""
    z = np.asarray(z, dtype=float)
    if z.size == 0:  # un registro vacío es válido: devolver vacío
        return z
    return 0.5 * (1.0 + np.vectorize(math.erf, otypes=[float])(z / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Momios: pago neto, probabilidad implícita y probabilidad de equilibrio
# ---------------------------------------------------------------------------
def pago_neto(cuota):
    """Cuota americana (−110, +145…) → pago neto por $1 (sin devolver el $).

    Vacíos o cuota 0 → vacío: aquí no se asume −110 (eso es solo para el ROI
    histórico de la app, que rellena cuotas viejas; el EV no rellena nada).
    """
    c = pd.to_numeric(pd.Series(cuota), errors="coerce").astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        pago = (c / 100.0).where(c > 0, 100.0 / -c)
    return pago.mask(c.isna() | (c == 0) | ~np.isfinite(pago))


def prob_implicita(cuota):
    """Probabilidad implícita del momio (incluye el vig de la casa)."""
    return 1.0 / (1.0 + pago_neto(cuota))


def prob_equilibrio(cuota):
    """Probabilidad de equilibrio: la p_condicional que hace EV = 0.

    Numéricamente es la probabilidad implícita (1/(1+pago neto)): con el push
    modelado como devolución del importe, el umbral no se mueve; el push solo
    escala el EV. Por debajo de esta probabilidad la apuesta pierde a largo
    plazo; por encima, gana — SI la probabilidad estimada fuera verdad.
    """
    return prob_implicita(cuota)


# ---------------------------------------------------------------------------
# Push: estimación explícita (no se asume 0 sin justificarlo)
# ---------------------------------------------------------------------------
def prob_push(valor_modelo, linea, sigma):
    """P(push) estimada por el modelo (normal discretizada sobre enteros).

    - Línea x.5 → 0 EXACTO (aritmético: el marcador real es entero y nunca
      cae en x.5; no hace falta el modelo).
    - Línea entera → Φ((L+0.5−μ)/σ) − Φ((L−0.5−μ)/σ): probabilidad de que el
      valor (margen o total) caiga justo en la línea. Para moneyline usar
      `linea = 0` (empate = push).

    Es una estimación del MODELO, no una frecuencia observada; su
    incertidumbre no está cuantificada aparte (ver
    `lab/verificacion_motor_ev.py`, que la contrasta con la historia).
    Vacíos: sin línea → vacío; línea entera sin μ/σ válidos → vacío.
    """
    v = pd.to_numeric(pd.Series(valor_modelo), errors="coerce").astype(float)
    l = _a_serie(linea, v.index)
    s = _a_serie(sigma, v.index)
    entera = (l % 1.0).eq(0.0)
    con_modelo = v.notna() & s.notna() & (s > 0)
    zi = (l + 0.5 - v) / s
    zs = (l - 0.5 - v) / s
    p_entera = pd.Series(_phi(zi.to_numpy()) - _phi(zs.to_numpy()), index=v.index)
    p = pd.Series(np.nan, index=v.index)
    p = p.mask(l.notna() & ~entera, 0.0)   # x.5: push imposible (exacto)
    p = p.mask(entera & con_modelo, p_entera)  # entera: estimación del modelo
    return p.clip(lower=0.0, upper=1.0)


# ---------------------------------------------------------------------------
# EV con push explícito
# ---------------------------------------------------------------------------
def descomponer(p_condicional, p_push=0.0):
    """(p_ganar, p_perder, p_push) sin condicionar; las tres suman 1.

    `p_condicional` = P(ganar | sin push) (la calibrada del lado del pick);
    el push devuelve el importe, así que p_ganar + p_perder = 1 − p_push.
    """
    pc = _a_serie(p_condicional)
    pp = _a_serie(p_push, pc.index)
    p_ganar = (1.0 - pp) * pc
    p_perder = (1.0 - pp) * (1.0 - pc)
    return p_ganar, p_perder, pp


def ev(p_condicional, cuota, p_push=0.0):
    """EV por $1 apostado con push explícito.

    EV = p_ganar·pago_neto − p_perder  (+ p_push·0: el push devuelve el
    importe). Equivale a (1−p_push)·(p_cond·pago − (1−p_cond)). Vacío si
    falta la cuota, la probabilidad o el push.
    """
    pc = _a_serie(p_condicional)
    pp = _a_serie(p_push, pc.index)
    b = _a_serie(pago_neto(cuota), pc.index)
    return (1.0 - pp) * (pc * b - (1.0 - pc))


def estado_ev(ev_valor, ev_lo=None):
    """Etiqueta del estado de una selección. NUNCA dice «validada».

    - vacío → «Sin datos»; EV ≤ 0 → «Sin EV»;
    - EV > 0 con el IC95% del EV sin superar 0 (o sin IC) → «EV+ en el ruido»;
    - EV > 0 con IC95% entero > 0 → «EV+ sin validar» (sigue sin ser
      validación: solo dice que el error de estimación de los coeficientes no
      explica el signo).
    """
    e = _a_serie(ev_valor)
    lo = (pd.Series(np.nan, index=e.index) if ev_lo is None
          else _a_serie(ev_lo, e.index))
    estado = pd.Series(SIN_DATOS, index=e.index)
    estado = estado.mask(e.notna() & (e <= 0.0), SIN_EV)
    positivo = e > 0.0
    robusto = positivo & lo.notna() & (lo > 0.0)
    estado = estado.mask(positivo & ~robusto, EV_EN_EL_RUIDO)
    estado = estado.mask(robusto, EV_SIN_VALIDAR)
    return estado


def evaluar_apuesta(p_condicional, cuota, p_push=0.0, p_lo=None, p_hi=None):
    """Todo junto para una lista de apuestas: probabilidades, EV, IC y estado.

    Devuelve un DataFrame alineado con la entrada:
    `prob_equilibrio`, `p_ganar`, `p_perder`, `p_push`, `ev`, `ev_lo`, `ev_hi`
    y `estado`. `p_lo`/`p_hi` son los extremos de la banda del calibrado
    (misma orientación que `p_condicional`); sin ellos, `ev_lo`/`ev_hi` quedan
    vacíos y el estado es conservador.
    """
    pc = _a_serie(p_condicional)
    pp = _a_serie(p_push, pc.index)
    p_eq = _a_serie(prob_equilibrio(cuota), pc.index)
    p_ganar, p_perder, pp = descomponer(pc, pp)
    e = ev(pc, cuota, pp)
    if p_lo is None or p_hi is None:
        e_lo = pd.Series(np.nan, index=pc.index)
        e_hi = pd.Series(np.nan, index=pc.index)
    else:
        e_lo = ev(_a_serie(p_lo, pc.index), cuota, pp)
        e_hi = ev(_a_serie(p_hi, pc.index), cuota, pp)
    return pd.DataFrame({
        "prob_equilibrio": p_eq,
        "p_ganar": p_ganar,
        "p_perder": p_perder,
        "p_push": pp,
        "ev": e,
        "ev_lo": e_lo,
        "ev_hi": e_hi,
        "estado": estado_ev(e, e_lo),
    }, index=pc.index)


# ---------------------------------------------------------------------------
# Integración con los marcos de picks de la app
# ---------------------------------------------------------------------------
def probabilidad_supera(valor_modelo, linea, sigma):
    """P(valor > línea) con la normal del modelo.

    Misma fórmula que `datos.probabilidad_supera` (aquí se replica para que
    el motor no arrastre la capa de datos). Sirve para reconstruir la
    probabilidad BRUTA que entra a la calibración y pedirle su banda.
    """
    v = _a_serie(valor_modelo)
    l = _a_serie(linea, v.index)
    s = _a_serie(sigma, v.index)
    p = pd.Series(_phi(((v - l) / s).to_numpy()), index=v.index)
    return p.mask(v.isna() | l.isna() | s.isna() | (s <= 0))


def decorar(picks, mercado):
    """Añade a un marco de picks las columnas del motor (F5), sin mutarlo.

    Requiere (orientación del proyecto: local cubre / over / gana local):
    - spread: margen_modelo, spread_line, sigma_modelo, cuota, prob_modelo,
      al_local
    - total: total_modelo, total_line, sigma_total_modelo, cuota, prob_modelo,
      al_over
    - moneyline: margen_modelo, sigma_modelo, cuota, prob_modelo, al_local,
      prob_local_sin_vig

    `prob_modelo` es la probabilidad CALIBRADA del lado del pick (la que ya
    traen los picks de la jornada). Devuelve una COPIA con: `p_equilibrio`,
    `p_estimada`, `p_push`, `p_ganar`, `p_perder`, `ev_estimado`, `ev_lo`,
    `ev_hi` y `estado_ev`. La banda del EV usa el error de estimación de la
    calibración (delta method); no incluye error de modelo ni del push.
    """
    requeridas = {
        "spread": ("margen_modelo", "spread_line", "sigma_modelo", "cuota",
                   "prob_modelo", "al_local"),
        "total": ("total_modelo", "total_line", "sigma_total_modelo", "cuota",
                  "prob_modelo", "al_over"),
        "moneyline": ("margen_modelo", "sigma_modelo", "cuota", "prob_modelo",
                      "al_local", "prob_local_sin_vig"),
    }
    if mercado not in requeridas:
        raise ValueError(f"Mercado desconocido para decorar: {mercado!r}")
    faltan = [c for c in requeridas[mercado] if c not in picks.columns]
    if faltan:
        raise ValueError(f"Faltan columnas para decorar ({mercado}): {faltan}")

    v = picks.copy()
    indice = v.index
    cuota = _a_serie(v["cuota"], indice)
    p_lado = _a_serie(v["prob_modelo"], indice)

    if mercado == "spread":
        p_bruta = probabilidad_supera(
            v["margen_modelo"], v["spread_line"], v["sigma_modelo"])
        p_push = prob_push(v["margen_modelo"], v["spread_line"], v["sigma_modelo"])
        lo, hi = calibracion.intervalo_prob("spread", p_bruta)
        al_primero = v["al_local"].eq(True)
    elif mercado == "total":
        p_bruta = probabilidad_supera(
            v["total_modelo"], v["total_line"], v["sigma_total_modelo"])
        p_push = prob_push(
            v["total_modelo"], v["total_line"], v["sigma_total_modelo"])
        lo, hi = calibracion.intervalo_prob("total", p_bruta)
        al_primero = v["al_over"].eq(True)
    else:
        m = _a_serie(v["margen_modelo"], indice)
        s = _a_serie(v["sigma_modelo"], indice)
        p_bruta = pd.Series(_phi((m / s).to_numpy()), index=indice).mask(
            m.isna() | s.isna() | (s <= 0))
        p_push = prob_push(v["margen_modelo"], 0.0, v["sigma_modelo"])
        lo, hi = calibracion.intervalo_prob(
            "moneyline", p_bruta, _a_serie(v["prob_local_sin_vig"], indice))
        al_primero = v["al_local"].eq(True)

    lo = _a_serie(lo, indice)
    hi = _a_serie(hi, indice)
    # El IC es monótono en la probabilidad: el otro lado lo invierte y lo gira.
    p_lo = pd.Series(np.where(al_primero, lo, 1.0 - hi), index=indice)
    p_hi = pd.Series(np.where(al_primero, hi, 1.0 - lo), index=indice)
    p_lo = p_lo.mask(p_bruta.isna())
    p_hi = p_hi.mask(p_bruta.isna())

    cuadro = evaluar_apuesta(p_lado, cuota, p_push, p_lo, p_hi)
    v["p_equilibrio"] = cuadro["prob_equilibrio"]
    v["p_estimada"] = p_lado
    v["p_push"] = cuadro["p_push"]
    v["p_ganar"] = cuadro["p_ganar"]
    v["p_perder"] = cuadro["p_perder"]
    v["ev_estimado"] = cuadro["ev"]
    v["ev_lo"] = cuadro["ev_lo"]
    v["ev_hi"] = cuadro["ev_hi"]
    v["estado_ev"] = cuadro["estado"]
    return v
