"""
Carga datos de demostración en MongoDB.

Uso:
    python -m db.datos_demo              -> carga solo si la base está vacía
    python -m db.datos_demo --reiniciar  -> BORRA todo y vuelve a cargar

Todos los datos son FICTICIOS (empresas, conductores y placas inventados).
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
from clasificador import reglas as clasif_reglas  # noqa: E402
from db.conexion import obtener_db  # noqa: E402
from reglas import motor  # noqa: E402

# (camion_id, placa, empresa, autorizado, días para que venza la certificación, conductor ficticio)
CAMIONES = [
    ("CAM-101", "ABC-101-A", "Transportes del Valle", True, 200, "Conductor 01"),
    ("CAM-102", "ABC-123-D", "Químicos del Centro", True, 150, "Conductor 02"),
    ("CAM-103", "DEF-204-B", "Logística Toluca", True, 20, "Conductor 03"),
    ("CAM-104", "GHI-305-C", "Fletes Rápidos", False, 300, "Conductor 04"),
    ("CAM-105", "JKL-456-M", "Agroindustrias MX", True, -10, "Conductor 05"),
    ("CAM-118", "MNO-118-E", "Combustibles Lerma", True, 90, "Conductor 06"),
    ("CAM-120", "PQR-120-F", "Transportes del Valle", True, 60, "Conductor 07"),
    ("CAM-127", "STU-127-G", "Materiales Metepec", True, 400, "Conductor 08"),
    ("CAM-130", "VWX-130-H", "Químicos del Centro", True, 25, "Conductor 09"),
    ("CAM-133", "YZA-133-J", "Fletes Rápidos", True, 180, "Conductor 10"),
    ("CAM-141", "BCD-141-K", "Logística Toluca", True, 5, "Conductor 11"),
    ("CAM-150", "EFG-150-L", "Agroindustrias MX", True, 240, "Conductor 12"),
]

EMPRESAS_PELIGROSAS = {"Químicos del Centro", "Combustibles Lerma"}

RIESGOS = [
    {
        "modulo": "Clasificador LLM",
        "descripcion": "Alucinaciones del LLM: inventa categorías, placas o explicaciones sin respaldo",
        "categoria": "transparencia", "probabilidad": 4, "impacto": 4,
        "mitigacion": "Salida JSON validada con pydantic, reintento y respaldo por reglas; el asistente solo "
                      "usa registros de MongoDB, cita la fuente y responde 'No tengo información' sin datos",
        "probabilidad_residual": 2, "impacto_residual": 3,
    },
    {
        "modulo": "Clasificador de incidentes",
        "descripcion": "Sesgo contra correos con ortografía informal (las reglas fallan con 'derame', 'vascula')",
        "categoria": "sesgo", "probabilidad": 4, "impacto": 4,
        "mitigacion": "Clasificador híbrido (el LLM entiende variantes), revisión humana cuando LLM y reglas "
                      "discrepan y medición separada de exactitud en correos informales",
        "probabilidad_residual": 2, "impacto_residual": 3,
    },
    {
        "modulo": "Catálogo de camiones",
        "descripcion": "Privacidad de datos del conductor: nombre, certificación e historial de accesos",
        "categoria": "privacidad", "probabilidad": 3, "impacto": 4,
        "mitigacion": "Guardar solo lo necesario, acceso por rol, retención limitada, conexión cifrada (TLS) "
                      "a Atlas y no enviar datos personales al LLM fuera del contexto mínimo",
        "probabilidad_residual": 2, "impacto_residual": 3,
    },
    {
        "modulo": "Motor de decisiones",
        "descripcion": "Dependencia excesiva de la automatización: el operador acepta el semáforo sin verificar",
        "categoria": "responsabilidad", "probabilidad": 4, "impacto": 5,
        "mitigacion": "Explicación paso a paso visible en cada decisión, revisión humana obligatoria en amarillo "
                      "y rojo, registro del operador responsable y capacitación",
        "probabilidad_residual": 2, "impacto_residual": 4,
    },
    {
        "modulo": "Motor de reglas",
        "descripcion": "Falso negativo: carga peligrosa no declarada entra como acceso estándar",
        "categoria": "seguridad", "probabilidad": 3, "impacto": 5,
        "mitigacion": "Validar R con sensores y documentos (no solo con lo que captura el operador) e "
                      "inspecciones aleatorias",
        "probabilidad_residual": 2, "impacto_residual": 4,
    },
    {
        "modulo": "Clasificador LLM",
        "descripcion": "Inyección de instrucciones en el texto del correo para alterar la clasificación",
        "categoria": "seguridad", "probabilidad": 2, "impacto": 4,
        "mitigacion": "Formato JSON restringido por esquema, el LLM no ejecuta acciones y su resultado se "
                      "fusiona con las reglas (gana la prioridad más alta)",
        "probabilidad_residual": 1, "impacto_residual": 4,
    },
    {
        "modulo": "Regla B (horario restringido)",
        "descripcion": "El bloqueo nocturno afecta a transportistas con rutas que solo pueden llegar de noche",
        "categoria": "responsabilidad", "probabilidad": 3, "impacto": 2,
        "mitigacion": "Canal de excepción autorizado por supervisor y reprogramación prioritaria",
        "probabilidad_residual": 2, "impacto_residual": 2,
    },
    {
        "modulo": "Lector de placas (LPR)",
        "descripcion": "Lectura errónea de placas que niega el acceso injustificadamente",
        "categoria": "responsabilidad", "probabilidad": 3, "impacto": 3,
        "mitigacion": "Búsqueda manual por placa en la GUI, revisión humana y canal de apelación",
        "probabilidad_residual": 2, "impacto_residual": 2,
    },
]


def _crear_acceso(camion, momento, peso_kg, carga_peligrosa, ajustes, operador):
    premisas, detalle = motor.premisas_desde_camion(camion, peso_kg, carga_peligrosa, momento, ajustes)
    resultado = motor.evaluar(**premisas)
    return {
        "camion_id": camion["camion_id"],
        "placa": camion["placa"],
        "empresa": camion["empresa"],
        "peso_kg": peso_kg,
        "carga_peligrosa": carga_peligrosa,
        "premisas": resultado["premisas"],
        "detalle_premisas": detalle,
        "reglas": resultado["reglas"],
        "reglas_activadas": resultado["reglas_activadas"],
        "resultado": resultado["resultado"],
        "decision": resultado["decision"],
        "causa": resultado["causa"],
        "explicacion": resultado["explicacion"],
        "operador": operador,
        "origen": "busqueda_placa",
        "fecha": momento,
    }


def cargar(reiniciar=False):
    db = obtener_db()
    ajustes = config.cargar_config()
    azar = random.Random(42)  # semilla fija: siempre los mismos datos
    ahora = datetime.now()

    if reiniciar:
        for coleccion in ["camiones", "accesos", "incidentes", "riesgos_eticos", "evaluaciones_llm"]:
            db[coleccion].delete_many({})
        print("Colecciones vaciadas.")
    elif db.camiones.count_documents({}) > 0:
        mensaje = "La base ya tiene datos. Usa 'Reiniciar' (o --reiniciar) para borrar y volver a cargar."
        print(mensaje)
        return mensaje

    # --- Camiones --------------------------------------------------------------
    camiones = []
    for camion_id, placa, empresa, autorizado, dias, conductor in CAMIONES:
        camiones.append({
            "camion_id": camion_id, "placa": placa, "empresa": empresa, "autorizado": autorizado,
            "conductor": conductor,
            "certificacion_vence": (ahora + timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0),
            "fecha_alta": ahora - timedelta(days=60),
        })
    db.camiones.insert_many(camiones)

    # --- Accesos de las últimas 3 semanas ----------------------------------------
    accesos = []
    operadores = ["operador.caseta", "operador.norte", "operador.sur"]
    for dias_atras in range(21, 0, -1):
        for _ in range(azar.randint(3, 6)):
            camion = azar.choice(camiones)
            hora = azar.choice([2, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 23])
            momento = (ahora - timedelta(days=dias_atras)).replace(hour=hora, minute=azar.randint(0, 59))
            peso = azar.choice([azar.randint(22000, 38000)] * 4 + [azar.randint(41000, 52000)])
            peligrosa = camion["empresa"] in EMPRESAS_PELIGROSAS and azar.random() < 0.7
            accesos.append(_crear_acceso(camion, momento, float(peso), peligrosa, ajustes, azar.choice(operadores)))

    # Caso para la demo del asistente: "¿por qué CAM-102 fue enviado a inspección?"
    cam102 = next(c for c in camiones if c["camion_id"] == "CAM-102")
    # Siempre a las 10:15 (fuera del horario restringido): hoy si ya pasó esa hora, si no ayer
    momento = ahora.replace(hour=10, minute=15, second=0, microsecond=0)
    if momento > ahora:
        momento = momento - timedelta(days=1)
    accesos.append(_crear_acceso(cam102, momento, 31500.0, True, ajustes, "operador.caseta"))
    db.accesos.insert_many(accesos)

    # --- Incidentes (correos de ejemplo con su etiqueta revisada) ----------------
    correos = json.loads((RAIZ / "experimento" / "correos_etiquetados.json").read_text(encoding="utf-8"))
    azar.shuffle(correos)
    incidentes = []
    for numero, correo in enumerate(correos[:24]):
        fecha = ahora - timedelta(days=20 - numero * 0.85, hours=azar.randint(0, 8))
        dias = (ahora - fecha).days
        estado = "cerrado" if dias > 10 else ("en_atencion" if dias > 4 else "nuevo")
        reglas_res = clasif_reglas.clasificar(correo["asunto"], correo["cuerpo"])
        revision = reglas_res["categoria"] != correo["categoria"]
        incidentes.append({
            "remitente": correo["remitente"], "asunto": correo["asunto"], "cuerpo": correo["cuerpo"],
            "categoria": correo["categoria"], "prioridad": correo["prioridad"],
            "resumen": clasif_reglas.resumen_simple(correo["asunto"], correo["cuerpo"]),
            "entidades": clasif_reglas.extraer_entidades(correo["asunto"], correo["cuerpo"]),
            "fuente_clasificacion": "demo (etiqueta revisada)",
            "requiere_revision_humana": revision and estado != "cerrado",
            "motivo_revision": "Las reglas no coincidieron con la etiqueta revisada" if revision else "",
            "detalle_clasificacion": {"reglas": reglas_res, "llm": None},
            "estado": estado,
            "fecha": fecha,
            "historial": [{"fecha": fecha, "accion": "creado", "detalle": "dato de demostración",
                           "usuario": "sistema"}],
        })
    db.incidentes.insert_many(incidentes)

    # --- Riesgos éticos -----------------------------------------------------------
    for riesgo in RIESGOS:
        db.riesgos_eticos.insert_one({
            **riesgo, "fecha_alta": ahora - timedelta(days=7),
            "historico": [{"fecha": ahora - timedelta(days=7), "usuario": "equipo", "accion": "alta", "cambios": {}}],
        })

    mensaje = (f"Cargados: {len(camiones)} camiones, {len(accesos)} accesos, "
               f"{len(incidentes)} incidentes, {len(RIESGOS)} riesgos.")
    print(mensaje)
    return mensaje


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Carga datos de demostración en MongoDB")
    parser.add_argument("--reiniciar", action="store_true", help="borra las colecciones antes de cargar")
    cargar(parser.parse_args().reiniciar)
