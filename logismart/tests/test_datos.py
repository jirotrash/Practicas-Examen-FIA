"""
Pruebas de persistencia (MongoDB simulado con mongomock), matriz de
riesgos (portadas de la sección 4 original) y asistente RAG.
"""

import unittest
from unittest import mock

import mongomock

from asistente import rag
from db import conexion, datos_demo, repositorios
from db.conexion import ErrorBaseDatos
from riesgos import matriz


def base_simulada():
    db = mongomock.MongoClient().logismart_pruebas
    conexion.crear_indices(db)
    conexion.usar_db_de_pruebas(db)
    return db


class TestRepositorios(unittest.TestCase):

    def setUp(self):
        self.db = base_simulada()
        datos_demo.cargar()

    def test_datos_demo(self):
        self.assertEqual(self.db.camiones.count_documents({}), 12)
        self.assertGreater(self.db.accesos.count_documents({}), 50)
        self.assertEqual(self.db.riesgos_eticos.count_documents({}), 8)

    def test_crud_camion_y_duplicado(self):
        id_nuevo = repositorios.crear_camion({"camion_id": "cam-900", "placa": "zzz-900-z", "empresa": "Prueba",
                                              "autorizado": True})
        self.assertEqual(repositorios.buscar_camion("ZZZ-900-Z")["camion_id"], "CAM-900")
        with self.assertRaises(ErrorBaseDatos):
            repositorios.crear_camion({"camion_id": "CAM-900", "placa": "YYY-900-Y", "empresa": "x"})
        repositorios.actualizar_camion(id_nuevo, {"empresa": "Otra"})
        self.assertEqual(repositorios.buscar_camion("CAM-900")["empresa"], "Otra")
        repositorios.eliminar_camion(id_nuevo)
        self.assertIsNone(repositorios.buscar_camion("CAM-900"))

    def test_incidente_historial(self):
        id_inc = repositorios.crear_incidente({"asunto": "x", "categoria": "otro", "prioridad": "baja"})
        repositorios.actualizar_incidente(id_inc, {"estado": "en_atencion"}, "tester", "cambio_estado")
        inc = repositorios.obtener_incidente(id_inc)
        self.assertEqual(inc["estado"], "en_atencion")
        self.assertEqual(len(inc["historial"]), 2)
        with self.assertRaises(ErrorBaseDatos):
            repositorios.actualizar_incidente(id_inc, {"estado": "inventado"})

    def test_agregacion_por_categoria_y_semana(self):
        filas = repositorios.incidentes_por_categoria_semana()
        self.assertTrue(filas)
        self.assertEqual(set(filas[0]), {"categoria", "semana", "total"})
        self.assertEqual(sum(f["total"] for f in filas), self.db.incidentes.count_documents({}))

    def test_riesgo_historico(self):
        riesgo = repositorios.listar_riesgos()[0]
        repositorios.actualizar_riesgo(riesgo["_id"], {"probabilidad": 1}, "tester")
        actualizado = self.db.riesgos_eticos.find_one({"_id": riesgo["_id"]})
        self.assertEqual(actualizado["historico"][-1]["cambios"]["probabilidad"], [riesgo["probabilidad"], 1])

    def test_indicadores(self):
        ind = repositorios.indicadores()
        self.assertEqual(ind["accesos_registrados"], ind["accesos_verde"] + ind["accesos_amarillo"] + ind["accesos_rojo"])

    def test_id_invalido(self):
        with self.assertRaises(ErrorBaseDatos):
            repositorios.eliminar_riesgo("no-es-un-id")


class TestMatrizRiesgos(unittest.TestCase):
    """Niveles y validaciones (portado de la sección 4 original)."""

    def test_niveles_limite(self):
        casos = {(1, 4): "bajo", (1, 5): "medio", (2, 5): "alto", (4, 4): "alto", (5, 4): "crítico"}
        for (p, i), esperado in casos.items():
            self.assertEqual(matriz.nivel(matriz.puntaje(p, i)), esperado, f"{(p, i)}")

    def test_validaciones(self):
        base = {"modulo": "m", "descripcion": "d", "categoria": "sesgo", "probabilidad": 3, "impacto": 3,
                "probabilidad_residual": 2, "impacto_residual": 2}
        self.assertEqual(matriz.validar_riesgo(base), [])
        self.assertTrue(matriz.validar_riesgo({**base, "probabilidad": 6}))
        self.assertTrue(matriz.validar_riesgo({**base, "categoria": "inventada"}))
        self.assertTrue(matriz.validar_riesgo({**base, "modulo": "  "}))
        self.assertTrue(matriz.validar_riesgo({**base, "probabilidad_residual": 5, "impacto_residual": 5}))

    def test_riesgo_residual(self):
        e = matriz.enriquecer({"probabilidad": 4, "impacto": 5, "probabilidad_residual": 2, "impacto_residual": 4})
        self.assertEqual((e["puntaje_inherente"], e["puntaje_residual"]), (20, 8))
        self.assertEqual((e["nivel_inherente"], e["nivel_residual"]), ("crítico", "medio"))
        self.assertEqual(e["reduccion_pct"], 60.0)


class TestAsistenteRAG(unittest.TestCase):

    def setUp(self):
        base_simulada()
        datos_demo.cargar()

    @mock.patch("asistente.rag.cliente.chat")
    def test_sin_datos_no_llama_al_llm(self, chat):
        r = rag.responder("¿Qué pasó con la placa ZZZ-000-Z?")
        self.assertTrue(r["sin_datos"])
        self.assertIn("No tengo información", r["respuesta"])
        chat.assert_not_called()

    def test_recupera_camion_y_accesos(self):
        fuentes = rag.recuperar("¿Por qué CAM-102 fue enviado a inspección?")
        colecciones = {f["coleccion"] for f in fuentes}
        self.assertIn("camiones", colecciones)
        self.assertIn("accesos", colecciones)

    @mock.patch("asistente.rag.cliente.chat")
    def test_contexto_solo_con_registros(self, chat):
        chat.return_value = ("Respuesta [x]", 10.0, "llama3.2")
        r = rag.responder("¿Por qué CAM-102 fue enviado a inspección?")
        mensajes = chat.call_args[0][0]
        self.assertIn("CONTEXTO:", mensajes[-1]["content"])
        self.assertIn("CAM-102", mensajes[-1]["content"])
        self.assertFalse(r["sin_datos"])


if __name__ == "__main__":
    unittest.main()
