#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificación de guardarraíles e integridad del sistema (F2) — offline.

Comprueba los criterios del encargo F2 y del diagnóstico
`lab/diagnostico_f2.md` (escrito antes de corregir):
1. El registro fiel REAL pasa la validación estructural (0 problemas) y la
   verificación no lo toca (sha idéntico antes y después).
2. Compatibilidad: un CSV con el esquema anterior (sin `p_push`) carga igual.
3. Captura en una COPIA del registro real: solo se añaden filas nuevas; las
   viejas quedan idénticas; recapturar no cambia nada; el sello de versión
   incluye modelo+calibración+motor; `p_push` y el EV se congelan.
4. Escritura atómica: un fallo simulado deja el original intacto y sin `.tmp`.
5. La captura falla cerrada: filas nuevas imposibles o archivo en disco
   corrupto → ValueError, sin escribir nada.
6. La jornada pendiente real (funciones de app.py por AST) pasa la alarma de
   coherencia de la terna p_ganar/p_perder/p_push, y los picks siguen siendo
   los mismos que midió F5 (línea base 14/13/0).
7. Seguridad: el redactado tapa la clave en mensajes de error; `.gitignore`
   cubre `.streamlit/secrets.toml`; la app está cableada a los guardarraíles.
8. Sin red y tiempo.

Cómo se corre (desde la carpeta del proyecto):
    .venv/bin/python -B lab/verificacion_integridad.py

