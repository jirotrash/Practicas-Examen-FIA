"""
Configuración central de LogiSmart.

Dos fuentes de configuración:

1. Archivo .env  -> datos de conexión que NO se suben a Git
   (cadena de MongoDB, host de Ollama).

2. Archivo config.json -> ajustes que el usuario cambia desde la
   pantalla "Configuración" (modelo de Ollama, umbrales, modo
   simulación de correo). Si no existe, se usan los valores por defecto.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

# Carpeta raíz del proyecto (donde está este archivo)
RAIZ = Path(__file__).resolve().parent

load_dotenv(RAIZ / ".env")

# -----------------------------------------------------------------------------
# Conexión (se leen del .env)
# -----------------------------------------------------------------------------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "logismart")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Carpeta donde se guardan los reportes exportados
CARPETA_EXPORTACIONES = RAIZ / "exportaciones"

# -----------------------------------------------------------------------------
# Ajustes editables desde la GUI
# -----------------------------------------------------------------------------
ARCHIVO_CONFIG = RAIZ / "config.json"

CONFIG_POR_DEFECTO = {
    "modelo_ollama": "llama3.2",
    "temperatura": 0.1,            # baja = respuestas más consistentes
    "num_ctx": 4096,               # memoria de contexto del modelo
    "reintentos_llm": 1,           # reintentos si el JSON del LLM es inválido
    "peso_limite_kg": 40000,       # umbral para la premisa Q (sobrepeso)
    "hora_restringida_inicio": 22, # horario restringido para materiales peligrosos
    "hora_restringida_fin": 6,
    "dias_aviso_certificacion": 30,  # premisa T: certificación por vencer
    "modo_simulacion_correo": True,  # no envía correos reales
    "correo_soporte": "soporte@logismart.example",
    "operador": "operador.caseta",
}


def cargar_config() -> dict:
    """Devuelve la configuración actual (valores por defecto + config.json)."""
    config = dict(CONFIG_POR_DEFECTO)
    if ARCHIVO_CONFIG.exists():
        try:
            with open(ARCHIVO_CONFIG, encoding="utf-8") as archivo:
                config.update(json.load(archivo))
        except (json.JSONDecodeError, OSError):
            # Si el archivo está dañado se ignora y se usan los valores por defecto
            pass
    return config


def guardar_config(config: dict) -> None:
    """Guarda la configuración en config.json."""
    with open(ARCHIVO_CONFIG, "w", encoding="utf-8") as archivo:
        json.dump(config, archivo, ensure_ascii=False, indent=2)
