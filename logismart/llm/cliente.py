"""
Cliente del LLM local (Ollama).

Centraliza las llamadas al modelo para medir la latencia de cada una
y manejar los errores de conexión en un solo lugar.
"""

import time

import ollama

import config


class ErrorLLM(Exception):
    """Ollama no responde o el modelo no existe."""


def _cliente():
    return ollama.Client(host=config.OLLAMA_HOST, timeout=180)


def chat(mensajes, ajustes=None, formato=None):
    """
    Envía la conversación al modelo.

    formato: None para texto libre, o un esquema JSON (dict) para obligar
             al modelo a responder con esa estructura (structured outputs).

    Devuelve (texto_respuesta, latencia_ms, modelo).
    """
    ajustes = ajustes or config.cargar_config()
    modelo = ajustes.get("modelo_ollama", "llama3.2")
    opciones = {
        "temperature": ajustes.get("temperatura", 0.1),
        "num_ctx": ajustes.get("num_ctx", 4096),
    }

    inicio = time.perf_counter()
    try:
        respuesta = _cliente().chat(model=modelo, messages=mensajes, format=formato, options=opciones)
    except ollama.ResponseError as error:
        raise ErrorLLM(f"Ollama respondió con error ({error.status_code}): {error.error}") from error
    except Exception as error:  # conexión rechazada, tiempo agotado, etc.
        raise ErrorLLM(f"No se pudo conectar con Ollama en {config.OLLAMA_HOST}: {error}") from error

    latencia_ms = (time.perf_counter() - inicio) * 1000
    return respuesta["message"]["content"], latencia_ms, modelo


def listar_modelos():
    """Nombres de los modelos descargados en Ollama (para la pantalla de configuración)."""
    try:
        respuesta = _cliente().list()
        return sorted(m["model"] for m in respuesta["models"])
    except Exception:
        return []


def verificar():
    """Devuelve (True, mensaje) si Ollama responde, o (False, error)."""
    try:
        modelos = _cliente().list()["models"]
        return True, f"Ollama activo · {len(modelos)} modelo(s)"
    except Exception as error:
        return False, f"Ollama no responde en {config.OLLAMA_HOST}: {error}"