Sale con código 1 si alguna comprobación falla. No escribe el registro real,
no usa red y no gasta créditos de APIs.
"""

import ast
import hashlib
import shutil
import sys
import tempfile
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


def extraer_version_registro(ruta_app: Path) -> str:
    """El sello VERSION_REGISTRO de app.py, evaluado sin Streamlit."""
    arbol = ast.parse(ruta_app.read_text(encoding="utf-8"))
    nodos = [n for n in arbol.body
             if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "VERSION_REGISTRO"
                     for t in n.targets)]
    if len(nodos) != 1:
        raise RuntimeError(
            "app.py: se esperaba 1 asignación de VERSION_REGISTRO y hay "
            f"{len(nodos)} — revisar la verificación")
    modulo = ast.Module(body=nodos, type_ignores=[])
    espacio = {"datos": datos, "calibracion": calibracion, "motor_ev": motor_ev}
    exec(compile(modulo, "app.py", "exec"), espacio)  # noqa: S102
    return str(espacio["VERSION_REGISTRO"])


def filas_nuevas(momento="2026-10-16T12:00:00"):
    """Dos picks sintéticos con ids que NO existen en el registro real."""
    crudo = pd.DataFrame([
        {"temporada": 2026, "semana": 99, "game_id": "2026_99_XXX_YYY",
         "equipo_local": "XXX", "equipo_visitante": "YYY",
         "mercado": "Spread", "lado": "local", "seleccion": "XXX -2.5",
         "linea_num": -2.5, "cuota": -105.0, "prob_modelo": 0.543,
         "prob_mercado": 0.512, "edge_num": 3.1, "p_push": 0.0,
         "ev_num": 0.0234},
        {"temporada": 2026, "semana": 99, "game_id": "2026_99_ZZZ_WWW",
         "equipo_local": "ZZZ", "equipo_visitante": "WWW",
         "mercado": "Total", "lado": "under", "seleccion": "Menos de 47.0",
         "linea_num": 47.0, "cuota": -110.0, "prob_modelo": 0.534,
         "prob_mercado": 0.524, "edge_num": 1.0, "p_push": 0.028,
         "ev_num": 0.0117},
    ])
    return crudo


def main() -> int:
    inicio = time.perf_counter()
    checks = []
    ruta_real = datos.RUTA_REGISTRO_PICKS
    sha_real_antes = hashlib.sha1(ruta_real.read_bytes()).hexdigest()

    print("=" * 84)
    print("Verificación de guardarraíles e integridad (F2) — sin Streamlit")
    print("=" * 84)
    for nombre in ("app.py", "datos.py", "motor_ev.py", "calibracion.py"):
        sha = hashlib.sha1((PROYECTO / nombre).read_bytes()).hexdigest()[:12]
        print(f"  {nombre:<16s} sha1 {sha}")
    ruta_diag = Path(__file__).resolve().parent / "diagnostico_f2.md"
    sha_diag = hashlib.sha1(ruta_diag.read_bytes()).hexdigest()[:12]
    print(f"  Diagnóstico: lab/diagnostico_f2.md (sha1 {sha_diag})")
    print(f"  Registro real: data/registro_picks.csv (sha1 {sha_real_antes[:12]})")
    version_registro = extraer_version_registro(PROYECTO / "app.py")
    print(f"  Sello de capturas nuevas: {version_registro}")
    print("  Solo lectura del registro real · sin red · determinista "
          "(salvo la línea de tiempo)")

    carpeta = Path(tempfile.mkdtemp(prefix="f2_integridad_"))
    try:
        with inst.GuardiaRed() as guardia:
            # --------------------------------------------------------------
            # 1. El registro real pasa la validación (sin tocarlo)
            # --------------------------------------------------------------
            inst.linea("1. REGISTRO FIEL REAL: VALIDACIÓN ESTRUCTURAL")
            registro = datos.cargar_registro_picks()
            problemas = datos.validar_registro_picks(registro)
            errores = (problemas[problemas["severidad"] == "error"]
                       if len(problemas) else problemas)
            avisos = (problemas[problemas["severidad"] == "aviso"]
                      if len(problemas) else problemas)
            inst.chk_int(checks, "registro real: filas", len(registro), 50)
            inst.chk_int(checks, "registro real: ids duplicados", 0,
                         int(registro["id"].duplicated().sum()))
            inst.chk_int(checks, "registro real: errores de validación", 0,
                         len(errores))
            inst.chk_int(checks, "registro real: avisos de validación", 0,
                         len(avisos))
            conteo_versiones = registro["version_modelo"].value_counts()
            print("  Versiones selladas: "
                  + " · ".join(f"{v} ({int(n)})"
                               for v, n in conteo_versiones.items()))
            columnas_disco = pd.read_csv(ruta_real, nrows=0).columns.tolist()
            print(f"  Esquema en disco: {'p_push' in columnas_disco and 'con p_push' or 'anterior a F2 (sin p_push)'}"
                  " — la próxima captura añade la columna con vacíos en las filas viejas")

            # --------------------------------------------------------------
            # 2. Compatibilidad con el esquema anterior
            # --------------------------------------------------------------
            inst.linea("2. COMPATIBILIDAD CON REGISTROS HISTÓRICOS")
            viejo = carpeta / "registro_viejo.csv"
            registro.drop(columns=["p_push"]).to_csv(viejo, index=False,
                                                     na_rep="")
            leido_viejo = datos.cargar_registro_picks(ruta=viejo)
            inst.chk_bool(checks, "CSV sin p_push carga con la columna vacía",
                          "p_push" in leido_viejo.columns
                          and bool(leido_viejo["p_push"].isna().all()),
                          f"n={len(leido_viejo)} · p_push toda vacía")
            inst.chk_int(checks, "CSV viejo: errores de validación", 0,
                         int((datos.validar_registro_picks(leido_viejo)
                              ["severidad"] == "error").sum()))
            inst.chk_bool(
                checks, "valores viejos intactos tras cargar",
                bool(np.allclose(
                    pd.to_numeric(leido_viejo["cuota"]).to_numpy(),
                    pd.to_numeric(registro["cuota"]).to_numpy(), atol=0)),
                "cuota fila a fila, sin cambios")

            # --------------------------------------------------------------
            # 3. Captura en copia: solo-añadir, idempotente y sellada
            # --------------------------------------------------------------
            inst.linea("3. CAPTURA EN COPIA DEL REGISTRO REAL (solo-añadir)")
            copia = carpeta / "registro_picks.csv"
            shutil.copy2(ruta_real, copia)
            antes = datos.cargar_registro_picks(ruta=copia)
            nuevas = datos.registro_desde_picks(
                filas_nuevas(), momento="2026-10-16T12:00:00",
                version=version_registro)
            total, nuevos, repetidos = datos.capturar_registro_picks(
                nuevas, ruta=copia)
            leido = datos.cargar_registro_picks(ruta=copia)
            inst.chk_int(checks, "captura: filas nuevas", nuevos, 2)
            inst.chk_int(checks, "captura: repetidas", repetidos, 0)
            inst.chk_int(checks, "captura: total = antes + nuevas",
                         len(leido), len(antes) + 2)
            try:
                pd.testing.assert_frame_equal(
                    antes.reset_index(drop=True),
                    leido.head(len(antes)).reset_index(drop=True))
                intactas, detalle = True, "assert_frame_equal fila a fila"
            except AssertionError as error:
                intactas = False
                detalle = str(error).splitlines()[0][:70]
            inst.chk_bool(checks, "captura: las filas viejas quedan IDÉNTICAS",
                          intactas, detalle)
            sello_ok = bool((leido.tail(2)["version_modelo"]
                             == version_registro).all())
            inst.chk_bool(checks, "captura: sello = modelo+calibración+motor",
                          sello_ok, version_registro)
            inst.chk_bool(
                checks, "captura: p_push y EV congelados tal cual",
                bool(np.allclose(leido.tail(2)["p_push"].to_numpy(),
                                 [0.0, 0.028], atol=1e-15))
                and bool(np.allclose(leido.tail(2)["ev"].to_numpy(),
                                     [0.0234, 0.0117], atol=1e-15)),
                f"p_push {list(leido.tail(2)['p_push'])} · "
                f"ev {list(leido.tail(2)['ev'])}")

            bytes_antes = copia.read_bytes()
            total2, nuevos2, repetidos2 = datos.capturar_registro_picks(
                nuevas, ruta=copia)
            inst.chk_bool(
                checks, "recapturar: 0 nuevos y archivo byte a byte igual",
                nuevos2 == 0 and repetidos2 == 2
                and copia.read_bytes() == bytes_antes,
                f"nuevos={nuevos2} repetidos={repetidos2}")

            movidas = datos.registro_desde_picks(
                filas_nuevas().assign(linea_num=-3.5, cuota=-120.0,
                                      ev_num=0.99),
                momento="2026-10-17T18:00:00", version=version_registro)
            datos.capturar_registro_picks(movidas, ruta=copia)
            tras_mover = datos.cargar_registro_picks(ruta=copia)
            inst.chk_bool(
                checks, "línea movida: lo congelado NO se reescribe",
                float(tras_mover.tail(2)["linea"].iloc[0]) == -2.5
                and float(tras_mover.tail(2)["cuota"].iloc[0]) == -105.0
                and float(tras_mover.tail(2)["ev"].iloc[0]) == 0.0234,
                f"linea {float(tras_mover.tail(2)['linea'].iloc[0])} · "
                f"cuota {float(tras_mover.tail(2)['cuota'].iloc[0])}")

            # --------------------------------------------------------------
            # 4. Escritura atómica
            # --------------------------------------------------------------
            inst.linea("4. ESCRITURA ATÓMICA (una interrupción no toca el original)")
            atomica = carpeta / "atomica.csv"
            shutil.copy2(ruta_real, atomica)
            bytes_atomica = atomica.read_bytes()
            to_csv_original = pd.DataFrame.to_csv

            def to_csv_fallido(*args, **kwargs):
                raise RuntimeError("fallo simulado de disco")

            pd.DataFrame.to_csv = to_csv_fallido
            try:
                try:
                    datos.guardar_registro_picks(registro, ruta=atomica)
                    fallo_lanzado = False
                except RuntimeError:
                    fallo_lanzado = True
            finally:
                pd.DataFrame.to_csv = to_csv_original
            inst.chk_bool(
                checks, "fallo de escritura: original intacto y sin .tmp",
                fallo_lanzado and atomica.read_bytes() == bytes_atomica
                and not atomica.with_name(atomica.name + ".tmp").exists(),
                "bytes idénticos + sin temporal")

            # --------------------------------------------------------------
            # 5. La captura falla cerrada
            # --------------------------------------------------------------
            inst.linea("5. CAPTURA QUE FALLA CERRADA (no escribe si hay errores)")
            rechazo = carpeta / "rechazo.csv"
            shutil.copy2(ruta_real, rechazo)
            bytes_rechazo = rechazo.read_bytes()
            mala = datos.registro_desde_picks(
                filas_nuevas().assign(prob_modelo=1.5),
                momento="2026-10-16T12:00:00", version=version_registro)
            try:
                datos.capturar_registro_picks(mala, ruta=rechazo)
                mensaje = ""
            except ValueError as error:
                mensaje = str(error)
            inst.chk_bool(
                checks, "fila nueva imposible (p=1.5): rechazada sin escribir",
                "no se escribió nada" in mensaje
                and rechazo.read_bytes() == bytes_rechazo,
                mensaje[:60] + "…" if mensaje else "NO se lanzó ValueError")

            corrupto = carpeta / "corrupto.csv"
            dup = pd.concat([antes.head(1), antes.head(1)], ignore_index=True)
            datos.guardar_registro_picks(dup, ruta=corrupto)
            bytes_corrupto = corrupto.read_bytes()
            try:
                datos.capturar_registro_picks(nuevas, ruta=corrupto)
                mensaje2 = ""
            except ValueError as error:
                mensaje2 = str(error)
            inst.chk_bool(
                checks, "archivo con ids duplicados: rechazado sin tocar",
                "NO se ha tocado nada" in mensaje2
                and corrupto.read_bytes() == bytes_corrupto,
                mensaje2[:60] + "…" if mensaje2 else "NO se lanzó ValueError")

            # --------------------------------------------------------------
            # 6. Jornada real: coherencia y línea base de picks
            # --------------------------------------------------------------
            inst.linea("6. JORNADA PENDIENTE REAL: COHERENCIA Y LÍNEA BASE")
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
            marcos = [
                ("Spread",
                 motor_ev.decorar(
                     app["evaluar_spread"](futuros, 2.0, calibrado=True),
                     "spread"), 14),
                ("Total",
                 motor_ev.decorar(
                     app["evaluar_totales"](futuros, 2.0, calibrado=True),
                     "total"), 13),
                ("Moneyline",
                 motor_ev.decorar(
                     datos.evaluar_picks_ml(futuros, umbral=0.04,
                                            calibrado=True),
                     "moneyline"), 0),
            ]
            for nombre, marco, esperado_n in marcos:
                if not len(marco):
                    inst.chk_int(checks, f"{nombre}: picks pendientes = {esperado_n}",
                                 esperado_n, esperado_n)
                    continue
                coherencia = motor_ev.problemas_coherencia(marco)
                inst.chk_int(checks, f"{nombre}: incoherencias de la terna", 0,
                             len(coherencia))
                inst.chk_int(checks, f"{nombre}: picks pendientes = línea base F5",
                             len(marco), esperado_n)

            # --------------------------------------------------------------
            # 7. Seguridad
            # --------------------------------------------------------------
            inst.linea("7. SEGURIDAD (clave fuera de pantalla, git y pruebas)")
            secreto = "CLAVE_SINTETICA_F2_987654"
            texto = (f"Max retries exceeded with url: /odds?apiKey={secreto}"
                     "&regions=us")
            limpio = datos._redactar_secretos(texto, secreto)
            inst.chk_bool(checks, "redactado: la clave no sobrevive",
                          secreto not in limpio and "apiKey=***" in limpio,
                          limpio[:60] + "…")
            get_original = datos.requests.get

            def get_fallido(*args, **kwargs):
                raise datos.requests.exceptions.ConnectionError(
                    f"HTTPSConnectionPool: url: /odds?apiKey={secreto}")

            datos.requests.get = get_fallido
            try:
                try:
                    datos.cargar_precios_casas(secreto)
                    mensaje3 = ""
                except ValueError as error:
                    mensaje3 = str(error)
            finally:
                datos.requests.get = get_original
            inst.chk_bool(
                checks, "error de conexión mostrado: sin clave",
                secreto not in mensaje3 and "Sin conexión" in mensaje3,
                mensaje3[:70] + "…")
            gitignore = (PROYECTO / ".gitignore").read_text(encoding="utf-8")
            inst.chk_bool(checks, ".gitignore cubre .streamlit/secrets.toml",
                          ".streamlit/secrets.toml" in gitignore,
                          "línea presente (no se lee el archivo de secretos)")
            fuente_app = (PROYECTO / "app.py").read_text(encoding="utf-8")
            fuente_datos = (PROYECTO / "datos.py").read_text(encoding="utf-8")
            inst.chk_bool(checks, "app.py: captura con VERSION_REGISTRO",
                          "version=VERSION_REGISTRO" in fuente_app,
                          version_registro)
            inst.chk_bool(checks, "app.py: valida el registro antes de capturar",
                          "datos.validar_registro_picks" in fuente_app
                          and "datos.resumen_problemas" in fuente_app,
                          "aviso en pantalla si hay problemas")
            inst.chk_bool(checks, "app.py: alarma de coherencia cableada",
                          "motor_ev.problemas_coherencia" in fuente_app,
                          "revisión antes de congelar")
            inst.chk_bool(checks, "app.py: p_push congelada y en la tabla",
                          'fiel_df["p_push"]' in fuente_app
                          and '"🧾 Línea de hoy"' in fuente_app,
                          "columna P. push + origen honesto")
            inst.chk_bool(checks, "datos.py: ambos errores de la API redactados",
                          fuente_datos.count("_redactar_secretos(") >= 3,
                          "definición + 2 usos")

            # --------------------------------------------------------------
            # 8. Sin red y tiempo
            # --------------------------------------------------------------
            inst.chk_bool(checks, "sin intentos de red",
                          len(guardia.intentos) == 0,
                          f"{len(guardia.intentos)} intentos")
            segundos = time.perf_counter() - inicio
            inst.chk_bool(checks, "tiempo de ejecución < 10 s", segundos < 10.0,
                          f"{segundos:.2f} s")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    # El registro real no se tocó en ningún momento.
    sha_real_despues = hashlib.sha1(ruta_real.read_bytes()).hexdigest()

    print()
    for nombre_chk, ok, detalle in checks:
        estado = "OK   " if ok else "FALLO"
        print(f"  [{estado}] {nombre_chk:<58s} {detalle}")
    print()
    intacto = sha_real_antes == sha_real_despues
    if not intacto:
        print(f"  [FALLO] REGISTRO REAL MODIFICADO: {sha_real_antes[:12]} → "
              f"{sha_real_despues[:12]}")
    fallos = [(n, d) for n, ok, d in checks if not ok]
    print()
    if not fallos and intacto:
        print(f"VEREDICTO: {len(checks)}/{len(checks)} comprobaciones OK — el "
              "registro real queda intacto")
        print(f"(sha1 {sha_real_despues[:12]}), la captura solo añade y falla "
              "cerrada ante corrupción,")
        print("la clave no puede aparecer en pantalla y la terna "
              "p_ganar/p_perder/p_push es coherente.")
        print("Recordatorio: esto NO dice que el sistema sea rentable; la "
              "validación de la estrategia")
        print("sigue siendo prospectiva (registro fiel) y nada de F2 cambia "
              "el modelo, la calibración ni los picks.")
        return 0
    print(f"VEREDICTO: {len(fallos)}/{len(checks)} comprobaciones FALLARON — "
          "no continuar sin investigar:")
    for nombre, detalle in fallos:
        print(f"   - {nombre}: {detalle}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
