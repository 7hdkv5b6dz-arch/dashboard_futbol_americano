"""Pruebas del dashboard — sin red, sin créditos (F2).

Guardia global: cualquier intento de conexión desde las pruebas falla de
inmediato con un mensaje claro. Las pruebas usan datos locales y mocks;
ninguna toca servicios externos ni gasta créditos de APIs.
"""
import socket

_conexion_original = socket.socket.connect


def _conexion_bloqueada(sock, direccion, *args, **kwargs):
    raise RuntimeError(
        f"Las pruebas no usan la red (conexión bloqueada a {direccion!r}).")


socket.socket.connect = _conexion_bloqueada
