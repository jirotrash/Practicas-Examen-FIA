"""
Clasificador de incidentes con LLM (salida JSON validada con pydantic).

Flujo:
    1. Se manda el correo al LLM pidiendo un JSON con el esquema EXACTO
       (categoria, prioridad, entidades, resumen). Además se le pasa el
       esquema a Ollama con `format=` para restringir su salida.
    2. Se valida la respuesta con pydantic.
    3. Si el JSON es inválido, se reintenta diciéndole al modelo cuál fue
       el error. Si vuelve a fallar (o Ollama no responde), quien llama
       usa el clasificador por reglas como respaldo.
"""

import json
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clasificador.reglas import CATEGORIAS_VALIDAS, ORDEN_PRIORIDAD
from llm import cliente
from llm.cliente import ErrorLLM

Categoria = Literal[
    "materiales_peligrosos", "sobrepeso", "acceso_no_autorizado",
    "falla_hardware", "falla_software", "somnolencia_conductor", "otro",
]
Prioridad = Literal["baja", "media", "alta", "critica"]


class Entidades(BaseModel):
    model_config = ConfigDict(extra="forbid")

    placa: Optional[str] = None
    camion_id: Optional[str] = None
    peso_reportado_kg: Optional[float] = None
    ubicacion: Optional[str] = None


class ClasificacionLLM(BaseModel):
    """Esquema EXACTO que debe devolver el LLM."""
    model_config = ConfigDict(extra="forbid")

    categoria: Categoria
    prioridad: Prioridad
    entidades: Entidades
    resumen: str = Field(min_length=5, max_length=400)


# Se comprueba que el esquema y el clasificador por reglas usen las mismas etiquetas
assert set(Categoria.__args__) == set(CATEGORIAS_VALIDAS)
assert list(Prioridad.__args__) == ORDEN_PRIORIDAD


PROMPT_SISTEMA = """Eres el clasificador de incidentes del centro logístico LogiSmart.
Recibes un correo de soporte y devuelves SOLO un objeto JSON, sin texto adicional.

Categorías (usa exactamente una):
- materiales_peligrosos: derrames, fugas, químicos, inflamables, tóxicos o corrosivos.
- sobrepeso: el camión excede el peso permitido o la báscula marca exceso.
- acceso_no_autorizado: vehículos o personas sin autorización, barrera forzada, intrusos.
- falla_hardware: cámaras, sensores, lectores RFID/QR, básculas o equipos físicos dañados.
- falla_software: el sistema, la aplicación o las pantallas fallan, se caen o van lentas.
- somnolencia_conductor: conductor cansado, dormido o con fatiga.
- otro: consultas generales o algo que no encaja en las anteriores.

Prioridad (baja, media, alta, critica):
- critica: riesgo inmediato para personas o ambiente (derrame, incendio, heridos).
- alta: riesgo de seguridad sin daño inmediato (intrusos, conductor dormido).
- media: afecta la operación (sobrepeso, equipo dañado).
- baja: molestias menores o consultas.
Si el correo dice urgente, emergencia o hay heridos, sube la prioridad.

Entidades: extrae solo lo que aparezca en el texto; si algo no aparece usa null.
- placa: formato como ABC-123-D
- camion_id: formato como CAM-102
- peso_reportado_kg: número en kilogramos (convierte toneladas x 1000)
- ubicacion: por ejemplo "andén 3", "puerta B", "caseta norte"

Resumen: una oración en español de máximo 25 palabras. No inventes datos.

Formato EXACTO:
{"categoria": "...", "prioridad": "...", "entidades": {"placa": null, "camion_id": null, "peso_reportado_kg": null, "ubicacion": null}, "resumen": "..."}"""


def prompt_usuario(asunto, cuerpo):
    return f"Asunto: {asunto}\nCuerpo: {cuerpo}"


def clasificar_con_llm(asunto, cuerpo, ajustes=None):
    """
    Devuelve un diccionario con:
        ok             -> True si se obtuvo un JSON válido
        clasificacion  -> dict validado (o None)
        intentos       -> cuántas llamadas se hicieron
        errores        -> mensajes de error de cada intento
        latencia_ms    -> tiempo total en el LLM
        respuesta      -> última respuesta cruda del modelo
        modelo         -> modelo usado
        prompt         -> prompt enviado (para registrarlo en evaluaciones_llm)
    """
    ajustes = ajustes or {}
    reintentos = int(ajustes.get("reintentos_llm", 1))

    mensajes = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": prompt_usuario(asunto, cuerpo)},
    ]

    errores = []
    latencia_total = 0.0
    respuesta = ""
    modelo = ajustes.get("modelo_ollama", "llama3.2")
    intentos = 0

    for intento in range(1 + reintentos):
        intentos = intento + 1
        try:
            respuesta, latencia, modelo = cliente.chat(
                mensajes, ajustes, formato=ClasificacionLLM.model_json_schema()
            )
            latencia_total += latencia
        except ErrorLLM as error:
            # Si Ollama no responde no tiene caso reintentar: se usa el respaldo
            errores.append(str(error))
            break

        try:
            validado = ClasificacionLLM.model_validate_json(respuesta)
            datos = validado.model_dump()
            if datos["entidades"]["camion_id"]:
                datos["entidades"]["camion_id"] = datos["entidades"]["camion_id"].upper()
            if datos["entidades"]["placa"]:
                datos["entidades"]["placa"] = datos["entidades"]["placa"].upper()
            return {
                "ok": True, "clasificacion": datos, "intentos": intentos, "errores": errores,
                "latencia_ms": latencia_total, "respuesta": respuesta, "modelo": modelo,
                "prompt": mensajes[-1]["content"],
            }
        except ValidationError as error:
            resumen_error = "; ".join(e["msg"] for e in error.errors()[:3])
            errores.append(f"JSON inválido (intento {intentos}): {resumen_error}")
            # Se le explica al modelo el error para que lo corrija
            mensajes.append({"role": "assistant", "content": respuesta})
            mensajes.append({"role": "user", "content":
                             f"Tu respuesta no cumple el esquema: {resumen_error}. "
                             "Responde de nuevo SOLO con el JSON en el formato exacto."})

    return {
        "ok": False, "clasificacion": None, "intentos": intentos, "errores": errores,
        "latencia_ms": latencia_total, "respuesta": respuesta, "modelo": modelo,
        "prompt": prompt_usuario(asunto, cuerpo),
    }


def esquema_como_texto():
    """Esquema JSON (para el informe técnico)."""
    return json.dumps(ClasificacionLLM.model_json_schema(), ensure_ascii=False, indent=2)
