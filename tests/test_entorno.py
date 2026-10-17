"""
Guardia de red de la suite (F2) — las pruebas no tocan servicios externos.

La guardia se instala en `tests/__init__.py`: cualquier intento de conexión
falla con un mensaje claro. Esta prueba comprueba que sigue activa (si
alguien la quitara, la suite lo avisaría aquí).
"""

import socket
import unittest


class SinRed(unittest.TestCase):
    def test_las_conexiones_estan_bloqueadas(self):
        with socket.socket() as sock:
            with self.assertRaises(RuntimeError) as caso:
                sock.connect(("127.0.0.1", 9))
        self.assertIn("no usan la red", str(caso.exception))


if __name__ == "__main__":
    unittest.main()
