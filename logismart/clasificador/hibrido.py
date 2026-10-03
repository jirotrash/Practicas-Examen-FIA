"""
Clasificador HÍBRIDO: combina reglas (palabras clave) y LLM.

Reglas de fusión:
    - Si el LLM falla (sin conexión o JSON inválido tras reintentar),
      se usa el clasificador por reglas (plan de respaldo).
    - Si LLM y reglas coinciden, se usa ese resultado.
    - Si discrepan, PREVALECE LA PRIORIDAD MÁS ALTA (ante la duda,
      seguridad) y se marca requiere_revision_humana = True.
    - Entidades: primero las del regex (deterministas); lo que el regex
      no encontró se completa con lo que extrajo el LLM.
"""

from datetime import datetime

from clasificador import reglas
from clasificador.llm import clasificar_con_llm
from clasificador.reglas import ORDEN_PRIORIDAD, PRIORIDAD_BASE
from db import repositorios
from db.conexion import ErrorBaseDatos


def _nivel(prioridad):
    return ORDEN_PRIORIDAD.index(prioridad)


def fusionar(res_reglas, res_llm):
    """Aplica las reglas de fusión. Devuelve (categoria, prioridad, revision, motivo)."""
    cat_r, pri_r = res_reglas["categoria"], res_reglas["prioridad"]
    cat_l, pri_l = res_llm["categoria"], res_llm["prioridad"]

    if cat_r == cat_l and pri_r == pri_l:
        return cat_l, pri_l, False, "LLM y reglas coinciden"

    # Discrepan: gana la prioridad más alta
    if _nivel(pri_l) > _nivel(pri_r):
        categoria, prioridad, ganador = cat_l, pri_l, "LLM"
    elif _nivel(pri_r) > _nivel(pri_l):
        categoria, prioridad, ganador = cat_r, pri_r, "reglas"
    else:
        # Misma prioridad y distinta categoría: la categoría de mayor riesgo base
        if _nivel(PRIORIDAD_BASE[cat_r]) > _nivel(PRIORIDAD_BASE[cat_l]):
            categoria, ganador = cat_r, "reglas"
        else:
            categoria, ganador = cat_l, "LLM"
        prioridad = pri_l

    motivo = (f"Discrepancia: reglas={cat_r}/{pri_r}, LLM={cat_l}/{pri_l}. "
              f"Se tomó {categoria}/{prioridad} ({ganador}, prioridad más alta)")
    return categoria, prioridad, True, motivo


def clasificar_incidente(remitente, asunto, cuerpo, ajustes=None, usar_llm=True, registrar=True,
                         tipo_registro="clasificacion"):
    """
    Clasifica un correo y devuelve el documento listo para guardarse en 'incidentes'.
    """
    ajustes = ajustes or {}

    res_reglas = reglas.clasificar(asunto, cuerpo)
    entidades = reglas.extraer_entidades(asunto, cuerpo)

    res_llm = clasificar_con_llm(asunto, cuerpo, ajustes) if usar_llm else None

    if res_llm and res_llm["ok"]:
        clasif_llm = res_llm["clasificacion"]
        categoria, prioridad, revision, motivo = fusionar(res_reglas, clasif_llm)
        fuente = "hibrido"
        resumen = clasif_llm["resumen"]

        # Completar entidades que el regex no encontró
        for campo, valor in clasif_llm["entidades"].items():
            if entidades.get(campo) is None and valor not in (None, ""):
                entidades[campo] = valor
    else:
        categoria = res_reglas["categoria"]
        prioridad = res_reglas["prioridad"]
        fuente = "reglas_respaldo" if usar_llm else "reglas"
        resumen = reglas.resumen_simple(asunto, cuerpo)
        # Si ni las reglas reconocen el correo, que lo revise una persona
        revision = categoria == "otro"
        if usar_llm:
            motivo = "LLM no disponible o JSON inválido: " + "; ".join(res_llm["errores"]) if res_llm else ""
        else:
            motivo = "Clasificado solo con reglas"

    # --- Registro en evaluaciones_llm ----------------------------------------
    if registrar and res_llm is not None:
        try:
            repositorios.registrar_evaluacion({
                "tipo": tipo_registro,
                "prompt": res_llm["prompt"],
                "respuesta": res_llm["respuesta"],
                "modelo": res_llm["modelo"],
                "latencia_ms": round(res_llm["latencia_ms"], 1),
                "json_valido": res_llm["ok"],
                "intentos": res_llm["intentos"],
                "errores": res_llm["errores"],
                "categoria_llm": res_llm["clasificacion"]["categoria"] if res_llm["ok"] else None,
                "categoria_reglas": res_reglas["categoria"],
                "coincidio_con_reglas": bool(res_llm["ok"]
                                             and res_llm["clasificacion"]["categoria"] == res_reglas["categoria"]
                                             and res_llm["clasificacion"]["prioridad"] == res_reglas["prioridad"]),
                "fecha": datetime.now(),
            })
        except ErrorBaseDatos:
            pass  # sin Mongo la clasificación sigue funcionando

    return {
        "remitente": remitente,
        "asunto": asunto,
        "cuerpo": cuerpo,
        "categoria": categoria,
        "prioridad": prioridad,
        "resumen": resumen,
        "entidades": entidades,
        "fuente_clasificacion": fuente,
        "requiere_revision_humana": revision,
        "motivo_revision": motivo,
        "detalle_clasificacion": {
            "reglas": res_reglas,
            "llm": res_llm["clasificacion"] if (res_llm and res_llm["ok"]) else None,
            "llm_intentos": res_llm["intentos"] if res_llm else 0,
            "llm_errores": res_llm["errores"] if res_llm else [],
            "llm_latencia_ms": round(res_llm["latencia_ms"], 1) if res_llm else 0,
            "modelo": res_llm["modelo"] if res_llm else None,
        },
    }
