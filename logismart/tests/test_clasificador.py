"""
Pruebas del clasificador: reglas (portadas del script original),
validación pydantic, reintento, respaldo y fusión híbrida.
El LLM se simula para que las pruebas no dependan de Ollama.
"""

import json
import os
import unittest
from unittest import mock

from clasificador import hibrido, reglas
from clasificador import llm as clasif_llm
from llm.cliente import ErrorLLM

CORREO = dict(
    remitente="operador@planta.example",
    asunto="URGENTE: derrame en andén 3",
    cuerpo="El camión CAM-102 con placas ABC-123-D presenta fuga de químico inflamable. "
           "La báscula marcó 48.5 toneladas.",
)

JSON_VALIDO = json.dumps({
    "categoria": "materiales_peligrosos", "prioridad": "critica",
    "entidades": {"placa": "abc-123-d", "camion_id": "cam-102", "peso_reportado_kg": 48500, "ubicacion": "andén 3"},
    "resumen": "Fuga de químico inflamable en el andén 3.",
})


class TestClasificadorReglasOriginal(unittest.TestCase):
    """Pruebas portadas de la sección 3 del script original."""

    def test_clasificacion_y_extraccion(self):
        c = reglas.clasificar(CORREO["asunto"], CORREO["cuerpo"])
        d = reglas.extraer_entidades(CORREO["asunto"], CORREO["cuerpo"])
        self.assertEqual(c["categoria"], "materiales_peligrosos")
        self.assertEqual(c["prioridad"], "critica")
        self.assertEqual(d["placa"], "ABC-123-D")
        self.assertEqual(d["camion_id"], "CAM-102")
        self.assertEqual(d["peso_reportado_kg"], 48500.0)
        self.assertEqual(d["ubicacion"], "andén 3")

    def test_campos_faltantes_son_none(self):
        self.assertEqual(reglas.clasificar("Consulta", "Hola, tengo una duda general.")["categoria"], "otro")
        d = reglas.extraer_entidades("Consulta", "Hola")
        self.assertIsNone(d["placa"])
        self.assertIsNone(d["peso_reportado_kg"])

    def test_urgencia_escala_prioridad(self):
        self.assertEqual(reglas.clasificar("Pantalla lenta", "El sistema carga lento")["prioridad"], "baja")
        self.assertEqual(reglas.clasificar("Pantalla lenta urgente", "El sistema carga lento")["prioridad"], "media")

    def test_envio_simulado_y_fallo_smtp(self):
        self.assertTrue(reglas.enviar_correo_soporte("a@b.c", "d@e.f", "x", "y", simulacion=True)["enviado"])
        for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
            os.environ.pop(var, None)
        r = reglas.enviar_correo_soporte("a@b.c", "d@e.f", "x", "y", simulacion=False)
        self.assertFalse(r["enviado"])
        self.assertIsNotNone(r["error"])


class TestClasificadorLLM(unittest.TestCase):

    @mock.patch("clasificador.llm.cliente.chat")
    def test_json_valido(self, chat):
        chat.return_value = (JSON_VALIDO, 120.0, "llama3.2")
        r = clasif_llm.clasificar_con_llm(CORREO["asunto"], CORREO["cuerpo"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["clasificacion"]["entidades"]["camion_id"], "CAM-102")  # normalizado
        self.assertEqual(r["intentos"], 1)

    @mock.patch("clasificador.llm.cliente.chat")
    def test_reintenta_si_json_invalido(self, chat):
        chat.side_effect = [("esto no es json", 50.0, "llama3.2"), (JSON_VALIDO, 60.0, "llama3.2")]
        r = clasif_llm.clasificar_con_llm(CORREO["asunto"], CORREO["cuerpo"], {"reintentos_llm": 1})
        self.assertTrue(r["ok"])
        self.assertEqual(r["intentos"], 2)
        self.assertEqual(r["latencia_ms"], 110.0)

    @mock.patch("clasificador.llm.cliente.chat")
    def test_categoria_fuera_del_esquema_es_invalida(self, chat):
        malo = json.loads(JSON_VALIDO)
        malo["categoria"] = "inventada"
        chat.return_value = (json.dumps(malo), 50.0, "llama3.2")
        r = clasif_llm.clasificar_con_llm(CORREO["asunto"], CORREO["cuerpo"], {"reintentos_llm": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(r["intentos"], 2)

    @mock.patch("clasificador.llm.cliente.chat")
    def test_campo_extra_es_invalido(self, chat):
        malo = json.loads(JSON_VALIDO)
        malo["opinion"] = "no debería estar"
        chat.return_value = (json.dumps(malo), 50.0, "llama3.2")
        self.assertFalse(clasif_llm.clasificar_con_llm("a", "bbbbbbbbbbbb", {"reintentos_llm": 0})["ok"])

    @mock.patch("clasificador.llm.cliente.chat", side_effect=ErrorLLM("sin conexión"))
    def test_sin_ollama_no_reintenta(self, chat):
        r = clasif_llm.clasificar_con_llm("a", "b", {"reintentos_llm": 3})
        self.assertFalse(r["ok"])
        self.assertEqual(chat.call_count, 1)


class TestHibrido(unittest.TestCase):

    def test_coinciden(self):
        cat, pri, revision, _ = hibrido.fusionar({"categoria": "sobrepeso", "prioridad": "media"},
                                                 {"categoria": "sobrepeso", "prioridad": "media"})
        self.assertEqual((cat, pri, revision), ("sobrepeso", "media", False))

    def test_discrepan_gana_prioridad_mas_alta(self):
        cat, pri, revision, motivo = hibrido.fusionar({"categoria": "otro", "prioridad": "baja"},
                                                      {"categoria": "materiales_peligrosos", "prioridad": "critica"})
        self.assertEqual((cat, pri, revision), ("materiales_peligrosos", "critica", True))
        self.assertIn("Discrepancia", motivo)

    def test_misma_prioridad_distinta_categoria(self):
        cat, pri, revision, _ = hibrido.fusionar({"categoria": "acceso_no_autorizado", "prioridad": "alta"},
                                                 {"categoria": "somnolencia_conductor", "prioridad": "alta"})
        self.assertTrue(revision)
        self.assertEqual(pri, "alta")

    @mock.patch("clasificador.hibrido.repositorios.registrar_evaluacion")
    @mock.patch("clasificador.llm.cliente.chat", side_effect=ErrorLLM("sin conexión"))
    def test_respaldo_por_reglas(self, chat, registrar):
        r = hibrido.clasificar_incidente(**CORREO)
        self.assertEqual(r["fuente_clasificacion"], "reglas_respaldo")
        self.assertEqual(r["categoria"], "materiales_peligrosos")
        registrar.assert_called_once()
        self.assertFalse(registrar.call_args[0][0]["json_valido"])

    @mock.patch("clasificador.hibrido.repositorios.registrar_evaluacion")
    @mock.patch("clasificador.llm.cliente.chat")
    def test_hibrido_completo(self, chat, registrar):
        chat.return_value = (JSON_VALIDO, 100.0, "llama3.2")
        r = hibrido.clasificar_incidente(**CORREO)
        self.assertEqual(r["fuente_clasificacion"], "hibrido")
        self.assertFalse(r["requiere_revision_humana"])
        self.assertTrue(registrar.call_args[0][0]["coincidio_con_reglas"])


if __name__ == "__main__":
    unittest.main()
