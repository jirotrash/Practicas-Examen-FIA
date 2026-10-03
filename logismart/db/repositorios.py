"""
Repositorios: todas las operaciones CRUD sobre MongoDB.

Colecciones:
    camiones          -> catálogo de camiones y su conductor
    accesos           -> bitácora de decisiones del motor de reglas
    incidentes        -> correos de soporte clasificados
    riesgos_eticos    -> matriz de riesgos con histórico de cambios
    evaluaciones_llm  -> cada llamada al LLM (prompt, respuesta, latencia...)

Cualquier error de MongoDB se convierte en ErrorBaseDatos para que
la interfaz muestre un mensaje claro.
"""

from datetime import datetime
from functools import wraps

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

from db.conexion import ErrorBaseDatos, obtener_db

ESTADOS_INCIDENTE = ["nuevo", "en_atencion", "cerrado"]


# =============================================================================
# Utilidades
# =============================================================================

def _seguro(funcion):
    """Decorador: convierte errores de MongoDB en ErrorBaseDatos."""

    @wraps(funcion)
    def envoltura(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except ErrorBaseDatos:
            raise
        except DuplicateKeyError as error:
            raise ErrorBaseDatos("Ya existe un registro con ese identificador (placa o camion_id).") from error
        except PyMongoError as error:
            raise ErrorBaseDatos(f"Error al operar con MongoDB: {error}") from error

    return envoltura


def _oid(id_texto):
    """Convierte un id en texto a ObjectId (con error claro si es inválido)."""
    if isinstance(id_texto, ObjectId):
        return id_texto
    try:
        return ObjectId(str(id_texto))
    except InvalidId as error:
        raise ErrorBaseDatos(f"Identificador inválido: {id_texto}") from error


def _filtro_fechas(desde=None, hasta=None, campo="fecha"):
    """Arma el filtro de rango de fechas (ambos extremos opcionales)."""
    if desde is None and hasta is None:
        return {}
    rango = {}
    if desde is not None:
        rango["$gte"] = desde
    if hasta is not None:
        rango["$lte"] = hasta
    return {campo: rango}


# =============================================================================
# CAMIONES
# =============================================================================

@_seguro
def listar_camiones(texto=None):
    filtro = {}
    if texto:
        patron = {"$regex": texto, "$options": "i"}
        filtro = {"$or": [{"placa": patron}, {"camion_id": patron}, {"empresa": patron}]}
    return list(obtener_db().camiones.find(filtro).sort("camion_id", 1))


@_seguro
def buscar_camion(identificador):
    """Busca un camión por placa o por camion_id (sin importar mayúsculas)."""
    valor = identificador.strip().upper()
    return obtener_db().camiones.find_one({"$or": [{"placa": valor}, {"camion_id": valor}]})


@_seguro
def crear_camion(datos):
    datos = dict(datos)
    datos["placa"] = datos["placa"].strip().upper()
    datos["camion_id"] = datos["camion_id"].strip().upper()
    datos["fecha_alta"] = datetime.now()
    resultado = obtener_db().camiones.insert_one(datos)
    return resultado.inserted_id


@_seguro
def actualizar_camion(id_camion, datos):
    datos = dict(datos)
    datos.pop("_id", None)
    if "placa" in datos:
        datos["placa"] = datos["placa"].strip().upper()
    if "camion_id" in datos:
        datos["camion_id"] = datos["camion_id"].strip().upper()
    obtener_db().camiones.update_one({"_id": _oid(id_camion)}, {"$set": datos})


@_seguro
def eliminar_camion(id_camion):
    obtener_db().camiones.delete_one({"_id": _oid(id_camion)})


# =============================================================================
# ACCESOS (bitácora del motor de reglas)
# =============================================================================

@_seguro
def registrar_acceso(documento):
    documento = dict(documento)
    documento.setdefault("fecha", datetime.now())
    return obtener_db().accesos.insert_one(documento).inserted_id


@_seguro
def listar_accesos(desde=None, hasta=None, camion_id=None, limite=300):
    filtro = _filtro_fechas(desde, hasta)
    if camion_id:
        filtro["camion_id"] = camion_id
    return list(obtener_db().accesos.find(filtro).sort("fecha", DESCENDING).limit(limite))


@_seguro
def eliminar_acceso(id_acceso):
    obtener_db().accesos.delete_one({"_id": _oid(id_acceso)})


# =============================================================================
# INCIDENTES
# =============================================================================

@_seguro
def crear_incidente(documento, usuario="sistema"):
    documento = dict(documento)
    ahora = datetime.now()
    documento.setdefault("fecha", ahora)
    documento.setdefault("estado", "nuevo")
    documento["historial"] = [{
        "fecha": ahora,
        "accion": "creado",
        "detalle": f"Clasificado como {documento.get('categoria')} / {documento.get('prioridad')}",
        "usuario": usuario,
    }]
    return obtener_db().incidentes.insert_one(documento).inserted_id


@_seguro
def listar_incidentes(estado=None, desde=None, hasta=None, limite=300):
    filtro = _filtro_fechas(desde, hasta)
    if estado and estado != "todos":
        filtro["estado"] = estado
    return list(obtener_db().incidentes.find(filtro).sort("fecha", DESCENDING).limit(limite))


@_seguro
def obtener_incidente(id_incidente):
    return obtener_db().incidentes.find_one({"_id": _oid(id_incidente)})


@_seguro
def actualizar_incidente(id_incidente, cambios, usuario="operador", accion="editado"):
    """Actualiza campos y deja constancia en el historial."""
    cambios = dict(cambios)
    cambios.pop("_id", None)
    cambios.pop("historial", None)

    if "estado" in cambios and cambios["estado"] not in ESTADOS_INCIDENTE:
        raise ErrorBaseDatos(f"Estado inválido: {cambios['estado']}")

    detalle = ", ".join(f"{campo}={valor}" for campo, valor in cambios.items()
                        if not isinstance(valor, (dict, list)))

    obtener_db().incidentes.update_one(
        {"_id": _oid(id_incidente)},
        {
            "$set": cambios,
            "$push": {"historial": {
                "fecha": datetime.now(),
                "accion": accion,
                "detalle": detalle or "edición",
                "usuario": usuario,
            }},
        },
    )


@_seguro
def eliminar_incidente(id_incidente):
    obtener_db().incidentes.delete_one({"_id": _oid(id_incidente)})


@_seguro
def incidentes_por_categoria_semana(desde=None, hasta=None):
    """
    AGREGACIÓN: número de incidentes por categoría y semana ISO.

    Devuelve una lista como:
        [{"semana": "2026-W40", "categoria": "sobrepeso", "total": 3}, ...]
    """
    tuberia = []
    filtro = _filtro_fechas(desde, hasta)
    if filtro:
        tuberia.append({"$match": filtro})

    tuberia += [
        {"$group": {
            "_id": {
                "categoria": "$categoria",
                # %G = año ISO, %V = número de semana ISO (lunes a domingo)
                "semana": {"$dateToString": {"format": "%G-W%V", "date": "$fecha"}},
            },
            "total": {"$sum": 1},
        }},
        {"$project": {"_id": 0, "categoria": "$_id.categoria", "semana": "$_id.semana", "total": 1}},
        {"$sort": {"semana": 1, "categoria": 1}},
    ]
    return list(obtener_db().incidentes.aggregate(tuberia))


@_seguro
def incidentes_por_categoria(desde=None, hasta=None):
    """AGREGACIÓN: total de incidentes por categoría (para gráficas y RAG)."""
    tuberia = []
    filtro = _filtro_fechas(desde, hasta)
    if filtro:
        tuberia.append({"$match": filtro})
    tuberia += [
        {"$group": {"_id": "$categoria", "total": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]
    return [{"categoria": r["_id"], "total": r["total"]} for r in obtener_db().incidentes.aggregate(tuberia)]


# =============================================================================
# RIESGOS ÉTICOS
# =============================================================================

CAMPOS_RIESGO = ["modulo", "descripcion", "categoria", "probabilidad", "impacto",
                 "mitigacion", "probabilidad_residual", "impacto_residual"]


@_seguro
def listar_riesgos():
    return list(obtener_db().riesgos_eticos.find().sort("modulo", 1))


@_seguro
def crear_riesgo(datos, usuario="operador"):
    documento = {campo: datos.get(campo) for campo in CAMPOS_RIESGO}
    ahora = datetime.now()
    documento["fecha_alta"] = ahora
    documento["historico"] = [{"fecha": ahora, "usuario": usuario, "accion": "alta", "cambios": {}}]
    return obtener_db().riesgos_eticos.insert_one(documento).inserted_id


@_seguro
def actualizar_riesgo(id_riesgo, datos, usuario="operador"):
    """Actualiza el riesgo y guarda en 'historico' qué cambió (antes -> después)."""
    coleccion = obtener_db().riesgos_eticos
    actual = coleccion.find_one({"_id": _oid(id_riesgo)})
    if actual is None:
        raise ErrorBaseDatos("El riesgo ya no existe.")

    cambios = {}
    nuevos = {}
    for campo in CAMPOS_RIESGO:
        if campo in datos and datos[campo] != actual.get(campo):
            cambios[campo] = [actual.get(campo), datos[campo]]
            nuevos[campo] = datos[campo]

    if not nuevos:
        return

    coleccion.update_one(
        {"_id": _oid(id_riesgo)},
        {
            "$set": nuevos,
            "$push": {"historico": {"fecha": datetime.now(), "usuario": usuario,
                                    "accion": "edicion", "cambios": cambios}},
        },
    )


@_seguro
def eliminar_riesgo(id_riesgo):
    obtener_db().riesgos_eticos.delete_one({"_id": _oid(id_riesgo)})


# =============================================================================
# EVALUACIONES DEL LLM
# =============================================================================

@_seguro
def registrar_evaluacion(documento):
    documento = dict(documento)
    documento.setdefault("fecha", datetime.now())
    return obtener_db().evaluaciones_llm.insert_one(documento).inserted_id


@_seguro
def listar_evaluaciones(tipo=None, limite=200):
    filtro = {"tipo": tipo} if tipo else {}
    return list(obtener_db().evaluaciones_llm.find(filtro).sort("fecha", DESCENDING).limit(limite))


# =============================================================================
# INDICADORES DEL PANEL DE CONTROL
# =============================================================================

@_seguro
def indicadores(desde=None, hasta=None):
    """Indicadores principales filtrados por fecha."""
    db = obtener_db()
    filtro = _filtro_fechas(desde, hasta)

    accesos = list(db.accesos.find(filtro, {"camion_id": 1, "resultado": 1}))
    camiones_distintos = {a.get("camion_id") for a in accesos if a.get("camion_id")}

    abiertos = db.incidentes.count_documents({**filtro, "estado": {"$in": ["nuevo", "en_atencion"]}})
    revision = db.incidentes.count_documents({**filtro, "requiere_revision_humana": True,
                                              "estado": {"$ne": "cerrado"}})

    # Riesgos críticos: puntaje inherente (probabilidad x impacto) >= 17
    criticos = 0
    criticos_residual = 0
    for riesgo in db.riesgos_eticos.find():
        if (riesgo.get("probabilidad") or 0) * (riesgo.get("impacto") or 0) >= 17:
            criticos += 1
        if (riesgo.get("probabilidad_residual") or 0) * (riesgo.get("impacto_residual") or 0) >= 17:
            criticos_residual += 1

    return {
        "accesos_registrados": len(accesos),
        "camiones_atendidos": len(camiones_distintos),
        "accesos_verde": sum(1 for a in accesos if a.get("resultado") == "verde"),
        "accesos_amarillo": sum(1 for a in accesos if a.get("resultado") == "amarillo"),
        "accesos_rojo": sum(1 for a in accesos if a.get("resultado") == "rojo"),
        "incidentes_abiertos": abiertos,
        "incidentes_revision_humana": revision,
        "riesgos_criticos": criticos,
        "riesgos_criticos_residual": criticos_residual,
    }
