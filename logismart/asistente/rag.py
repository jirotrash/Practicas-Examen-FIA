"""
Asistente explicativo con patrón RAG sencillo:

    1. CONSULTA PRIMERO: se buscan en MongoDB los registros relacionados
       con la pregunta (camión, placa, incidentes, accesos, riesgos).
    2. CONTEXTO DESPUÉS: solo esos registros se le pasan al LLM, con una
       etiqueta de referencia [coleccion#id] que debe citar.
    3. Si no se encontró nada, se responde "No tengo información" SIN
       llamar al LLM (así es imposible que invente).
"""

import re
from datetime import datetime, timedelta

from clasificador.reglas import normalizar
from db import repositorios
from db.conexion import ErrorBaseDatos, obtener_db
from llm import cliente
from llm.cliente import ErrorLLM

SIN_INFORMACION = "No tengo información sobre eso en la base de datos de LogiSmart."

PROMPT_SISTEMA = """Eres el asistente del centro de control LogiSmart.
Responde preguntas de los operadores usando ÚNICAMENTE los registros del CONTEXTO.

Reglas obligatorias:
1. No uses conocimiento externo ni supongas datos que no estén en el CONTEXTO.
2. Cita el registro de origen de cada dato con su etiqueta exacta, por ejemplo [accesos#a1b2c3].
3. Si el CONTEXTO no contiene la respuesta, responde exactamente: "No tengo información."
4. Para explicar decisiones de acceso, usa los campos "decision", "causa" y "explicacion".
5. Responde en español, breve y claro (máximo 6 oraciones)."""

PALABRAS_CATEGORIA = {
    "peligros": "materiales_peligrosos", "derrame": "materiales_peligrosos", "quimic": "materiales_peligrosos",
    "sobrepeso": "sobrepeso", "peso": "sobrepeso",
    "autoriz": "acceso_no_autorizado", "intruso": "acceso_no_autorizado",
    "hardware": "falla_hardware", "camara": "falla_hardware", "sensor": "falla_hardware",
    "software": "falla_software", "sistema": "falla_software",
    "somnolencia": "somnolencia_conductor", "dormido": "somnolencia_conductor", "fatiga": "somnolencia_conductor",
}


def _ref(coleccion, documento):
    return f"{coleccion}#{str(documento['_id'])[-6:]}"


def _fecha(valor):
    return valor.strftime("%d/%m/%Y %H:%M") if isinstance(valor, datetime) else str(valor)


# -----------------------------------------------------------------------------
# Conversión de documentos a texto para el contexto
# -----------------------------------------------------------------------------

def _texto_camion(c):
    vence = c.get("certificacion_vence")
    return (f"camion_id={c.get('camion_id')}, placa={c.get('placa')}, empresa={c.get('empresa')}, "
            f"autorizado={'sí' if c.get('autorizado') else 'no'}, "
            f"certificacion_vence={_fecha(vence) if vence else 'sin registro'}")


def _texto_acceso(a):
    premisas = ", ".join(f"{k}={'V' if v else 'F'}" for k, v in a.get("premisas", {}).items())
    return (f"fecha={_fecha(a.get('fecha'))}, camion_id={a.get('camion_id')}, placa={a.get('placa')}, "
            f"resultado={a.get('resultado')}, decision={a.get('decision')}, causa={a.get('causa')}, "
            f"premisas: {premisas}, explicacion: {' | '.join(a.get('explicacion', []))}, "
            f"operador={a.get('operador')}")


def _texto_incidente(i):
    return (f"fecha={_fecha(i.get('fecha'))}, asunto={i.get('asunto')}, categoria={i.get('categoria')}, "
            f"prioridad={i.get('prioridad')}, estado={i.get('estado')}, resumen={i.get('resumen')}, "
            f"entidades={i.get('entidades')}, requiere_revision_humana={i.get('requiere_revision_humana')}")


def _texto_riesgo(r):
    inh = (r.get("probabilidad") or 0) * (r.get("impacto") or 0)
    res = (r.get("probabilidad_residual") or 0) * (r.get("impacto_residual") or 0)
    return (f"modulo={r.get('modulo')}, riesgo={r.get('descripcion')}, categoria={r.get('categoria')}, "
            f"puntaje_inherente={inh}, puntaje_residual={res}, mitigacion={r.get('mitigacion')}")


# -----------------------------------------------------------------------------
# 1. Recuperación (consulta primero)
# -----------------------------------------------------------------------------

