"""
Clasificador de incidentes por REGLAS (palabras clave) + extracción con regex.

Es el clasificador del script original. Se conserva tal cual porque:
- funciona sin LLM (plan de respaldo), y
- sirve de línea base en el experimento (reglas vs LLM vs híbrido).
"""

import json
import logging
import os
import re
import smtplib
from email.message import EmailMessage

log = logging.getLogger("logismart")

# Categorías con sus palabras clave (en minúsculas y sin acentos)
CATEGORIAS = {
    "materiales_peligrosos": ["peligroso", "derrame", "fuga", "quimico", "inflamable", "toxico", "corrosivo"],
    "sobrepeso": ["sobrepeso", "excede", "bascula", "exceso de peso", "sobrecarga"],
    "acceso_no_autorizado": ["sin autorizacion", "no autorizado", "acceso denegado", "barrera", "intruso"],
    "falla_hardware": ["camara", "sensor", "lector", "rfid", "no enciende", "apagado", "danado", "falla electrica"],
    "falla_software": ["sistema", "error", "pantalla", "caido", "no carga", "lento", "software", "aplicacion"],
    "somnolencia_conductor": ["somnolencia", "dormido", "cansancio", "fatiga", "sueno"],
}

CATEGORIAS_VALIDAS = list(CATEGORIAS.keys()) + ["otro"]

# Palabras que elevan la prioridad un nivel
PALABRAS_URGENTES = ["urgente", "emergencia", "accidente", "incendio", "herido", "critico", "inmediato"]

PRIORIDAD_BASE = {
    "materiales_peligrosos": "critica",
    "somnolencia_conductor": "alta",
    "acceso_no_autorizado": "alta",
    "sobrepeso": "media",
    "falla_hardware": "media",
    "falla_software": "baja",
    "otro": "baja",
}

ORDEN_PRIORIDAD = ["baja", "media", "alta", "critica"]


def normalizar(texto):
    """Minúsculas y sin acentos/ñ para comparar palabras clave."""
    tabla = str.maketrans("áéíóúüñ", "aeiouun")
    return texto.lower().translate(tabla)


def clasificar(asunto, cuerpo):
    """Clasifica por conteo de palabras clave. Empate: gana la primera (seguridad)."""
    texto = normalizar(f"{asunto} {cuerpo}")

    puntajes = {cat: [kw for kw in kws if kw in texto] for cat, kws in CATEGORIAS.items()}
    mejor = max(puntajes, key=lambda c: len(puntajes[c]))

    if not puntajes[mejor]:
        mejor = "otro"
        coincidencias = []
    else:
        coincidencias = puntajes[mejor]

    prioridad = PRIORIDAD_BASE[mejor]
    urgentes = [p for p in PALABRAS_URGENTES if p in texto]
    if urgentes:
        indice = min(ORDEN_PRIORIDAD.index(prioridad) + 1, len(ORDEN_PRIORIDAD) - 1)
        prioridad = ORDEN_PRIORIDAD[indice]

    return {
        "categoria": mejor,
        "prioridad": prioridad,
        "palabras_clave": coincidencias + urgentes,
    }


def extraer_entidades(asunto, cuerpo):
    """Extrae placa, ID de camión, peso y ubicación. Lo que no aparece queda en None."""
    texto = f"{asunto}\n{cuerpo}"

    m_placa = re.search(r"\b[A-Z0-9]{2,3}-\d{2,3}-[A-Z0-9]{1,2}\b", texto.upper())
    m_camion = re.search(r"\bCAM-?\s?(\d+)\b", texto.upper())
    m_peso = re.search(r"(\d+(?:[.,]\d+)?)\s*(toneladas|tonelada|ton|t|kg)\b", texto.lower())
    m_ubic = re.search(r"\b(and[eé]n|puerta|muelle|caseta|dock)\s+([A-Za-z0-9]+)", texto, re.IGNORECASE)

    peso_kg = None
    if m_peso:
        valor = float(m_peso.group(1).replace(",", "."))
        peso_kg = valor if m_peso.group(2) == "kg" else valor * 1000

    return {
        "placa": m_placa.group(0) if m_placa else None,
        "camion_id": f"CAM-{m_camion.group(1)}" if m_camion else None,
        "peso_reportado_kg": peso_kg,
        "ubicacion": normalizar(f"{m_ubic.group(1)} {m_ubic.group(2)}").replace("anden", "andén") if m_ubic else None,
    }


def resumen_simple(asunto, cuerpo, limite=140):
    """Resumen de respaldo cuando no hay LLM: el asunto + inicio del cuerpo."""
    texto = f"{asunto.strip()}: {cuerpo.strip()}"
    return texto if len(texto) <= limite else texto[:limite - 3].rstrip() + "..."


def enviar_correo_soporte(remitente, destinatario, asunto, cuerpo, simulacion=True):
    """
    Envía el correo al equipo de soporte.
    simulacion=True: no se conecta a ningún servidor (modo por defecto).
    simulacion=False: usa SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD del entorno.
    """
    mensaje = EmailMessage()
    mensaje["From"] = remitente
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)

    if simulacion:
        log.info("Envío SIMULADO de correo a %s (asunto: %s)", destinatario, asunto)
        return {"enviado": True, "modo": "simulacion", "error": None}

    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=15) as servidor:
            servidor.starttls()
            servidor.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            servidor.send_message(mensaje)
        return {"enviado": True, "modo": "smtp", "error": None}
    except (KeyError, OSError, smtplib.SMTPException) as error:
        log.error("No se pudo enviar el correo: %s", error)
        return {"enviado": False, "modo": "smtp", "error": f"{type(error).__name__}: {error}"}


def correo_para_soporte(incidente):
    """Arma asunto y cuerpo del correo de soporte a partir del incidente."""
    asunto = f"[{incidente['prioridad'].upper()}] {incidente['categoria']} - {incidente.get('asunto', '')}"
    cuerpo = (
        f"Incidente reportado por: {incidente.get('remitente', '-')}\n"
        f"Categoría: {incidente['categoria']}\n"
        f"Prioridad: {incidente['prioridad']}\n"
        f"Requiere revisión humana: {'sí' if incidente.get('requiere_revision_humana') else 'no'}\n"
        f"Entidades: {json.dumps(incidente.get('entidades', {}), ensure_ascii=False)}\n\n"
        f"Mensaje original:\n{incidente.get('cuerpo', '')}"
    )
    return asunto, cuerpo
