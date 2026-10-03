"""
Pruebas del motor de reglas.

Incluye las pruebas ORIGINALES de logiuncodigo.py (sección 2) para
demostrar que separar el código en capas no cambió el comportamiento
de A y E, más pruebas de las reglas nuevas B y V.
"""

import itertools
import unittest
from datetime import datetime, timedelta

from reglas import motor


def evaluar_camion(P, Q, R, S):
    """Adaptador con la firma original: devuelve solo A y E."""
    r = motor.evaluar(P, Q, R, S)
    return {"acceso_estandar": r["reglas"]["A"], "inspeccion_especial": r["reglas"]["E"]}


class TestReglasOriginales(unittest.TestCase):
    """Pruebas portadas sin cambios del script original."""

    ESPERADO = {
        (1, 1, 1, 1): (0, 1), (1, 1, 1, 0): (0, 1), (1, 1, 0, 1): (0, 1), (1, 1, 0, 0): (0, 1),
        (1, 0, 1, 1): (1, 1), (1, 0, 1, 0): (0, 1), (1, 0, 0, 1): (1, 0), (1, 0, 0, 0): (0, 0),
        (0, 1, 1, 1): (0, 0), (0, 1, 1, 0): (0, 0), (0, 1, 0, 1): (0, 0), (0, 1, 0, 0): (0, 0),
        (0, 0, 1, 1): (0, 0), (0, 0, 1, 0): (0, 0), (0, 0, 0, 1): (0, 0), (0, 0, 0, 0): (0, 0),
    }

    def test_tabla_completa(self):
        for (p, q, r, s), (a, e) in self.ESPERADO.items():
            res = evaluar_camion(bool(p), bool(q), bool(r), bool(s))
            self.assertEqual(res["acceso_estandar"], bool(a), f"A mal en {(p, q, r, s)}")
            self.assertEqual(res["inspeccion_especial"], bool(e), f"E mal en {(p, q, r, s)}")

    def test_sin_autorizacion_nunca_pasa(self):
        for q, r, s in itertools.product([True, False], repeat=3):
            res = evaluar_camion(False, q, r, s)
            self.assertFalse(res["acceso_estandar"])
            self.assertFalse(res["inspeccion_especial"])

    def test_sobrepeso_bloquea_acceso_estandar(self):
        for r, s in itertools.product([True, False], repeat=2):
            self.assertFalse(evaluar_camion(True, True, r, s)["acceso_estandar"])

    def test_caso_ambas_reglas_verdaderas(self):
        self.assertEqual(evaluar_camion(True, False, True, True),
                         {"acceso_estandar": True, "inspeccion_especial": True})

    def test_tipo_invalido(self):
        with self.assertRaises(TypeError):
            motor.evaluar(1, False, False, True)

    def test_tabla_verdad_tiene_16_filas(self):
        self.assertEqual(len(motor.tabla_original()), 16)


class TestReglasNuevas(unittest.TestCase):

    def test_tabla_B(self):
        esperado = {(True, True): True, (True, False): False, (False, True): False, (False, False): False}
        for fila in motor.tabla_verdad("B"):
            self.assertEqual(fila["B"], esperado[(fila["R"], fila["H"])])

    def test_tabla_V(self):
        for fila in motor.tabla_verdad("V"):
            self.assertEqual(fila["V"], fila["S"] and fila["T"])

    def test_bloqueo_horario_gana_sobre_acceso(self):
        r = motor.evaluar(P=True, Q=False, R=True, S=True, H=True, T=False)
        self.assertTrue(r["reglas"]["A"])
        self.assertTrue(r["reglas"]["B"])
        self.assertEqual(r["resultado"], "rojo")

    def test_inspeccion_gana_sobre_acceso(self):
        r = motor.evaluar(P=True, Q=False, R=True, S=True, H=False)
        self.assertEqual(r["resultado"], "amarillo")

    def test_acceso_con_aviso_de_renovacion(self):
        r = motor.evaluar(P=True, Q=False, R=False, S=True, H=False, T=True)
        self.assertEqual(r["resultado"], "verde")
        self.assertTrue(any("renovación" in a for a in r["avisos"]))

    def test_sin_certificacion_es_rojo(self):
        self.assertEqual(motor.evaluar(True, False, False, False)["resultado"], "rojo")

    def test_explicacion_menciona_formulas(self):
        texto = " ".join(motor.evaluar(True, True, False, True)["explicacion"])
        self.assertIn("A = P ∧ S ∧ ¬Q", texto)
        self.assertIn("Decisión", texto)

    def test_contradiccion_de_premisas(self):
        r = motor.evaluar(P=True, Q=False, R=False, S=False, H=False, T=True)
        self.assertTrue(r["advertencias"])

    def test_tabla_completa_64(self):
        self.assertEqual(len(motor.tabla_completa()), 64)

    def test_analisis_detecta_conflictos(self):
        analisis = motor.analizar_reglas()
        reglas_en_conflicto = {c["reglas"] for c in analisis["conflictos"]}
        self.assertIn("A y B", reglas_en_conflicto)
        self.assertIn("B ⇒ R", analisis["implicaciones"])
        self.assertEqual(analisis["combinaciones_imposibles"], 16)


class TestPremisasDesdeDatos(unittest.TestCase):

    def test_horario_cruza_medianoche(self):
        self.assertTrue(motor.es_horario_restringido(23, 22, 6))
        self.assertTrue(motor.es_horario_restringido(3, 22, 6))
        self.assertFalse(motor.es_horario_restringido(12, 22, 6))

    def test_premisas_de_camion(self):
        manana = datetime(2026, 10, 3, 10, 0)
        camion = {"autorizado": True, "certificacion_vence": manana + timedelta(days=10)}
        p, detalle = motor.premisas_desde_camion(camion, 45000, False, manana, {"peso_limite_kg": 40000})
        self.assertEqual(p, {"P": True, "Q": True, "R": False, "S": True, "H": False, "T": True})
        self.assertIn("45,000", detalle["Q"])

    def test_certificacion_vencida(self):
        hoy = datetime(2026, 10, 3, 10, 0)
        camion = {"autorizado": True, "certificacion_vence": hoy - timedelta(days=1)}
        p, _ = motor.premisas_desde_camion(camion, 30000, False, hoy)
        self.assertFalse(p["S"])
        self.assertFalse(p["T"])


if __name__ == "__main__":
    unittest.main()