def recuperar(pregunta, limite=6):
    """Devuelve la lista de fuentes encontradas en MongoDB para la pregunta."""
    db = obtener_db()
    texto = normalizar(pregunta)
    fuentes = []
    vistos = set()

    def agregar(coleccion, documento, contenido):
        ref = _ref(coleccion, documento)
        if ref not in vistos:
            vistos.add(ref)
            fuentes.append({"ref": ref, "coleccion": coleccion, "id": str(documento["_id"]), "texto": contenido})

    # --- Camiones mencionados por ID o placa -------------------------------
    ids = {f"CAM-{n}" for n in re.findall(r"\bcam-?\s?(\d+)\b", texto)}
    placas = set(re.findall(r"\b[A-Z0-9]{2,3}-\d{2,3}-[A-Z0-9]{1,2}\b", pregunta.upper()))

    for identificador in list(ids) + list(placas):
        camion = repositorios.buscar_camion(identificador)
        filtro_ids = [identificador]
        if camion:
            agregar("camiones", camion, _texto_camion(camion))
            filtro_ids = [camion["camion_id"], camion["placa"]]

        consulta_accesos = {"$or": [{"camion_id": {"$in": filtro_ids}}, {"placa": {"$in": filtro_ids}}]}
        for acceso in db.accesos.find(consulta_accesos).sort("fecha", -1).limit(3):
            agregar("accesos", acceso, _texto_acceso(acceso))

        consulta_inc = {"$or": [{"entidades.camion_id": {"$in": filtro_ids}},
                                {"entidades.placa": {"$in": filtro_ids}}]}
        for incidente in db.incidentes.find(consulta_inc).sort("fecha", -1).limit(3):
            agregar("incidentes", incidente, _texto_incidente(incidente))

    # --- Preguntas generales por tema --------------------------------------
    if not ids and not placas:
        if "incidente" in texto or "correo" in texto or "reporte" in texto:
            filtro = {}
            if "abiert" in texto or "pendiente" in texto:
                filtro["estado"] = {"$in": ["nuevo", "en_atencion"]}
            if "revision" in texto or "humana" in texto:
                filtro["requiere_revision_humana"] = True
            if "critic" in texto:
                filtro["prioridad"] = "critica"
            for palabra, categoria in PALABRAS_CATEGORIA.items():
                if palabra in texto:
                    filtro["categoria"] = categoria
                    break
            for incidente in db.incidentes.find(filtro).sort("fecha", -1).limit(limite):
                agregar("incidentes", incidente, _texto_incidente(incidente))

        if "riesgo" in texto or "etic" in texto:
            riesgos = sorted(repositorios.listar_riesgos(),
                             key=lambda r: (r.get("probabilidad") or 0) * (r.get("impacto") or 0), reverse=True)
            for riesgo in riesgos[:limite]:
                agregar("riesgos_eticos", riesgo, _texto_riesgo(riesgo))

        if any(p in texto for p in ["acceso", "rechaz", "deneg", "inspeccion", "ingres", "entrad", "semaforo"]):
            filtro = {}
            if "hoy" in texto:
                inicio = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                filtro["fecha"] = {"$gte": inicio}
            elif "semana" in texto:
                filtro["fecha"] = {"$gte": datetime.now() - timedelta(days=7)}
            if "rechaz" in texto or "deneg" in texto:
                filtro["resultado"] = "rojo"
            elif "inspeccion" in texto:
                filtro["resultado"] = "amarillo"
            for acceso in db.accesos.find(filtro).sort("fecha", -1).limit(limite):
                agregar("accesos", acceso, _texto_acceso(acceso))

    return fuentes


# -----------------------------------------------------------------------------
# 2. Respuesta (contexto después)
# -----------------------------------------------------------------------------

def responder(pregunta, historial=None, ajustes=None):
    """
    Devuelve {"respuesta", "fuentes", "sin_datos", "latencia_ms", "error"}.
    historial: lista de mensajes previos [{"role": "user"/"assistant", "content": ...}]
    """
    try:
        fuentes = recuperar(pregunta)
    except ErrorBaseDatos as error:
        return {"respuesta": f"No pude consultar la base de datos: {error}", "fuentes": [],
                "sin_datos": True, "latencia_ms": 0, "error": True}

    if not fuentes:
        return {
            "respuesta": SIN_INFORMACION + " Puedo responder sobre un camión (ej. CAM-102 o su placa), "
                                           "accesos, incidentes o riesgos registrados.",
            "fuentes": [], "sin_datos": True, "latencia_ms": 0, "error": False,
        }

    contexto = "\n".join(f"[{f['ref']}] {f['texto']}" for f in fuentes)

    mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]
    for mensaje in (historial or [])[-4:]:
        mensajes.append(mensaje)
    mensajes.append({"role": "user", "content": f"CONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}"})

    try:
        respuesta, latencia, modelo = cliente.chat(mensajes, ajustes)
    except ErrorLLM as error:
        # Sin LLM, se muestran los datos crudos encontrados (no se inventa nada)
        return {"respuesta": "El LLM no está disponible. Estos son los registros encontrados:\n\n" + contexto,
                "fuentes": fuentes, "sin_datos": False, "latencia_ms": 0, "error": True, "detalle": str(error)}

    try:
        repositorios.registrar_evaluacion({
            "tipo": "asistente",
            "prompt": mensajes[-1]["content"],
            "respuesta": respuesta,
            "modelo": modelo,
            "latencia_ms": round(latencia, 1),
            "fuentes": [f["ref"] for f in fuentes],
            "cito_fuentes": any(f["ref"] in respuesta for f in fuentes),
            "coincidio_con_reglas": None,
        })
    except ErrorBaseDatos:
        pass

    return {"respuesta": respuesta.strip(), "fuentes": fuentes, "sin_datos": False,
            "latencia_ms": latencia, "error": False}
