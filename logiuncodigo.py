#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 LogiSmart  -  Centro de control inteligente (versión en un solo archivo)
==============================================================================
Evolución de logiuncodigo.py: aplicación con persistencia en MongoDB, un LLM
local (Ollama) que apoya la clasificación y la explicación de decisiones, y
una interfaz gráfica de escritorio (Flet).

El código está organizado por SECCIONES que siguen una arquitectura por capas:

  Datos        -> secciones 1 a 3   (configuración, conexión y repositorios)
  Dominio      -> secciones 4 a 11  (PEAS, reglas, clasificadores, asistente, riesgos)
  Servicios    -> secciones 12 a 16 (gráficas, exportación, datos demo, experimento)
  Presentación -> secciones 17 a 27 (interfaz gráfica: 9 pantallas)
  Pruebas      -> sección 28        (incluye las pruebas del script original)

Uso:
  python3 logismart.py                  -> abre la aplicación de escritorio
  python3 logismart.py --demo           -> carga datos de demostración en MongoDB
  python3 logismart.py --demo --reiniciar
  python3 logismart.py --experimento    -> experimento reglas vs LLM vs híbrido
  python3 logismart.py --tests          -> pruebas unitarias
  python3 logismart.py --tablas         -> tablas de verdad, análisis de reglas y PEAS

Requisitos: pip install -r requirements.txt  (Ollama con llama3.2 y MongoDB)
==============================================================================
"""

# -----------------------------------------------------------------------------
# IMPORTACIONES
# -----------------------------------------------------------------------------
import argparse
import asyncio
import copy
import csv
import io
import itertools
import json
import logging
import os
import random
import re
import smtplib
import statistics
import sys
import time
import unittest
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from typing import Literal, Optional
from unittest import mock

import matplotlib

matplotlib.use("Agg")  # las gráficas se generan como imágenes, sin ventana propia
import matplotlib.pyplot as plt  # noqa: E402

import flet as ft  # noqa: E402
import ollama  # noqa: E402
from bson import ObjectId  # noqa: E402
from bson.errors import InvalidId  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fpdf import FPDF  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, ValidationError  # noqa: E402
from pymongo import DESCENDING, MongoClient  # noqa: E402
from pymongo.errors import DuplicateKeyError, PyMongoError  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
# Oculta mensajes internos de librerías (peticiones HTTP a Ollama y recorte de fuentes del PDF)
for _ruidoso in ("httpx", "fontTools"):
    logging.getLogger(_ruidoso).setLevel(logging.WARNING)


# =============================================================================
# SECCIÓN 1: CONFIGURACIÓN
# =============================================================================
# Configuración central de LogiSmart.
#
# Dos fuentes de configuración:
#
# 1. Archivo .env  -> datos de conexión que NO se suben a Git
#    (cadena de MongoDB, host de Ollama).
#
# 2. Archivo config.json -> ajustes que el usuario cambia desde la
#    pantalla "Configuración" (modelo de Ollama, umbrales, modo
#    simulación de correo). Si no existe, se usan los valores por defecto.

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

# Carpeta de fuentes de matplotlib (DejaVu Sans): la interfaz la usa como carpeta de recursos
CARPETA_FUENTES = Path(matplotlib.get_data_path()) / "fonts" / "ttf"

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


# =============================================================================
# SECCIÓN 2: CONEXIÓN A MONGODB
# =============================================================================
# Conexión a MongoDB (local o Atlas).
#
# Toda la aplicación obtiene la base de datos con obtener_db().
# Si MongoDB no responde se lanza ErrorBaseDatos con un mensaje
# claro, para que la interfaz lo muestre sin "tronar".

class ErrorBaseDatos(Exception):
    """Error de conexión u operación con MongoDB, con mensaje amigable."""


_cliente_mongo = None
_db = None


def obtener_db():
    """Devuelve la base de datos; crea la conexión la primera vez."""
    global _cliente_mongo, _db

    if _db is not None:
        return _db

    try:
        # serverSelectionTimeoutMS: si en 4 s no responde, se da por caído
        _cliente_mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=4000)
        _cliente_mongo.admin.command("ping")
        _db = _cliente_mongo[MONGO_DB]
        crear_indices(_db)
        return _db
    except PyMongoError as error:
        _cliente_mongo = None
        _db = None
        raise ErrorBaseDatos(
            "No se pudo conectar a MongoDB. Verifica que el servicio esté "
            f"encendido y la cadena MONGO_URI del archivo .env.\nDetalle: {error}"
        ) from error


def verificar_conexion():
    """Devuelve (True, mensaje) si hay conexión o (False, mensaje de error)."""
    try:
        db = obtener_db()
        db.client.admin.command("ping")
        destino = "Atlas" if "mongodb.net" in MONGO_URI else "local"
        return True, f"MongoDB {destino} · base '{MONGO_DB}'"
    except (ErrorBaseDatos, PyMongoError) as error:
        reiniciar_conexion()
        return False, str(error)


def reiniciar_conexion():
    """Olvida la conexión actual (para reintentar después de un error)."""
    global _cliente_mongo, _db
    _cliente_mongo = None
    _db = None


def usar_db_de_pruebas(db):
    """Permite inyectar una base simulada (mongomock) en las pruebas."""
    global _db
    _db = db


def crear_indices(db):
    """Índices para que las búsquedas frecuentes sean rápidas."""
    db.camiones.create_index("camion_id", unique=True)
    db.camiones.create_index("placa", unique=True)
    db.accesos.create_index([("fecha", -1)])
    db.accesos.create_index("camion_id")
    db.incidentes.create_index([("fecha", -1)])
    db.incidentes.create_index("estado")


# =============================================================================
# SECCIÓN 3: REPOSITORIOS (CRUD Y AGREGACIONES)
# =============================================================================
# Repositorios: todas las operaciones CRUD sobre MongoDB.
#
# Colecciones:
#     camiones          -> catálogo de camiones y su conductor
#     accesos           -> bitácora de decisiones del motor de reglas
#     incidentes        -> correos de soporte clasificados
#     riesgos_eticos    -> matriz de riesgos con histórico de cambios
#     evaluaciones_llm  -> cada llamada al LLM (prompt, respuesta, latencia...)
#
# Cualquier error de MongoDB se convierte en ErrorBaseDatos para que
# la interfaz muestre un mensaje claro.

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


# =============================================================================
# SECCIÓN 4: MARCO PEAS
# =============================================================================
# Diseño PEAS del agente LogiSmart (sección 1 del script original).
#
# P = medida de desempeño, E = entorno, A = actuadores, S = sensores.
# Se agregan los nuevos componentes de software de esta versión.

PEAS_LOGISMART = {
    "agente": "Agente de control inteligente de acceso y seguridad logística LogiSmart",
    "P_desempeno": [
        "Tiempo promedio de atención por camión (minutos) -> minimizar",
        "% de camiones autorizados que ingresan sin fricción -> maximizar",
        "% de camiones no autorizados / con sobrepeso detenidos -> maximizar (meta 100%)",
        "Falsos positivos de inspección especial -> minimizar",
        "Falsos negativos (carga peligrosa que no fue inspeccionada) -> minimizar (meta 0)",
        "Incidentes de seguridad y accidentes en patio -> minimizar",
        "Tiempo de clasificación y respuesta a incidentes de soporte -> minimizar",
    ],
    "E_entorno": {
        "descripcion": "Patio de maniobras, casetas de acceso, básculas y andenes del centro logístico",
        "propiedades": {
            "observabilidad": "Parcialmente observable (sensores con ruido, mala visión nocturna)",
            "determinismo": "Estocástico (llegadas, clima y fallas impredecibles)",
            "episodico": "Secuencial (una decisión afecta el tráfico posterior)",
            "dinamico": "Dinámico (el entorno cambia mientras el agente decide)",
            "discreto": "Mixto (estados discretos de acceso; peso y posición continuos)",
            "agentes": "Multiagente (conductores, personal, otros sistemas)",
        },
        "actores_externos": ["Conductores", "Operadores de caseta", "Personal de seguridad", "Autoridades"],
    },
    "A_actuadores": [
        "Barrera vehicular (abrir / cerrar)",
        "Semáforo y pantallas de instrucciones al conductor",
        "Alarma sonora y luminosa",
        "Sistema de asignación de andén / carril de inspección especial",
        "Notificaciones (correo, SMS, panel) a supervisores y soporte",
        "Registro en base de datos (bitácora de accesos e incidentes)",
    ],
    "S_sensores": [
        "Cámaras con lector de placas (LPR) y cámara de somnolencia del conductor",
        "Báscula de piso (peso del vehículo)",
        "Lector RFID / QR de autorización previa",
        "Escáner de documentos (certificación del conductor)",
        "Sensores de detección de materiales peligrosos / lectura de placas de riesgo (NOM)",
        "Buzón de correo de soporte (entrada de texto de incidentes)",
    ],
}

# Elementos nuevos de esta versión (arquitectura modular)
PEAS_LOGISMART["S_sensores"].append("Base de datos MongoDB (historial de accesos, incidentes y riesgos)")
PEAS_LOGISMART["A_actuadores"].append("Asistente LLM que explica decisiones citando registros de MongoDB")
PEAS_LOGISMART["P_desempeno"].append("Exactitud del clasificador híbrido de incidentes -> maximizar")


def peas_como_texto(peas=PEAS_LOGISMART):
    lineas = [f"Agente: {peas['agente']}", "", "P (Medidas de desempeño):"]
    lineas += [f"   - {x}" for x in peas["P_desempeno"]]
    entorno = peas["E_entorno"]
    lineas += ["", f"E (Entorno): {entorno['descripcion']}"]
    lineas += [f"   - {k}: {v}" for k, v in entorno["propiedades"].items()]
    lineas += ["", "A (Actuadores):"] + [f"   - {x}" for x in peas["A_actuadores"]]
    lineas += ["", "S (Sensores):"] + [f"   - {x}" for x in peas["S_sensores"]]
    return "\n".join(lineas)


# =============================================================================
# SECCIÓN 5: MOTOR DE REGLAS (LÓGICA PROPOSICIONAL)
# =============================================================================
# Motor de reglas de LogiSmart (lógica proposicional).
#
# PREMISAS
#     P : el vehículo tiene autorización previa
#     Q : el peso excede el límite
#     R : lleva materiales peligrosos
#     S : el conductor tiene certificación vigente
#     H : es horario restringido (por defecto 22:00 a 06:00)     <- nueva
#     T : la certificación vence en 30 días o menos              <- nueva
#
# REGLAS ORIGINALES
#     A (Acceso estándar)      = P ∧ S ∧ ¬Q
#     E (Inspección especial)  = P ∧ (R ∨ Q)
#
# REGLAS NUEVAS
#     B (Bloqueo por horario)  = R ∧ H
#         Los materiales peligrosos no ingresan en horario nocturno:
#         hay menos personal de seguridad, menor visibilidad y la
#         respuesta ante un derrame es más lenta. Se reprograma la cita.
#
#     V (Aviso de renovación)  = S ∧ T
#         La certificación sigue vigente pero está por vencer: se permite
#         el paso y se avisa para renovarla antes de que el conductor sea
#         rechazado.
#
# PRIORIDAD AL DECIDIR (de mayor a menor; ante la duda, seguridad)
#     1. ¬P        -> ROJO     (sin autorización no se evalúa nada más)
#     2. B         -> ROJO     (bloqueo por horario)
#     3. E         -> AMARILLO (inspección especial)
#     4. A         -> VERDE    (acceso estándar; con aviso si V)
#     5. otro caso -> ROJO     (autorizado pero sin certificación vigente)

# Descripción de cada premisa (para las explicaciones)
PREMISAS = {
    "P": "autorización previa",
    "Q": "peso excede el límite",
    "R": "materiales peligrosos",
    "S": "certificación del conductor vigente",
    "H": "horario restringido",
    "T": "certificación por vencer (≤ 30 días)",
}

ORDEN_PREMISAS = ["P", "Q", "R", "S", "H", "T"]

# Definición de las reglas: variables que usa, fórmula y función
REGLAS = {
    "A": {
        "nombre": "Acceso estándar",
        "formula": "P ∧ S ∧ ¬Q",
        "variables": ["P", "Q", "S"],
        "nueva": False,
        "funcion": lambda v: v["P"] and v["S"] and not v["Q"],
    },
    "E": {
        "nombre": "Inspección especial",
        "formula": "P ∧ (R ∨ Q)",
        "variables": ["P", "Q", "R"],
        "nueva": False,
        "funcion": lambda v: v["P"] and (v["R"] or v["Q"]),
    },
    "B": {
        "nombre": "Bloqueo por horario restringido",
        "formula": "R ∧ H",
        "variables": ["R", "H"],
        "nueva": True,
        "funcion": lambda v: v["R"] and v["H"],
    },
    "V": {
        "nombre": "Aviso de renovación de certificación",
        "formula": "S ∧ T",
        "variables": ["S", "T"],
        "nueva": True,
        "funcion": lambda v: v["S"] and v["T"],
    },
}


def _vf(valor):
    return "V" if valor else "F"


# =============================================================================
# EVALUACIÓN
# =============================================================================

def evaluar_reglas(P, Q, R, S, H=False, T=False):
    """
    Evalúa todas las reglas y devuelve la decisión con su explicación.

    Retorna un diccionario con:
        premisas, reglas (A, E, B, V), resultado (verde/amarillo/rojo),
        decision (texto), reglas_activadas y explicacion (lista de pasos).
    """
    premisas = {"P": P, "Q": Q, "R": R, "S": S, "H": H, "T": T}

    # Validación defensiva: solo booleanos estrictos
    for nombre, valor in premisas.items():
        if not isinstance(valor, bool):
            raise TypeError(f"La premisa {nombre} debe ser bool, se recibió {type(valor).__name__}")

    reglas = {clave: regla["funcion"](premisas) for clave, regla in REGLAS.items()}
    A, E, B, V = reglas["A"], reglas["E"], reglas["B"], reglas["V"]

    # --- Explicación paso a paso --------------------------------------------
    explicacion = []
    explicacion.append("Premisas: " + ", ".join(
        f"{p}={_vf(premisas[p])} ({PREMISAS[p]})" for p in ORDEN_PREMISAS))

    explicacion.append(f"A = P ∧ S ∧ ¬Q = {_vf(P)} ∧ {_vf(S)} ∧ {_vf(not Q)} = {_vf(A)}")
    explicacion.append(f"E = P ∧ (R ∨ Q) = {_vf(P)} ∧ ({_vf(R)} ∨ {_vf(Q)}) = {_vf(E)}")
    explicacion.append(f"B = R ∧ H = {_vf(R)} ∧ {_vf(H)} = {_vf(B)}")
    explicacion.append(f"V = S ∧ T = {_vf(S)} ∧ {_vf(T)} = {_vf(V)}")

    # --- Decisión según prioridad --------------------------------------------
    avisos = []

    if not P:
        resultado = "rojo"
        decision = "Acceso denegado: el vehículo no tiene autorización previa"
        causa = "P es falsa (prioridad 1)"
    elif B:
        resultado = "rojo"
        decision = "Acceso denegado: carga peligrosa en horario restringido; reprogramar cita"
        causa = "B = R ∧ H es verdadera (prioridad 2, regla nueva)"
    elif E:
        resultado = "amarillo"
        motivos = []
        if R:
            motivos.append("materiales peligrosos")
        if Q:
            motivos.append("exceso de peso")
        decision = "Enviar a inspección especial por " + " y ".join(motivos)
        causa = "E = P ∧ (R ∨ Q) es verdadera (prioridad 3)"
        if A:
            avisos.append("A también es verdadera, pero la inspección especial tiene prioridad (seguridad)")
        if not S:
            avisos.append("El conductor no tiene certificación vigente: retener hasta validarla")
    elif A:
        resultado = "verde"
        decision = "Acceso estándar autorizado"
        causa = "A = P ∧ S ∧ ¬Q es verdadera (prioridad 4)"
    else:
        resultado = "rojo"
        decision = "Acceso denegado: el conductor no tiene certificación vigente"
        causa = "P es verdadera pero S es falsa y no aplica inspección (prioridad 5)"

    if V:
        avisos.append("Aviso: la certificación del conductor vence pronto; solicitar renovación (regla V)")

    advertencias = validar_premisas(premisas)

    explicacion.append(f"Decisión: {decision}. Causa: {causa}.")
    explicacion.extend(avisos)
    explicacion.extend(advertencias)

    return {
        "premisas": premisas,
        "reglas": reglas,
        "resultado": resultado,
        "decision": decision,
        "causa": causa,
        "avisos": avisos,
        "advertencias": advertencias,
        "reglas_activadas": [clave for clave, valor in reglas.items() if valor],
        "explicacion": explicacion,
    }


def validar_premisas(premisas):
    """
    Detecta combinaciones de premisas que no pueden ocurrir en la realidad.

    T (por vencer en ≤ 30 días) implica que la certificación sigue vigente (S).
    Si T es verdadera y S falsa, los datos de entrada se contradicen.
    """
    advertencias = []
    if premisas.get("T") and not premisas.get("S"):
        advertencias.append(
            "Advertencia: T=V y S=F se contradicen (una certificación 'por vencer' sigue vigente). "
            "Revisa los datos del conductor."
        )
    return advertencias


# =============================================================================
# OBTENER PREMISAS A PARTIR DE DATOS REALES
# =============================================================================

def es_horario_restringido(hora, inicio=22, fin=6):
    """True si la hora (0-23) cae en el horario restringido (puede cruzar medianoche)."""
    if inicio <= fin:
        return inicio <= hora < fin
    return hora >= inicio or hora < fin


def premisas_desde_camion(camion, peso_kg, carga_peligrosa, momento=None, config=None):
    """
    Calcula P, Q, R, S, H, T a partir del registro del camión en MongoDB
    y de lo que captura el operador (peso y tipo de carga).
    Devuelve (premisas, detalle) donde detalle explica de dónde salió cada una.
    """
    config = config or {}
    momento = momento or datetime.now()
    limite = config.get("peso_limite_kg", 40000)
    dias_aviso = config.get("dias_aviso_certificacion", 30)

    P = bool(camion.get("autorizado", False))

    Q = float(peso_kg) > float(limite)
    R = bool(carga_peligrosa)

    vence = camion.get("certificacion_vence")
    if isinstance(vence, datetime):
        vence = vence.date()
    hoy = momento.date() if isinstance(momento, datetime) else date.today()

    if vence is None:
        S = False
        T = False
        dias_restantes = None
    else:
        dias_restantes = (vence - hoy).days
        S = dias_restantes >= 0
        T = 0 <= dias_restantes <= dias_aviso

    H = es_horario_restringido(momento.hour,
                               config.get("hora_restringida_inicio", 22),
                               config.get("hora_restringida_fin", 6))

    detalle = {
        "P": "Autorizado en el catálogo de camiones" if P else "Sin autorización en el catálogo",
        "Q": f"Peso {peso_kg:,.0f} kg vs límite {limite:,.0f} kg",
        "R": "El operador indicó carga peligrosa" if R else "Carga normal",
        "S": ("Sin fecha de certificación registrada" if vence is None
              else f"Certificación vence el {vence:%d/%m/%Y} ({dias_restantes} días)"),
        "H": f"Hora de llegada {momento:%H:%M}",
        "T": (f"Faltan {dias_restantes} días (aviso a {dias_aviso})" if dias_restantes is not None
              else "Sin fecha"),
    }
    return {"P": P, "Q": Q, "R": R, "S": S, "H": H, "T": T}, detalle


# =============================================================================
# TABLAS DE VERDAD
# =============================================================================

def tabla_verdad(clave):
    """Tabla de verdad de una sola regla (solo con sus variables)."""
    regla = REGLAS[clave]
    filas = []
    for valores in itertools.product([True, False], repeat=len(regla["variables"])):
        v = dict(zip(regla["variables"], valores))
        # Las variables que la regla no usa no afectan; se rellenan con False
        completo = {p: v.get(p, False) for p in ORDEN_PREMISAS}
        filas.append({**v, clave: regla["funcion"](completo)})
    return filas


def tabla_original():
    """Tabla de 16 filas (P, Q, R, S) con columnas intermedias, A y E."""
    filas = []
    for P, Q, R, S in itertools.product([True, False], repeat=4):
        resultado = evaluar_reglas(P, Q, R, S)
        filas.append({
            "P": P, "Q": Q, "R": R, "S": S,
            "no_Q": not Q, "P_y_S": P and S, "R_o_Q": R or Q,
            "A": resultado["reglas"]["A"], "E": resultado["reglas"]["E"],
        })
    return filas


def tabla_completa():
    """Las 64 combinaciones de las 6 premisas con todas las reglas y la decisión."""
    filas = []
    for valores in itertools.product([True, False], repeat=6):
        premisas = dict(zip(ORDEN_PREMISAS, valores))
        resultado = evaluar_reglas(**premisas)
        filas.append({**premisas, **resultado["reglas"], "resultado": resultado["resultado"]})
    return filas


def tabla_como_texto(clave):
    """Tabla de verdad en texto (para el informe y la consola)."""
    regla = REGLAS[clave]
    columnas = regla["variables"] + [clave]
    lineas = [f"{clave} = {regla['formula']}  ({regla['nombre']})",
              " ".join(f"{c:^3}" for c in columnas),
              "-" * (4 * len(columnas))]
    for fila in tabla_verdad(clave):
        lineas.append(" ".join(f"{_vf(fila[c]):^3}" for c in columnas))
    return "\n".join(lineas)


# =============================================================================
# RETO OPCIONAL: CONTRADICCIONES Y REDUNDANCIAS
# =============================================================================

def analizar_reglas():
    """
    Recorre las 64 combinaciones y detecta:

    - Conflictos: dos reglas con acciones opuestas verdaderas a la vez
      (por ejemplo A permite el paso y B lo bloquea). Se resuelven con la
      prioridad del motor y aquí se documenta cuántas veces ocurre.
    - Implicaciones: si siempre que X es verdadera también lo es Y
      (X ⇒ Y). Indica dependencia/redundancia entre reglas.
    - Reglas que nunca deciden: reglas que son verdaderas pero cuya acción
      queda siempre opacada por otra de mayor prioridad.
    - Combinaciones imposibles de premisas (T ∧ ¬S).
    """
    tabla = tabla_completa()
    total = len(tabla)

    pares_opuestos = [
        ("A", "B", "A permite el acceso y B lo bloquea", "prevalece B (seguridad)"),
        ("A", "E", "A permite acceso estándar y E exige inspección", "prevalece E (seguridad)"),
    ]

    conflictos = []
    for x, y, descripcion, resolucion in pares_opuestos:
        casos = [f for f in tabla if f[x] and f[y]]
        if casos:
            ejemplo = {p: casos[0][p] for p in ORDEN_PREMISAS}
            conflictos.append({
                "reglas": f"{x} y {y}",
                "descripcion": descripcion,
                "casos": len(casos),
                "ejemplo": ", ".join(f"{p}={_vf(v)}" for p, v in ejemplo.items()),
                "resolucion": resolucion,
            })

    implicaciones = []
    claves = list(REGLAS.keys())
    for x in claves:
        for y in claves + ["P", "Q", "R", "S", "H", "T"]:
            if x == y:
                continue
            casos_x = [f for f in tabla if f[x]]
            if casos_x and all(f[y] for f in casos_x):
                implicaciones.append(f"{x} ⇒ {y}")

    # ¿Cuántas veces cada regla "decide" el resultado final?
    decide = {"A": 0, "E": 0, "B": 0, "V": 0}
    for fila in tabla:
        if not fila["P"]:
            continue
        if fila["B"]:
            decide["B"] += 1
        elif fila["E"]:
            decide["E"] += 1
        elif fila["A"]:
            decide["A"] += 1

    imposibles = sum(1 for f in tabla if f["T"] and not f["S"])

    return {
        "total_combinaciones": total,
        "veces_verdadera": {c: sum(1 for f in tabla if f[c]) for c in REGLAS},
        "veces_que_decide": decide,
        "conflictos": conflictos,
        "implicaciones": implicaciones,
        "combinaciones_imposibles": imposibles,
        "nota_V": "V no decide el color del semáforo: solo agrega un aviso (no compite con otras reglas).",
    }


# =============================================================================
# SECCIÓN 6: CLASIFICADOR POR REGLAS
# =============================================================================
# Clasificador de incidentes por REGLAS (palabras clave) + extracción con regex.
#
# Es el clasificador del script original. Se conserva tal cual porque:
# - funciona sin LLM (plan de respaldo), y
# - sirve de línea base en el experimento (reglas vs LLM vs híbrido).

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


def clasificar_por_reglas(asunto, cuerpo):
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


# =============================================================================
# SECCIÓN 7: CLIENTE DEL LLM (OLLAMA)
# =============================================================================
# Cliente del LLM local (Ollama).
#
# Centraliza las llamadas al modelo para medir la latencia de cada una
# y manejar los errores de conexión en un solo lugar.

class ErrorLLM(Exception):
    """Ollama no responde o el modelo no existe."""


def _cliente_ollama():
    return ollama.Client(host=OLLAMA_HOST, timeout=180)


def chat_llm(mensajes, ajustes=None, formato=None):
    """
    Envía la conversación al modelo.

    formato: None para texto libre, o un esquema JSON (dict) para obligar
             al modelo a responder con esa estructura (structured outputs).

    Devuelve (texto_respuesta, latencia_ms, modelo).
    """
    ajustes = ajustes or cargar_config()
    modelo = ajustes.get("modelo_ollama", "llama3.2")
    opciones = {
        "temperature": ajustes.get("temperatura", 0.1),
        "num_ctx": ajustes.get("num_ctx", 4096),
    }

    inicio = time.perf_counter()
    try:
        respuesta = _cliente_ollama().chat(model=modelo, messages=mensajes, format=formato, options=opciones)
    except ollama.ResponseError as error:
        raise ErrorLLM(f"Ollama respondió con error ({error.status_code}): {error.error}") from error
    except Exception as error:  # conexión rechazada, tiempo agotado, etc.
        raise ErrorLLM(f"No se pudo conectar con Ollama en {OLLAMA_HOST}: {error}") from error

    latencia_ms = (time.perf_counter() - inicio) * 1000
    return respuesta["message"]["content"], latencia_ms, modelo


def listar_modelos():
    """Nombres de los modelos descargados en Ollama (para la pantalla de configuración)."""
    try:
        respuesta = _cliente_ollama().list()
        return sorted(m["model"] for m in respuesta["models"])
    except Exception:
        return []


def verificar_ollama():
    """Devuelve (True, mensaje) si Ollama responde, o (False, error)."""
    try:
        modelos = _cliente_ollama().list()["models"]
        return True, f"Ollama activo · {len(modelos)} modelo(s)"
    except Exception as error:
        return False, f"Ollama no responde en {OLLAMA_HOST}: {error}"


# =============================================================================
# SECCIÓN 8: CLASIFICADOR CON LLM
# =============================================================================
# Clasificador de incidentes con LLM (salida JSON validada con pydantic).
#
# Flujo:
#     1. Se manda el correo al LLM pidiendo un JSON con el esquema EXACTO
#        (categoria, prioridad, entidades, resumen). Además se le pasa el
#        esquema a Ollama con `format=` para restringir su salida.
#     2. Se valida la respuesta con pydantic.
#     3. Si el JSON es inválido, se reintenta diciéndole al modelo cuál fue
#        el error. Si vuelve a fallar (o Ollama no responde), quien llama
#        usa el clasificador por reglas como respaldo.

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


PROMPT_CLASIFICADOR = """Eres el clasificador de incidentes del centro logístico LogiSmart.
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
        {"role": "system", "content": PROMPT_CLASIFICADOR},
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
            respuesta, latencia, modelo = chat_llm(
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


# =============================================================================
# SECCIÓN 9: CLASIFICADOR HÍBRIDO
# =============================================================================
# Clasificador HÍBRIDO: combina reglas (palabras clave) y LLM.
#
# Reglas de fusión:
#     - Si el LLM falla (sin conexión o JSON inválido tras reintentar),
#       se usa el clasificador por reglas (plan de respaldo).
#     - Si LLM y reglas coinciden, se usa ese resultado.
#     - Si discrepan, PREVALECE LA PRIORIDAD MÁS ALTA (ante la duda,
#       seguridad) y se marca requiere_revision_humana = True.
#     - Entidades: primero las del regex (deterministas); lo que el regex
#       no encontró se completa con lo que extrajo el LLM.

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

    res_reglas = clasificar_por_reglas(asunto, cuerpo)
    entidades = extraer_entidades(asunto, cuerpo)

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
        resumen = resumen_simple(asunto, cuerpo)
        # Si ni las reglas reconocen el correo, que lo revise una persona
        revision = categoria == "otro"
        if usar_llm:
            motivo = "LLM no disponible o JSON inválido: " + "; ".join(res_llm["errores"]) if res_llm else ""
        else:
            motivo = "Clasificado solo con reglas"

    # --- Registro en evaluaciones_llm ----------------------------------------
    if registrar and res_llm is not None:
        try:
            registrar_evaluacion({
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


# =============================================================================
# SECCIÓN 10: ASISTENTE EXPLICATIVO (RAG)
# =============================================================================
# Asistente explicativo con patrón RAG sencillo:
#
#     1. CONSULTA PRIMERO: se buscan en MongoDB los registros relacionados
#        con la pregunta (camión, placa, incidentes, accesos, riesgos).
#     2. CONTEXTO DESPUÉS: solo esos registros se le pasan al LLM, con una
#        etiqueta de referencia [coleccion#id] que debe citar.
#     3. Si no se encontró nada, se responde "No tengo información" SIN
#        llamar al LLM (así es imposible que invente).

SIN_INFORMACION = "No tengo información sobre eso en la base de datos de LogiSmart."

PROMPT_ASISTENTE = """Eres el asistente del centro de control LogiSmart.
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

def recuperar_fuentes(pregunta, limite=6):
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
        camion = buscar_camion(identificador)
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
            riesgos = sorted(listar_riesgos(),
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

def responder_asistente(pregunta, historial=None, ajustes=None):
    """
    Devuelve {"respuesta", "fuentes", "sin_datos", "latencia_ms", "error"}.
    historial: lista de mensajes previos [{"role": "user"/"assistant", "content": ...}]
    """
    try:
        fuentes = recuperar_fuentes(pregunta)
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

    mensajes = [{"role": "system", "content": PROMPT_ASISTENTE}]
    for mensaje in (historial or [])[-4:]:
        mensajes.append(mensaje)
    mensajes.append({"role": "user", "content": f"CONTEXTO:\n{contexto}\n\nPREGUNTA: {pregunta}"})

    try:
        respuesta, latencia, modelo = chat_llm(mensajes, ajustes)
    except ErrorLLM as error:
        # Sin LLM, se muestran los datos crudos encontrados (no se inventa nada)
        return {"respuesta": "El LLM no está disponible. Estos son los registros encontrados:\n\n" + contexto,
                "fuentes": fuentes, "sin_datos": False, "latencia_ms": 0, "error": True, "detalle": str(error)}

    try:
        registrar_evaluacion({
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


# =============================================================================
# SECCIÓN 11: MATRIZ DE RIESGOS ÉTICOS
# =============================================================================
# Matriz de riesgos éticos.
#
# Puntaje = probabilidad (1-5) x impacto (1-5)  -> rango 1..25
#     1-4 bajo | 5-9 medio | 10-16 alto | 17-25 crítico
#
# Riesgo residual: el mismo cálculo DESPUÉS de aplicar la mitigación
# (probabilidad_residual x impacto_residual).

CATEGORIAS_RIESGO = ["sesgo", "privacidad", "transparencia", "seguridad", "responsabilidad", "otro"]

NIVELES = [
    (17, "crítico", "#D32F2F"),
    (10, "alto", "#F57C00"),
    (5, "medio", "#FBC02D"),
    (1, "bajo", "#388E3C"),
]


def puntaje_riesgo(probabilidad, impacto):
    return int(probabilidad or 0) * int(impacto or 0)


def nivel_riesgo(valor):
    for minimo, nombre, _ in NIVELES:
        if valor >= minimo:
            return nombre
    return "bajo"


def color_nivel(valor):
    for minimo, _, color in NIVELES:
        if valor >= minimo:
            return color
    return "#388E3C"


def validar_riesgo(datos):
    """Devuelve una lista de errores (vacía si todo está bien)."""
    errores = []
    if not str(datos.get("modulo", "")).strip():
        errores.append("El módulo es obligatorio.")
    if not str(datos.get("descripcion", "")).strip():
        errores.append("La descripción es obligatoria.")
    if datos.get("categoria") not in CATEGORIAS_RIESGO:
        errores.append(f"Categoría inválida. Usa una de: {', '.join(CATEGORIAS_RIESGO)}.")
    for campo in ["probabilidad", "impacto", "probabilidad_residual", "impacto_residual"]:
        valor = datos.get(campo)
        if not isinstance(valor, int) or isinstance(valor, bool) or not 1 <= valor <= 5:
            errores.append(f"'{campo.replace('_', ' ')}' debe ser un entero de 1 a 5.")
    if not errores:
        if puntaje_riesgo(datos["probabilidad_residual"], datos["impacto_residual"]) > puntaje_riesgo(datos["probabilidad"], datos["impacto"]):
            errores.append("El riesgo residual no puede ser mayor que el inherente (la mitigación no debe empeorarlo).")
    return errores


def enriquecer_riesgo(riesgo):
    """Agrega puntajes, niveles y reducción (%) a un documento de riesgo."""
    inherente = puntaje_riesgo(riesgo.get("probabilidad"), riesgo.get("impacto"))
    residual = puntaje_riesgo(riesgo.get("probabilidad_residual"), riesgo.get("impacto_residual"))
    reduccion = round(100 * (inherente - residual) / inherente, 1) if inherente else 0
    return {
        **riesgo,
        "puntaje_inherente": inherente,
        "nivel_inherente": nivel_riesgo(inherente),
        "puntaje_residual": residual,
        "nivel_residual": nivel_riesgo(residual),
        "reduccion_pct": reduccion,
    }


def resumen_riesgos(riesgos):
    """Estadísticas de la matriz."""
    enriquecidos = [enriquecer_riesgo(r) for r in riesgos]
    por_nivel = {"crítico": 0, "alto": 0, "medio": 0, "bajo": 0}
    por_nivel_residual = {"crítico": 0, "alto": 0, "medio": 0, "bajo": 0}
    for r in enriquecidos:
        por_nivel[r["nivel_inherente"]] += 1
        por_nivel_residual[r["nivel_residual"]] += 1
    total_inh = sum(r["puntaje_inherente"] for r in enriquecidos)
    total_res = sum(r["puntaje_residual"] for r in enriquecidos)
    return {
        "total": len(enriquecidos),
        "por_nivel": por_nivel,
        "por_nivel_residual": por_nivel_residual,
        "promedio_inherente": round(total_inh / len(enriquecidos), 1) if enriquecidos else 0,
        "promedio_residual": round(total_res / len(enriquecidos), 1) if enriquecidos else 0,
        "reduccion_total_pct": round(100 * (total_inh - total_res) / total_inh, 1) if total_inh else 0,
    }


# =============================================================================
# SECCIÓN 12: GRÁFICAS
# =============================================================================
# Gráficas con matplotlib (se devuelven como PNG en bytes).
#
# Se usan en la interfaz (como imagen) y en el reporte PDF.
# Colores: paleta categórica validada para daltonismo (orden fijo) y
# colores de estado reservados para niveles de riesgo y semáforo.

# Paleta categórica (orden fijo) para superficie clara y oscura
CATEGORICA = {
    False: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    True: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
# Colores de estado (bueno, advertencia, serio, crítico)
ESTADO = {"verde": "#0ca30c", "amarillo": "#fab219", "naranja": "#ec835a", "rojo": "#d03b3b"}

SUPERFICIE = {False: "#fcfcfb", True: "#1a1a19"}
TEXTO = {False: "#0b0b0b", True: "#ffffff"}
TEXTO_2 = {False: "#52514e", True: "#c3c2b7"}
REJILLA = {False: "#e4e3df", True: "#333331"}

# Orden fijo de categorías: el color sigue a la categoría, no a su posición
ORDEN_CATEGORIAS = ["materiales_peligrosos", "sobrepeso", "acceso_no_autorizado", "falla_hardware",
                    "falla_software", "somnolencia_conductor", "otro"]


def _figura(ancho=8, alto=4.2, oscuro=True):
    fig, ax = plt.subplots(figsize=(ancho, alto), dpi=110)
    fig.patch.set_facecolor(SUPERFICIE[oscuro])
    ax.set_facecolor(SUPERFICIE[oscuro])
    for lado in ["top", "right"]:
        ax.spines[lado].set_visible(False)
    for lado in ["left", "bottom"]:
        ax.spines[lado].set_color(REJILLA[oscuro])
    ax.tick_params(colors=TEXTO_2[oscuro], labelsize=9)
    ax.yaxis.label.set_color(TEXTO_2[oscuro])
    ax.xaxis.label.set_color(TEXTO_2[oscuro])
    return fig, ax


def _a_png(fig):
    buffer = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buffer.getvalue()


def _sin_datos(mensaje, oscuro=True):
    fig, ax = _figura(oscuro=oscuro)
    ax.axis("off")
    ax.text(0.5, 0.5, mensaje, ha="center", va="center", color=TEXTO_2[oscuro], fontsize=12)
    return _a_png(fig)


# =============================================================================
# Incidentes por categoría y semana (agregación)
# =============================================================================

def incidentes_por_semana(datos, oscuro=True):
    """datos: salida de repositorios.incidentes_por_categoria_semana()."""
    if not datos:
        return _sin_datos("Sin incidentes en el periodo", oscuro)

    semanas = sorted({d["semana"] for d in datos})
    presentes = [c for c in ORDEN_CATEGORIAS if any(d["categoria"] == c for d in datos)]

    fig, ax = _figura(oscuro=oscuro)
    base = [0] * len(semanas)
    colores = CATEGORICA[oscuro]

    for categoria in presentes:
        valores = [sum(d["total"] for d in datos if d["semana"] == s and d["categoria"] == categoria)
                   for s in semanas]
        color = colores[ORDEN_CATEGORIAS.index(categoria) % len(colores)]
        ax.bar(semanas, valores, bottom=base, color=color, width=0.55, label=categoria.replace("_", " "),
               edgecolor=SUPERFICIE[oscuro], linewidth=2)
        base = [b + v for b, v in zip(base, valores)]

    for x, total in enumerate(base):
        ax.text(x, total + 0.1, str(total), ha="center", va="bottom", color=TEXTO[oscuro], fontsize=9)

    ax.set_ylabel("Incidentes")
    ax.set_ylim(0, max(base) * 1.2 + 0.5)
    ax.set_title("Incidentes por categoría y semana", color=TEXTO[oscuro], fontsize=11, loc="left")
    ax.grid(axis="y", color=REJILLA[oscuro], linewidth=0.6)
    ax.set_axisbelow(True)
    leyenda = ax.legend(fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    for texto in leyenda.get_texts():
        texto.set_color(TEXTO_2[oscuro])
    return _a_png(fig)


# =============================================================================
# Semáforo de accesos
# =============================================================================

def accesos_por_resultado(indicadores, oscuro=True):
    etiquetas = ["Verde (acceso)", "Amarillo (inspección)", "Rojo (denegado)"]
    valores = [indicadores.get("accesos_verde", 0), indicadores.get("accesos_amarillo", 0),
               indicadores.get("accesos_rojo", 0)]
    if sum(valores) == 0:
        return _sin_datos("Sin accesos en el periodo", oscuro)

    fig, ax = _figura(ancho=6, alto=3.4, oscuro=oscuro)
    colores = [ESTADO["verde"], ESTADO["amarillo"], ESTADO["rojo"]]
    barras = ax.barh(etiquetas, valores, color=colores, height=0.55)
    for barra, valor in zip(barras, valores):
        ax.text(barra.get_width() + 0.2, barra.get_y() + barra.get_height() / 2, str(valor),
                va="center", color=TEXTO[oscuro], fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Decisiones")
    ax.set_title("Resultado del motor de reglas", color=TEXTO[oscuro], fontsize=11, loc="left")
    ax.grid(axis="x", color=REJILLA[oscuro], linewidth=0.6)
    ax.set_axisbelow(True)
    return _a_png(fig)


# =============================================================================
# Matriz de riesgos (probabilidad x impacto) con riesgo residual
# =============================================================================

def matriz_riesgos(riesgos, oscuro=True):
    """Mapa 5x5: círculo lleno = inherente, círculo hueco = residual, flecha = mitigación."""
    fig, ax = _figura(ancho=6.4, alto=5.2, oscuro=oscuro)

    # Fondo por nivel de riesgo
    for p in range(1, 6):
        for i in range(1, 6):
            ax.add_patch(plt.Rectangle((i - 0.5, p - 0.5), 1, 1, color=color_nivel(p * i),
                                       alpha=0.22, linewidth=0))
            ax.text(i + 0.38, p - 0.38, str(p * i), fontsize=7, color=TEXTO_2[oscuro], ha="right")

    # Posiciones repetidas: se desplazan un poco para que no se encimen
    ocupados = {}
    for numero, riesgo in enumerate(riesgos, start=1):
        pi, ii = riesgo["probabilidad"], riesgo["impacto"]
        pr, ir = riesgo["probabilidad_residual"], riesgo["impacto_residual"]
        desfase = ocupados.get((pi, ii), 0) * 0.16
        ocupados[(pi, ii)] = ocupados.get((pi, ii), 0) + 1
        desfase_r = ocupados.get((pr, ir), 0) * 0.16
        ocupados[(pr, ir)] = ocupados.get((pr, ir), 0) + 1

        x1, y1 = ii - 0.25 + desfase, pi + 0.2 - desfase
        x2, y2 = ir - 0.25 + desfase_r, pr + 0.2 - desfase_r
        if (x1, y1) != (x2, y2):
            ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                        arrowprops=dict(arrowstyle="->", color=TEXTO_2[oscuro], lw=1))
        ax.scatter([x1], [y1], s=150, color=color_nivel(pi * ii), edgecolors=SUPERFICIE[oscuro],
                   linewidths=2, zorder=3)
        ax.text(x1, y1, str(numero), ha="center", va="center", fontsize=7, color="#ffffff",
                zorder=4, fontweight="bold")
        ax.scatter([x2], [y2], s=110, facecolors="none", edgecolors=TEXTO[oscuro], linewidths=1.4, zorder=3)
        ax.text(x2, y2, str(numero), ha="center", va="center", fontsize=6, color=TEXTO[oscuro], zorder=4)

    ax.set_xlim(0.5, 5.5)
    ax.set_ylim(0.5, 5.5)
    ax.set_xticks(range(1, 6))
    ax.set_yticks(range(1, 6))
    ax.set_xlabel("Impacto")
    ax.set_ylabel("Probabilidad")
    ax.set_title("Matriz de riesgos  ● inherente  ○ residual", color=TEXTO[oscuro], fontsize=11, loc="left")
    ax.set_aspect("equal")
    return _a_png(fig)


def riesgo_antes_despues(riesgos, oscuro=True):
    """Barras horizontales: puntaje inherente vs residual por riesgo."""
    if not riesgos:
        return _sin_datos("Sin riesgos registrados", oscuro)

    enriquecidos = [enriquecer_riesgo(r) for r in riesgos]
    etiquetas = [f"{n}. {r['descripcion'][:34]}" for n, r in enumerate(enriquecidos, start=1)]
    inherentes = [r["puntaje_inherente"] for r in enriquecidos]
    residuales = [r["puntaje_residual"] for r in enriquecidos]

    alto = max(3.2, 0.42 * len(riesgos) + 1.2)
    fig, ax = _figura(ancho=8, alto=alto, oscuro=oscuro)
    posiciones = list(range(len(riesgos)))
    colores = CATEGORICA[oscuro]
    ax.barh([p - 0.2 for p in posiciones], inherentes, height=0.38, color=colores[0], label="Inherente")
    ax.barh([p + 0.2 for p in posiciones], residuales, height=0.38, color=colores[1], label="Residual")
    for p, (a, b) in enumerate(zip(inherentes, residuales)):
        ax.text(a + 0.2, p - 0.2, str(a), va="center", fontsize=8, color=TEXTO[oscuro])
        ax.text(b + 0.2, p + 0.2, str(b), va="center", fontsize=8, color=TEXTO[oscuro])
    ax.axvline(17, color=ESTADO["rojo"], linewidth=1, linestyle="--")
    ax.text(17.2, -0.75, "crítico ≥ 17", color=TEXTO_2[oscuro], fontsize=8)
    ax.set_yticks(posiciones)
    ax.set_yticklabels(etiquetas, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 26)
    ax.set_xlabel("Puntaje (probabilidad × impacto)")
    ax.set_title("Riesgo antes y después de la mitigación", color=TEXTO[oscuro], fontsize=11, loc="left")
    leyenda = ax.legend(fontsize=8, frameon=False, loc="lower right")
    for texto in leyenda.get_texts():
        texto.set_color(TEXTO_2[oscuro])
    return _a_png(fig)


# =============================================================================
# Matriz de confusión (experimento de clasificación)
# =============================================================================

def grafica_matriz_confusion(matriz_valores, etiquetas, titulo, oscuro=False):
    """matriz_valores[i][j] = correos de la clase real i predichos como j."""
    rampa = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"]
    fig, ax = _figura(ancho=6.6, alto=5.4, oscuro=oscuro)
    maximo = max(max(fila) for fila in matriz_valores) or 1
    n = len(etiquetas)
    for i in range(n):
        for j in range(n):
            valor = matriz_valores[i][j]
            if valor == 0:
                color = SUPERFICIE[oscuro]
            else:
                color = rampa[min(len(rampa) - 1, int(valor / maximo * (len(rampa) - 1)))]
            ax.add_patch(plt.Rectangle((j, n - 1 - i), 1, 1, color=color, ec=REJILLA[oscuro]))
            if valor:
                oscuro_celda = rampa.index(color) >= 3
                ax.text(j + 0.5, n - 1 - i + 0.5, str(valor), ha="center", va="center", fontsize=9,
                        color="#ffffff" if oscuro_celda else "#0b0b0b")
    cortas = [e.replace("materiales_peligrosos", "mat_pelig").replace("somnolencia_conductor", "somnolencia")
               .replace("acceso_no_autorizado", "acceso_no_aut") for e in etiquetas]
    ax.set_xlim(0, n)
    ax.set_ylim(0, n)
    ax.set_xticks([k + 0.5 for k in range(n)])
    ax.set_xticklabels(cortas, rotation=45, ha="right", fontsize=8)
    ax.set_yticks([k + 0.5 for k in range(n)])
    ax.set_yticklabels(list(reversed(cortas)), fontsize=8)
    ax.set_xlabel("Predicción")
    ax.set_ylabel("Etiqueta real")
    ax.set_title(titulo, color=TEXTO[oscuro], fontsize=11, loc="left")
    ax.set_aspect("equal")
    return _a_png(fig)


# =============================================================================
# SECCIÓN 13: EXPORTACIÓN (CSV, JSON, PDF)
# =============================================================================
# Exportación de reportes a CSV, JSON y PDF.
#
# Los archivos se guardan en la carpeta exportaciones/ del proyecto.

# Fuente con soporte de acentos y símbolos (viene incluida con matplotlib)
FUENTE_TTF = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
FUENTE_TTF_NEGRITA = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"


def _carpeta():
    CARPETA_EXPORTACIONES.mkdir(parents=True, exist_ok=True)
    return CARPETA_EXPORTACIONES


def _sello():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _serializar(valor):
    """Convierte fechas y ObjectId a texto para JSON/CSV."""
    if isinstance(valor, datetime):
        return valor.isoformat(timespec="seconds")
    if isinstance(valor, ObjectId):
        return str(valor)
    return str(valor)


def aplanar(documento, prefijo=""):
    """{'a': {'b': 1}} -> {'a.b': 1}. Las listas se unen con ' | '."""
    plano = {}
    for clave, valor in documento.items():
        nombre = f"{prefijo}{clave}"
        if isinstance(valor, dict):
            plano.update(aplanar(valor, nombre + "."))
        elif isinstance(valor, list):
            plano[nombre] = " | ".join(
                json.dumps(v, ensure_ascii=False, default=_serializar) if isinstance(v, dict) else str(v)
                for v in valor
            )
        elif isinstance(valor, (datetime, ObjectId)):
            plano[nombre] = _serializar(valor)
        else:
            plano[nombre] = valor
    return plano


def exportar_csv(nombre, documentos):
    ruta = _carpeta() / f"{nombre}_{_sello()}.csv"
    filas = [aplanar(d) for d in documentos]
    columnas = []
    for fila in filas:
        for columna in fila:
            if columna not in columnas:
                columnas.append(columna)
    # utf-8-sig para que Excel muestre bien los acentos
    with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas or ["sin_datos"])
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def exportar_json(nombre, datos):
    ruta = _carpeta() / f"{nombre}_{_sello()}.json"
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=2, default=_serializar)
    return ruta


# =============================================================================
# PDF
# =============================================================================

class _PDF(FPDF):
    def header(self):
        self.set_font("DejaVu", "B", 9)
        self.set_text_color(110, 110, 110)
        self.cell(0, 6, "LogiSmart · Centro de control inteligente", align="L")
        self.cell(0, 6, datetime.now().strftime("%d/%m/%Y %H:%M"), align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", "", 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 6, f"Página {self.page_no()}", align="C")


def _titulo(pdf, texto):
    pdf.ln(3)
    pdf.set_font("DejaVu", "B", 13)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 8, texto, new_x="LMARGIN", new_y="NEXT")


def _tabla(pdf, encabezados, filas, anchos):
    pdf.set_font("DejaVu", "B", 8)
    pdf.set_fill_color(230, 236, 245)
    pdf.set_text_color(20, 20, 20)
    for encabezado, ancho in zip(encabezados, anchos):
        pdf.cell(ancho, 6, encabezado, border=1, fill=True)
    pdf.ln()
    pdf.set_font("DejaVu", "", 7.5)
    for fila in filas:
        if pdf.get_y() > 270:
            pdf.add_page()
        for valor, ancho in zip(fila, anchos):
            texto = str(valor) if valor is not None else "-"
            # recorta para que quepa en la celda
            while pdf.get_string_width(texto) > ancho - 2 and len(texto) > 3:
                texto = texto[:-4] + "…"
            pdf.cell(ancho, 5.5, texto, border=1)
        pdf.ln()


def reporte_pdf(indicadores, accesos, incidentes, riesgos, imagenes=None, periodo="Todo el historial"):
    """
    Genera el reporte general en PDF.
    imagenes: lista de PNG (bytes) con las gráficas a incluir.
    """
    pdf = _PDF()
    pdf.add_font("DejaVu", "", str(FUENTE_TTF))
    pdf.add_font("DejaVu", "B", str(FUENTE_TTF_NEGRITA))
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(0, 10, "Reporte de operación LogiSmart", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("DejaVu", "", 10)
    pdf.cell(0, 6, f"Periodo: {periodo}", new_x="LMARGIN", new_y="NEXT")

    _titulo(pdf, "Indicadores")
    datos = [
        ("Camiones atendidos", indicadores.get("camiones_atendidos", 0)),
        ("Decisiones de acceso registradas", indicadores.get("accesos_registrados", 0)),
        ("Verde / Amarillo / Rojo", f"{indicadores.get('accesos_verde', 0)} / "
                                    f"{indicadores.get('accesos_amarillo', 0)} / {indicadores.get('accesos_rojo', 0)}"),
        ("Incidentes abiertos", indicadores.get("incidentes_abiertos", 0)),
        ("Incidentes que requieren revisión humana", indicadores.get("incidentes_revision_humana", 0)),
        ("Riesgos críticos (inherente / residual)", f"{indicadores.get('riesgos_criticos', 0)} / "
                                                     f"{indicadores.get('riesgos_criticos_residual', 0)}"),
    ]
    _tabla(pdf, ["Indicador", "Valor"], datos, [120, 60])

    for imagen in imagenes or []:
        if pdf.get_y() > 190:
            pdf.add_page()
        pdf.ln(3)
        pdf.image(io.BytesIO(imagen), w=175)

    pdf.add_page()
    _titulo(pdf, "Últimas decisiones de acceso")
    filas = [(a.get("fecha").strftime("%d/%m %H:%M") if isinstance(a.get("fecha"), datetime) else a.get("fecha"),
              a.get("camion_id"), a.get("placa"), a.get("resultado"), a.get("decision"))
             for a in accesos[:25]]
    _tabla(pdf, ["Fecha", "Camión", "Placa", "Semáforo", "Decisión"], filas, [22, 20, 25, 18, 105])

    _titulo(pdf, "Incidentes")
    filas = [(i.get("fecha").strftime("%d/%m %H:%M") if isinstance(i.get("fecha"), datetime) else i.get("fecha"),
              i.get("categoria"), i.get("prioridad"), i.get("estado"),
              "sí" if i.get("requiere_revision_humana") else "no", i.get("asunto"))
             for i in incidentes[:25]]
    _tabla(pdf, ["Fecha", "Categoría", "Prioridad", "Estado", "Revisión", "Asunto"], filas, [22, 38, 18, 20, 15, 77])

    _titulo(pdf, "Matriz de riesgos éticos")
    filas = []
    for n, r in enumerate([enriquecer_riesgo(r) for r in riesgos], start=1):
        filas.append((n, r.get("modulo"), r.get("descripcion"), r.get("categoria"),
                      f"{r['puntaje_inherente']} ({r['nivel_inherente']})",
                      f"{r['puntaje_residual']} ({r['nivel_residual']})"))
    _tabla(pdf, ["#", "Módulo", "Riesgo", "Categoría", "Inherente", "Residual"], filas, [8, 34, 70, 24, 27, 27])

    ruta = _carpeta() / f"reporte_logismart_{_sello()}.pdf"
    pdf.output(str(ruta))
    return ruta


# =============================================================================
# SECCIÓN 14: CORREOS ETIQUETADOS
# =============================================================================
# 36 correos etiquetados a mano para el experimento y los datos de demostración.
# Campos: id, remitente, asunto, cuerpo, categoria y prioridad reales, informal (ortografía informal) y nota.

CORREOS_ETIQUETADOS = [
    {"id": 1, "remitente": "operador.caseta@logismart.example", "asunto": "Derrame de químico en andén 3", "cuerpo": "El camión CAM-102 con placas ABC-123-D presenta fuga de químico inflamable. Se requiere apoyo inmediato.", "categoria": "materiales_peligrosos", "prioridad": "critica", "informal": False, "nota": "caso base del script original"},
    {"id": 2, "remitente": "seguridad@logismart.example", "asunto": "Olor fuerte a gasolina en patio", "cuerpo": "Se percibe olor a combustible cerca del CAM-118, parece que el tanque gotea sobre el piso.", "categoria": "materiales_peligrosos", "prioridad": "critica", "informal": False, "nota": "sinónimos sin palabra clave"},
    {"id": 3, "remitente": "muelle2@logismart.example", "asunto": "Tambo de ácido volcado", "cuerpo": "En el muelle 2 se cayó un tambo de ácido sulfúrico de la unidad con placas JKL-456-M. Nadie está herido pero el área huele muy fuerte.", "categoria": "materiales_peligrosos", "prioridad": "critica", "informal": False, "nota": "ácido no está en las palabras clave"},
    {"id": 4, "remitente": "turno.noche@logismart.example", "asunto": "ai un derame en el anden 1!!", "cuerpo": "urjente el CAM-130 esta tirando liquido raro y huele feo, vengan pronto", "categoria": "materiales_peligrosos", "prioridad": "critica", "informal": True, "nota": "ortografía informal"},
    {"id": 5, "remitente": "recepcion@logismart.example", "asunto": "Validación de hoja de seguridad", "cuerpo": "El CAM-145 lleva material corrosivo clase 8. ¿Alguien puede validar la hoja de seguridad antes de descargar?", "categoria": "materiales_peligrosos", "prioridad": "alta", "informal": False, "nota": "no es emergencia"},
    {"id": 6, "remitente": "puertab@logismart.example", "asunto": "Etiqueta de tóxico rota", "cuerpo": "La etiqueta de material tóxico del contenedor en la puerta B está rota y no se alcanza a ver la clase de riesgo.", "categoria": "materiales_peligrosos", "prioridad": "alta", "informal": False, "nota": ""},
    {"id": 7, "remitente": "bascula.norte@logismart.example", "asunto": "Báscula marca exceso", "cuerpo": "La báscula de la caseta norte marcó 48.5 toneladas para el CAM-102, excede el límite permitido.", "categoria": "sobrepeso", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 8, "remitente": "trafico@logismart.example", "asunto": "Unidad pasada de peso", "cuerpo": "El tráiler con placas XYZ-789-A trae como 3 toneladas de más según el ticket de pesaje.", "categoria": "sobrepeso", "prioridad": "media", "informal": False, "nota": "sin palabra clave exacta"},
    {"id": 9, "remitente": "caseta.sur@logismart.example", "asunto": "el camion trai sobrepezo", "cuerpo": "oigan el CAM-127 viene bien cargado, la vascula dice 52 ton", "categoria": "sobrepeso", "prioridad": "media", "informal": True, "nota": "ortografía informal"},
    {"id": 10, "remitente": "anden4@logismart.example", "asunto": "Sobrecarga en eje trasero", "cuerpo": "Detectamos sobrecarga en el eje trasero de la unidad CAM-133 en el andén 4.", "categoria": "sobrepeso", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 11, "remitente": "supervisor@logismart.example", "asunto": "Pesaje urgente", "cuerpo": "URGENTE: el CAM-150 excede por 6000 kg y ya está dentro del patio.", "categoria": "sobrepeso", "prioridad": "alta", "informal": False, "nota": "urgencia sube prioridad"},
    {"id": 12, "remitente": "caseta.sur@logismart.example", "asunto": "Vehículo sin autorización en caseta sur", "cuerpo": "Un camión sin autorización intentó ingresar por la caseta sur; placas MNO-321-P.", "categoria": "acceso_no_autorizado", "prioridad": "alta", "informal": False, "nota": ""},
    {"id": 13, "remitente": "vigilancia@logismart.example", "asunto": "Persona extraña en el patio", "cuerpo": "Vimos a alguien sin gafete caminando entre los andenes; nadie del turno lo conoce.", "categoria": "acceso_no_autorizado", "prioridad": "alta", "informal": False, "nota": "sin palabra clave"},
    {"id": 14, "remitente": "puertaa@logismart.example", "asunto": "Barrera forzada en puerta A", "cuerpo": "La barrera de la puerta A fue forzada por una camioneta que se dio a la fuga.", "categoria": "acceso_no_autorizado", "prioridad": "alta", "informal": False, "nota": "'fuga' confunde a las reglas con materiales peligrosos"},
    {"id": 15, "remitente": "turno.noche@logismart.example", "asunto": "se metio un carro", "cuerpo": "se metio un carro sin permiso x la puerta c, nadie lo paro", "categoria": "acceso_no_autorizado", "prioridad": "alta", "informal": True, "nota": "ortografía informal"},
    {"id": 16, "remitente": "lpr@logismart.example", "asunto": "Posibles placas clonadas", "cuerpo": "El lector detectó las placas ABC-123-D, pero esa unidad ya estaba dentro. Posible clonación, vehículo no autorizado.", "categoria": "acceso_no_autorizado", "prioridad": "alta", "informal": False, "nota": "empate lector/no autorizado"},
    {"id": 17, "remitente": "mantenimiento@logismart.example", "asunto": "Cámara LPR apagada", "cuerpo": "La cámara lectora de placas de la caseta norte está apagada desde las 6 am.", "categoria": "falla_hardware", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 18, "remitente": "caseta.norte@logismart.example", "asunto": "Sensor RFID no lee tarjetas", "cuerpo": "El sensor RFID de la caseta norte no reconoce las tarjetas de autorización previa.", "categoria": "falla_hardware", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 19, "remitente": "puertab@logismart.example", "asunto": "camra no prende", "cuerpo": "la camra de la puerta b no prende desde ayer", "categoria": "falla_hardware", "prioridad": "media", "informal": True, "nota": "ortografía informal"},
    {"id": 20, "remitente": "anden2@logismart.example", "asunto": "Báscula descalibrada", "cuerpo": "La báscula del andén 2 da lecturas distintas cada vez que pesamos la misma unidad; parece descalibrada.", "categoria": "falla_hardware", "prioridad": "media", "informal": False, "nota": "'báscula' confunde a las reglas con sobrepeso"},
    {"id": 21, "remitente": "electrico@logismart.example", "asunto": "Falla eléctrica en caseta", "cuerpo": "Hubo una falla eléctrica y el semáforo de acceso no enciende.", "categoria": "falla_hardware", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 22, "remitente": "citas@logismart.example", "asunto": "Sistema de citas caído", "cuerpo": "El sistema de citas no carga desde la mañana, aparece error 500.", "categoria": "falla_software", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 23, "remitente": "caseta.sur@logismart.example", "asunto": "Pantalla congelada", "cuerpo": "La pantalla de la caseta sur se quedó congelada y no deja registrar entradas.", "categoria": "falla_software", "prioridad": "media", "informal": False, "nota": ""},
    {"id": 24, "remitente": "operador2@logismart.example", "asunto": "Aplicación lenta", "cuerpo": "La aplicación del operador va muy lenta al buscar placas.", "categoria": "falla_software", "prioridad": "baja", "informal": False, "nota": ""},
    {"id": 25, "remitente": "turno.tarde@logismart.example", "asunto": "no jala el sistema", "cuerpo": "no jala el sistema pa registrar las entradas, ya le reinicie y nada", "categoria": "falla_software", "prioridad": "media", "informal": True, "nota": "ortografía informal"},
    {"id": 26, "remitente": "reportes@logismart.example", "asunto": "Error al exportar reporte", "cuerpo": "Al exportar el reporte de accesos aparece un error y la ventana se cierra.", "categoria": "falla_software", "prioridad": "baja", "informal": False, "nota": ""},
    {"id": 27, "remitente": "fila@logismart.example", "asunto": "Conductor con fatiga", "cuerpo": "El conductor del CAM-120 se ve con mucha fatiga, va cabeceando en la fila de acceso.", "categoria": "somnolencia_conductor", "prioridad": "alta", "informal": False, "nota": ""},
    {"id": 28, "remitente": "caseta.norte@logismart.example", "asunto": "Chofer dormido en la caseta", "cuerpo": "El chofer de la unidad con placas QRS-654-T se quedó dormido con el motor encendido.", "categoria": "somnolencia_conductor", "prioridad": "alta", "informal": False, "nota": ""},
    {"id": 29, "remitente": "turno.noche@logismart.example", "asunto": "chofer desvelado", "cuerpo": "el chofer se ve bien desvelado y cabeceando, no se si lo dejen pasar", "categoria": "somnolencia_conductor", "prioridad": "alta", "informal": True, "nota": "ortografía informal, sin palabra clave"},
    {"id": 30, "remitente": "monitoreo@logismart.example", "asunto": "Alerta de cámara de somnolencia", "cuerpo": "La cámara de somnolencia marcó alerta para el conductor del CAM-141.", "categoria": "somnolencia_conductor", "prioridad": "alta", "informal": False, "nota": "empate cámara/somnolencia"},
    {"id": 31, "remitente": "estacionamiento@logismart.example", "asunto": "Operador sin descanso", "cuerpo": "El operador comenta que lleva 20 horas sin descansar y pide permiso para dormir en el estacionamiento antes de descargar.", "categoria": "somnolencia_conductor", "prioridad": "alta", "informal": False, "nota": "sin palabra clave exacta"},
    {"id": 32, "remitente": "cliente1@empresa.example", "asunto": "Consulta de horarios", "cuerpo": "¿Cuál es el horario de recepción del sábado?", "categoria": "otro", "prioridad": "baja", "informal": False, "nota": ""},
    {"id": 33, "remitente": "cliente2@empresa.example", "asunto": "Agradecimiento", "cuerpo": "Quiero agradecer al equipo de la caseta norte por su atención de ayer.", "categoria": "otro", "prioridad": "baja", "informal": False, "nota": ""},
    {"id": 34, "remitente": "proveedor@maniobras.example", "asunto": "Factura pendiente", "cuerpo": "No he recibido la factura del servicio de maniobras de la semana pasada.", "categoria": "otro", "prioridad": "baja", "informal": False, "nota": ""},
    {"id": 35, "remitente": "rh@logismart.example", "asunto": "Solicitud de capacitación", "cuerpo": "¿Cuándo es la próxima capacitación de manejo defensivo para operadores?", "categoria": "otro", "prioridad": "baja", "informal": False, "nota": ""},
    {"id": 36, "remitente": "cliente3@empresa.example", "asunto": "Duda sobre citas", "cuerpo": "¿El sistema permite registrar dos citas para la misma placa en un día?", "categoria": "otro", "prioridad": "baja", "informal": False, "nota": "'sistema' confunde a las reglas con falla de software"},
]


# =============================================================================
# SECCIÓN 15: DATOS DE DEMOSTRACIÓN
# =============================================================================
# Carga datos de demostración en MongoDB.
#
# Uso:
#     python3 logismart.py --demo              -> carga solo si la base está vacía
#     python3 logismart.py --demo --reiniciar  -> BORRA todo y vuelve a cargar
#
# Todos los datos son FICTICIOS (empresas, conductores y placas inventados).

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
    premisas, detalle = premisas_desde_camion(camion, peso_kg, carga_peligrosa, momento, ajustes)
    resultado = evaluar_reglas(**premisas)
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


def cargar_datos_demo(reiniciar=False):
    db = obtener_db()
    ajustes = cargar_config()
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
    correos = copy.deepcopy(CORREOS_ETIQUETADOS)
    azar.shuffle(correos)
    incidentes = []
    for numero, correo in enumerate(correos[:24]):
        fecha = ahora - timedelta(days=20 - numero * 0.85, hours=azar.randint(0, 8))
        dias = (ahora - fecha).days
        estado = "cerrado" if dias > 10 else ("en_atencion" if dias > 4 else "nuevo")
        reglas_res = clasificar_por_reglas(correo["asunto"], correo["cuerpo"])
        revision = reglas_res["categoria"] != correo["categoria"]
        incidentes.append({
            "remitente": correo["remitente"], "asunto": correo["asunto"], "cuerpo": correo["cuerpo"],
            "categoria": correo["categoria"], "prioridad": correo["prioridad"],
            "resumen": resumen_simple(correo["asunto"], correo["cuerpo"]),
            "entidades": extraer_entidades(correo["asunto"], correo["cuerpo"]),
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


# =============================================================================
# SECCIÓN 16: EXPERIMENTO DE CLASIFICACIÓN
# =============================================================================
# EXPERIMENTO: comparación de clasificadores (reglas vs LLM vs híbrido).
#
# Uso:
#     python3 logismart.py --experimento                 -> experimento completo (necesita Ollama)
#     python3 logismart.py --experimento --solo-reglas   -> rápido, sin LLM
#     python3 logismart.py --experimento --sin-mongo     -> no guarda en evaluaciones_llm
#     python3 logismart.py --experimento --limite 5      -> solo los primeros 5 correos (prueba rápida)
#
# Métricas por clasificador:
#     - exactitud de categoría y de prioridad
#     - matriz de confusión de categorías
#     - latencia promedio y mediana (ms)
#     - exactitud en correos con ortografía informal (evidencia de sesgo)
#     - % de JSON válidos del LLM y % marcados para revisión humana
#
# Resultados (carpeta resultados_experimento/):
#     resultados.json, resultados.md y confusion_*.png

SALIDA_JSON = RAIZ / "resultados_experimento" / "resultados.json"
SALIDA_MD = RAIZ / "resultados_experimento" / "resultados.md"
CARPETA_IMG = RAIZ / "resultados_experimento"


def calcular_matriz_confusion(reales, predichas, etiquetas):
    indice = {e: i for i, e in enumerate(etiquetas)}
    matriz = [[0] * len(etiquetas) for _ in etiquetas]
    for real, pred in zip(reales, predichas):
        matriz[indice[real]][indice[pred]] += 1
    return matriz


def exactitud(reales, predichas):
    if not reales:
        return 0.0
    return sum(1 for r, p in zip(reales, predichas) if r == p) / len(reales)


def metricas_clasificador(nombre, correos, predicciones, latencias):
    reales_cat = [c["categoria"] for c in correos]
    reales_pri = [c["prioridad"] for c in correos]
    pred_cat = [p["categoria"] for p in predicciones]
    pred_pri = [p["prioridad"] for p in predicciones]
    informales = [i for i, c in enumerate(correos) if c["informal"]]
    formales = [i for i, c in enumerate(correos) if not c["informal"]]

    por_clase = {}
    for etiqueta in CATEGORIAS_VALIDAS:
        indices = [i for i, r in enumerate(reales_cat) if r == etiqueta]
        if indices:
            por_clase[etiqueta] = round(exactitud([reales_cat[i] for i in indices],
                                                  [pred_cat[i] for i in indices]), 3)

    return {
        "clasificador": nombre,
        "exactitud_categoria": round(exactitud(reales_cat, pred_cat), 3),
        "exactitud_prioridad": round(exactitud(reales_pri, pred_pri), 3),
        "exactitud_informal": round(exactitud([reales_cat[i] for i in informales],
                                              [pred_cat[i] for i in informales]), 3),
        "exactitud_formal": round(exactitud([reales_cat[i] for i in formales],
                                            [pred_cat[i] for i in formales]), 3),
        "exhaustividad_por_clase": por_clase,
        "latencia_promedio_ms": round(statistics.mean(latencias), 2) if latencias else 0,
        "latencia_mediana_ms": round(statistics.median(latencias), 2) if latencias else 0,
        "matriz_confusion": calcular_matriz_confusion(reales_cat, pred_cat, CATEGORIAS_VALIDAS),
    }


def ejecutar_experimento(solo_reglas=False, guardar_mongo=True, limite=None):
    correos = copy.deepcopy(CORREOS_ETIQUETADOS)
    if limite:
        correos = correos[:limite]

    ajustes = cargar_config()
    print(f"Correos etiquetados: {len(correos)} | modelo: {ajustes['modelo_ollama']}")

    registrar = None
    if guardar_mongo and not solo_reglas:
        try:
            obtener_db()
            registrar = registrar_evaluacion
        except Exception as error:  # noqa: BLE001
            print(f"[aviso] Sin MongoDB, no se guardará en evaluaciones_llm: {error}")

    pred_reglas, lat_reglas = [], []
    pred_llm, lat_llm = [], []
    pred_hibrido, lat_hibrido = [], []
    detalle = []
    json_validos = 0
    revisiones = 0

    for numero, correo in enumerate(correos, start=1):
        # --- Reglas ---------------------------------------------------------
        inicio = time.perf_counter()
        r = clasificar_por_reglas(correo["asunto"], correo["cuerpo"])
        t_reglas = (time.perf_counter() - inicio) * 1000
        pred_reglas.append(r)
        lat_reglas.append(t_reglas)

        fila = {"id": correo["id"], "real": correo["categoria"], "informal": correo["informal"],
                "reglas": r["categoria"]}

        if not solo_reglas:
            # --- LLM --------------------------------------------------------
            res = clasificar_con_llm(correo["asunto"], correo["cuerpo"], ajustes)
            if res["ok"]:
                json_validos += 1
                l = res["clasificacion"]
            else:
                # El LLM "solo" no tiene respaldo: si falla cuenta como 'otro'
                l = {"categoria": "otro", "prioridad": "baja"}
            pred_llm.append(l)
            lat_llm.append(res["latencia_ms"])

            # --- Híbrido (fusión de los dos resultados anteriores) -----------
            if res["ok"]:
                categoria, prioridad, revision, _ = fusionar(r, l)
            else:
                categoria, prioridad, revision = r["categoria"], r["prioridad"], r["categoria"] == "otro"
            revisiones += int(revision)
            pred_hibrido.append({"categoria": categoria, "prioridad": prioridad})
            lat_hibrido.append(t_reglas + res["latencia_ms"])

            fila.update({"llm": l["categoria"], "hibrido": categoria, "revision_humana": revision,
                         "json_valido": res["ok"], "latencia_llm_ms": round(res["latencia_ms"], 1)})

            if registrar:
                try:
                    registrar({
                        "tipo": "experimento",
                        "prompt": res["prompt"],
                        "respuesta": res["respuesta"],
                        "modelo": res["modelo"],
                        "latencia_ms": round(res["latencia_ms"], 1),
                        "json_valido": res["ok"],
                        "intentos": res["intentos"],
                        "categoria_real": correo["categoria"],
                        "categoria_llm": l["categoria"],
                        "categoria_reglas": r["categoria"],
                        "coincidio_con_reglas": l["categoria"] == r["categoria"],
                        "acierto_llm": l["categoria"] == correo["categoria"],
                    })
                except Exception:  # noqa: BLE001
                    pass

            estado = "OK " if categoria == correo["categoria"] else "MAL"
            print(f"  [{numero:02d}/{len(correos)}] {estado} real={correo['categoria']:<22} "
                  f"reglas={r['categoria']:<22} llm={l['categoria']:<22} "
                  f"({res['latencia_ms'] / 1000:.1f} s)")
        detalle.append(fila)

    resultados = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "modelo": ajustes["modelo_ollama"],
        "total_correos": len(correos),
        "correos_informales": sum(1 for c in correos if c["informal"]),
        "clasificadores": [metricas_clasificador("reglas", correos, pred_reglas, lat_reglas)],
        "detalle": detalle,
    }
    if not solo_reglas:
        resultados["clasificadores"].append(metricas_clasificador("llm", correos, pred_llm, lat_llm))
        resultados["clasificadores"].append(metricas_clasificador("hibrido", correos, pred_hibrido, lat_hibrido))
        resultados["json_validos_pct"] = round(100 * json_validos / len(correos), 1)
        resultados["revision_humana_pct"] = round(100 * revisiones / len(correos), 1)

    guardar_resultados(resultados)
    return resultados


def guardar_resultados(resultados):
    CARPETA_IMG.mkdir(parents=True, exist_ok=True)
    SALIDA_JSON.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    CARPETA_IMG.mkdir(parents=True, exist_ok=True)

    lineas = [
        "# Resultados del experimento de clasificación",
        "",
        f"- Fecha: {resultados['fecha']}",
        f"- Modelo LLM: `{resultados['modelo']}`",
        f"- Correos etiquetados a mano: {resultados['total_correos']} "
        f"({resultados['correos_informales']} con ortografía informal)",
    ]
    if "json_validos_pct" in resultados:
        lineas.append(f"- JSON válidos del LLM: {resultados['json_validos_pct']} %")
        lineas.append(f"- Correos marcados para revisión humana (híbrido): {resultados['revision_humana_pct']} %")

    lineas += ["", "## Comparación", "",
               "| Clasificador | Exactitud categoría | Exactitud prioridad | Exactitud formal | "
               "Exactitud informal | Latencia promedio | Latencia mediana |",
               "|---|---|---|---|---|---|---|"]
    for m in resultados["clasificadores"]:
        lineas.append(
            f"| {m['clasificador']} | {m['exactitud_categoria'] * 100:.1f} % | {m['exactitud_prioridad'] * 100:.1f} % | "
            f"{m['exactitud_formal'] * 100:.1f} % | {m['exactitud_informal'] * 100:.1f} % | "
            f"{m['latencia_promedio_ms']:.2f} ms | {m['latencia_mediana_ms']:.2f} ms |")

    lineas += ["", "## Exhaustividad (recall) por categoría", "",
               "| Categoría | " + " | ".join(m["clasificador"] for m in resultados["clasificadores"]) + " |",
               "|---|" + "---|" * len(resultados["clasificadores"])]
    for etiqueta in CATEGORIAS_VALIDAS:
        valores = [f"{m['exhaustividad_por_clase'].get(etiqueta, 0) * 100:.0f} %" for m in resultados["clasificadores"]]
        lineas.append(f"| {etiqueta} | " + " | ".join(valores) + " |")

    lineas += ["", "## Matrices de confusión", ""]
    for m in resultados["clasificadores"]:
        png = grafica_matriz_confusion(m["matriz_confusion"], CATEGORIAS_VALIDAS,
                                        f"Matriz de confusión · {m['clasificador']}", oscuro=False)
        nombre = f"confusion_{m['clasificador']}.png"
        (CARPETA_IMG / nombre).write_bytes(png)
        lineas.append(f"![Matriz de confusión {m['clasificador']}]({nombre})")
        lineas.append("")

    lineas += ["## Detalle por correo", "",
               "| # | Real | Informal | Reglas | LLM | Híbrido | Revisión |", "|---|---|---|---|---|---|---|"]
    for f in resultados["detalle"]:
        lineas.append(f"| {f['id']} | {f['real']} | {'sí' if f['informal'] else ''} | {f['reglas']} | "
                      f"{f.get('llm', '-')} | {f.get('hibrido', '-')} | "
                      f"{'sí' if f.get('revision_humana') else ''} |")

    SALIDA_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"\nResultados guardados en:\n  {SALIDA_JSON}\n  {SALIDA_MD}\n  {CARPETA_IMG}")


def imprimir_resultados(resultados):
    print("\n" + "=" * 78)
    print(f"{'Clasificador':<12}{'Categoría':>12}{'Prioridad':>12}{'Informal':>12}{'Latencia prom.':>18}")
    print("-" * 78)
    for m in resultados["clasificadores"]:
        print(f"{m['clasificador']:<12}{m['exactitud_categoria'] * 100:>11.1f}%{m['exactitud_prioridad'] * 100:>11.1f}%"
              f"{m['exactitud_informal'] * 100:>11.1f}%{m['latencia_promedio_ms']:>15.1f} ms")


# =============================================================================
# SECCIÓN 17: INTERFAZ: COMPONENTES COMUNES
# =============================================================================
# Componentes y utilidades compartidas por todas las pantallas.

# Colores de marca (mismo estilo que el tutor de la práctica 2)
MORADO = "#7C4DFF"
ROSA = "#FF4081"
CIAN = "#00B8D4"

# Colores de estado (semáforo y niveles de riesgo)
VERDE = "#0ca30c"
AMARILLO = "#fab219"
NARANJA = "#ec835a"
ROJO = "#d03b3b"

COLOR_RESULTADO = {"verde": VERDE, "amarillo": AMARILLO, "rojo": ROJO}
COLOR_PRIORIDAD = {"baja": VERDE, "media": AMARILLO, "alta": NARANJA, "critica": ROJO}
COLOR_ESTADO = {"nuevo": CIAN, "en_atencion": AMARILLO, "cerrado": VERDE}


# Valor que devuelve App.bd() cuando MongoDB falla (None puede ser un resultado válido)
FALLO = object()


async def en_hilo(funcion, *args, **kwargs):
    """Ejecuta una función lenta (MongoDB, LLM) sin congelar la interfaz."""
    return await asyncio.to_thread(funcion, *args, **kwargs)


def fecha_txt(valor, con_hora=True):
    if not isinstance(valor, datetime):
        return "-" if valor is None else str(valor)
    return valor.strftime("%d/%m/%Y %H:%M" if con_hora else "%d/%m/%Y")


def titulo_vista(titulo, subtitulo="", acciones=None):
    return ft.Row(
        [
            ft.Column(
                [
                    ft.Text(titulo, size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(subtitulo, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=2,
                expand=True,
            ),
            *(acciones or []),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def tarjeta(contenido, padding=20, expand=False, width=None, col=None):
    return ft.Container(
        content=contenido,
        padding=padding,
        border_radius=16,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        expand=expand,
        width=width,
        col=col if col is not None else 12,
    )


def subtitulo(texto, icono=None):
    controles = []
    if icono:
        controles.append(ft.Icon(icono, size=18, color=MORADO))
    controles.append(ft.Text(texto, size=15, weight=ft.FontWeight.BOLD))
    return ft.Row(controles, spacing=8)


def kpi(titulo, valor, icono, color, detalle=None):
    """Tarjeta de indicador. 'valor' y 'detalle' son controles ft.Text para poder actualizarlos."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Icon(icono, color=ft.Colors.WHITE, size=24),
                    width=48, height=48, border_radius=14, bgcolor=color,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Column(
                    [ft.Text(titulo, size=12, color=ft.Colors.ON_SURFACE_VARIANT), valor] +
                    ([detalle] if detalle else []),
                    spacing=0,
                    expand=True,
                ),
            ],
            spacing=14,
        ),
        padding=16,
        border_radius=16,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        col={"xs": 12, "sm": 6, "lg": 3},
    )


def chip(texto, color, icono=None):
    """Etiqueta de color con texto (el color nunca va solo: siempre con texto)."""
    controles = []
    if icono:
        controles.append(ft.Icon(icono, size=14, color=color))
    controles.append(ft.Text(texto, size=12, weight=ft.FontWeight.BOLD, color=color))
    return ft.Container(
        content=ft.Row(controles, spacing=4, tight=True),
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=20,
        bgcolor=ft.Colors.with_opacity(0.14, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
    )


def chip_vf(nombre, valor):
    color = VERDE if valor else ft.Colors.ON_SURFACE_VARIANT
    return chip(f"{nombre} = {'V' if valor else 'F'}", color)


def imagen(png, alto=None):
    return ft.Image(src=png, fit=ft.BoxFit.CONTAIN, height=alto, border_radius=12)


def cargando(texto="Cargando..."):
    return ft.Row(
        [ft.ProgressRing(width=18, height=18, stroke_width=2, color=MORADO),
         ft.Text(texto, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
        spacing=10,
    )


def aviso(page, texto, tipo="info"):
    colores = {"info": MORADO, "ok": VERDE, "error": ROJO, "aviso": NARANJA}
    page.show_dialog(ft.SnackBar(
        content=ft.Text(texto, color=ft.Colors.WHITE),
        bgcolor=colores.get(tipo, MORADO),
        behavior=ft.SnackBarBehavior.FLOATING,
        show_close_icon=True,
        duration=ft.Duration(seconds=5),
    ))
    page.update()


def confirmar(page, titulo, mensaje, al_confirmar, texto_boton="Eliminar"):
    """Diálogo de confirmación. al_confirmar puede ser async."""

    async def aceptar(e):
        page.pop_dialog()
        resultado = al_confirmar()
        if asyncio.iscoroutine(resultado):
            await resultado

    def cancelar(e):
        page.pop_dialog()

    page.show_dialog(ft.AlertDialog(
        modal=True,
        title=ft.Text(titulo),
        content=ft.Text(mensaje),
        actions=[
            ft.TextButton("Cancelar", on_click=cancelar),
            ft.FilledButton(texto_boton, on_click=aceptar, bgcolor=ROJO, color=ft.Colors.WHITE),
        ],
    ))


def tabla(columnas, filas_controles=None):
    return ft.DataTable(
        columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD, size=12)) for c in columnas],
        rows=filas_controles or [],
        column_spacing=18,
        heading_row_height=40,
        data_row_min_height=40,
        data_row_max_height=64,
        horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
    )


def celda(texto, ancho=None, color=None, negrita=False):
    return ft.DataCell(ft.Container(
        ft.Text(str(texto) if texto is not None else "-", size=12, color=color,
                weight=ft.FontWeight.BOLD if negrita else None,
                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        width=ancho,
    ))


def boton_icono(icono, ayuda, al_hacer_clic, color=None):
    return ft.IconButton(icon=icono, tooltip=ayuda, on_click=al_hacer_clic, icon_color=color, icon_size=20)


# -----------------------------------------------------------------------------
# Filtro de fechas reutilizable
# -----------------------------------------------------------------------------

class FiltroFechas:
    """
    Selector de periodo: Hoy, 7 días, 30 días, Todo o rango personalizado.
    al_cambiar() se llama (async) cuando cambia el periodo.
    """

    def __init__(self, page, al_cambiar, inicial="30"):
        self.page = page
        self.al_cambiar = al_cambiar
        self.opcion = inicial
        self.desde_personal = None
        self.hasta_personal = None
        self.texto_rango = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.segmentos = ft.SegmentedButton(
            segments=[
                ft.Segment(value="hoy", label=ft.Text("Hoy")),
                ft.Segment(value="7", label=ft.Text("7 días")),
                ft.Segment(value="30", label=ft.Text("30 días")),
                ft.Segment(value="todo", label=ft.Text("Todo")),
                ft.Segment(value="personal", label=ft.Text("Rango…")),
            ],
            selected=[inicial],
            show_selected_icon=False,
            on_change=self._cambio,
        )
        self.control = ft.Row([self.segmentos, self.texto_rango], spacing=12, wrap=True)
        self._actualizar_texto()

    def rango(self):
        ahora = datetime.now()
        inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.opcion == "hoy":
            return inicio_hoy, None
        if self.opcion == "7":
            return inicio_hoy - timedelta(days=7), None
        if self.opcion == "30":
            return inicio_hoy - timedelta(days=30), None
        if self.opcion == "personal" and self.desde_personal:
            hasta = (self.hasta_personal or ahora).replace(hour=23, minute=59, second=59)
            return self.desde_personal, hasta
        return None, None

    def descripcion(self):
        desde, hasta = self.rango()
        if desde is None:
            return "Todo el historial"
        return f"{fecha_txt(desde, False)} a {fecha_txt(hasta or datetime.now(), False)}"

    def _actualizar_texto(self):
        self.texto_rango.value = self.descripcion()

    async def _cambio(self, e):
        self.opcion = e.control.selected[0] if e.control.selected else "todo"
        if self.opcion == "personal":
            self._pedir_fecha("desde")
            return
        self._actualizar_texto()
        await self.al_cambiar()

    def _pedir_fecha(self, cual):
        async def elegida(e):
            valor = e.control.value
            if isinstance(valor, datetime):
                valor = valor.replace(tzinfo=None)
            else:
                valor = datetime(valor.year, valor.month, valor.day)
            if cual == "desde":
                self.desde_personal = valor.replace(hour=0, minute=0, second=0)
                self._pedir_fecha("hasta")
            else:
                self.hasta_personal = valor
                if self.hasta_personal < self.desde_personal:
                    self.desde_personal, self.hasta_personal = self.hasta_personal, self.desde_personal
                self._actualizar_texto()
                await self.al_cambiar()

        self.page.show_dialog(ft.DatePicker(
            first_date=datetime(2024, 1, 1),
            last_date=datetime.now() + timedelta(days=1),
            help_text="Fecha inicial" if cual == "desde" else "Fecha final",
            on_change=elegida,
        ))
        self.page.update()


# =============================================================================
# SECCIÓN 18: INTERFAZ: PANEL DE CONTROL
# =============================================================================
# Panel de control: indicadores con filtro de fechas, gráficas y últimos accesos.

class VistaPanel:
    def __init__(self, app):
        self.app = app
        self.filtro = FiltroFechas(app.page, self.refrescar, inicial="30")

        self.v_camiones = ft.Text("-", size=26, weight=ft.FontWeight.BOLD)
        self.d_camiones = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        self.v_accesos = ft.Text("-", size=26, weight=ft.FontWeight.BOLD)
        self.d_accesos = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        self.v_incidentes = ft.Text("-", size=26, weight=ft.FontWeight.BOLD)
        self.d_incidentes = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        self.v_riesgos = ft.Text("-", size=26, weight=ft.FontWeight.BOLD)
        self.d_riesgos = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)

        self.grafica_semana = ft.Container(cargando(), height=330, alignment=ft.Alignment.CENTER)
        self.grafica_accesos = ft.Container(cargando(), height=330, alignment=ft.Alignment.CENTER)
        self.tabla_accesos = tabla(["Fecha", "Camión", "Placa", "Semáforo", "Decisión", "Operador"])

        peas = ft.ExpansionTile(
            title=ft.Text("Diseño PEAS del agente (medidas, entorno, actuadores, sensores)", size=14),
            leading=ft.Icon(ft.Icons.PSYCHOLOGY, color=MORADO),
            controls=[ft.Container(ft.Text(peas_como_texto(), size=12, selectable=True), padding=16)],
        )

        self.control = ft.Column(
            [
                titulo_vista("Panel de control", "Resumen de la operación del centro logístico"),
                self.filtro.control,
                ft.ResponsiveRow([
                    kpi("Camiones atendidos", self.v_camiones, ft.Icons.LOCAL_SHIPPING, MORADO, self.d_camiones),
                    kpi("Decisiones de acceso", self.v_accesos, ft.Icons.TRAFFIC, CIAN, self.d_accesos),
                    kpi("Incidentes abiertos", self.v_incidentes, ft.Icons.INBOX, NARANJA, self.d_incidentes),
                    kpi("Riesgos críticos", self.v_riesgos, ft.Icons.WARNING_AMBER, ROJO, self.d_riesgos),
                ], spacing=14, run_spacing=14),
                ft.ResponsiveRow([
                    tarjeta(ft.Column([subtitulo("Incidentes por categoría y semana", ft.Icons.BAR_CHART),
                                       ft.Text("Agregación de MongoDB: $group por categoría y semana ISO",
                                               size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                       self.grafica_semana]), col={"xs": 12, "lg": 7}),
                    tarjeta(ft.Column([subtitulo("Semáforo de accesos", ft.Icons.TRAFFIC),
                                       ft.Text("Decisiones del motor de reglas en el periodo",
                                               size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                       self.grafica_accesos]), col={"xs": 12, "lg": 5}),
                ], spacing=14, run_spacing=14),
                tarjeta(ft.Column([subtitulo("Últimas decisiones de acceso", ft.Icons.HISTORY),
                                   ft.Row([self.tabla_accesos], scroll=ft.ScrollMode.AUTO)])),
                tarjeta(peas, padding=4),
            ],
            spacing=16,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    async def refrescar(self):
        desde, hasta = self.filtro.rango()
        datos = await self.app.bd(self._consultar, desde, hasta)
        if datos is FALLO:
            return
        ind, semana, accesos = datos

        self.v_camiones.value = str(ind["camiones_atendidos"])
        self.d_camiones.value = "camiones distintos con decisión registrada"
        self.v_accesos.value = str(ind["accesos_registrados"])
        self.d_accesos.value = (f"{ind['accesos_verde']} verde · {ind['accesos_amarillo']} amarillo · "
                                f"{ind['accesos_rojo']} rojo")
        self.v_incidentes.value = str(ind["incidentes_abiertos"])
        self.d_incidentes.value = f"{ind['incidentes_revision_humana']} requieren revisión humana"
        self.v_riesgos.value = str(ind["riesgos_criticos"])
        self.d_riesgos.value = f"{ind['riesgos_criticos_residual']} críticos tras mitigar"

        oscuro = self.app.oscuro
        self.grafica_semana.content = imagen(incidentes_por_semana(semana, oscuro), alto=320)
        self.grafica_accesos.content = imagen(accesos_por_resultado(ind, oscuro), alto=320)

        self.tabla_accesos.rows = [
            ft.DataRow(cells=[
                celda(fecha_txt(a.get("fecha")), 120),
                celda(a.get("camion_id"), 70, negrita=True),
                celda(a.get("placa"), 90),
                ft.DataCell(chip(a.get("resultado", "-").upper(), COLOR_RESULTADO.get(a.get("resultado"), MORADO))),
                celda(a.get("decision"), 380),
                celda(a.get("operador"), 110),
            ])
            for a in accesos
        ]
        self.app.page.update()

    @staticmethod
    def _consultar(desde, hasta):
        return (indicadores(desde, hasta),
                incidentes_por_categoria_semana(desde, hasta),
                listar_accesos(desde, hasta, limite=8))


# =============================================================================
# SECCIÓN 19: INTERFAZ: CAMIONES
# =============================================================================
# Catálogo de camiones: alta, búsqueda, edición y baja (CRUD).

PATRON_PLACA = re.compile(r"^[A-Z0-9]{2,3}-\d{2,3}-[A-Z0-9]{1,2}$")
PATRON_ID = re.compile(r"^CAM-\d+$")


def estado_certificacion(vence, dias_aviso=30):
    if not isinstance(vence, datetime):
        return "sin registro", ROJO
    dias = (vence.date() - datetime.now().date()).days
    if dias < 0:
        return f"vencida hace {-dias} d", ROJO
    if dias <= dias_aviso:
        return f"vence en {dias} d", NARANJA
    return "vigente", VERDE


class VistaCamiones:
    def __init__(self, app):
        self.app = app
        self.busqueda = ft.TextField(hint_text="Buscar por placa, ID o empresa", prefix_icon=ft.Icons.SEARCH,
                                     dense=True, width=320, on_submit=self._buscar, on_change=self._buscar)
        self.tabla = tabla(["ID", "Placa", "Empresa", "Autorizado", "Conductor", "Certificación", "Estado", ""])
        self.contador = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.control = ft.Column(
            [
                titulo_vista("Camiones", "Catálogo con autorización previa (P) y certificación del conductor (S, T)",
                             [ft.FilledButton("Nuevo camión", icon=ft.Icons.ADD, on_click=self._nuevo,
                                              bgcolor=MORADO, color=ft.Colors.WHITE)]),
                ft.Row([self.busqueda, self.contador], spacing=16),
                tarjeta(ft.Row([self.tabla], scroll=ft.ScrollMode.AUTO)),
                ft.Text("Los datos de conductores son ficticios. En producción se aplican las mitigaciones de "
                        "privacidad de la matriz de riesgos.", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=16, scroll=ft.ScrollMode.AUTO, expand=True,
        )

    async def _buscar(self, e=None):
        await self.refrescar()

    async def refrescar(self):
        camiones = await self.app.bd(listar_camiones, self.busqueda.value or None)
        if camiones is FALLO:
            return
        dias_aviso = self.app.ajustes.get("dias_aviso_certificacion", 30)
        filas = []
        for c in camiones:
            texto_estado, color = estado_certificacion(c.get("certificacion_vence"), dias_aviso)
            filas.append(ft.DataRow(cells=[
                celda(c.get("camion_id"), 70, negrita=True),
                celda(c.get("placa"), 90),
                celda(c.get("empresa"), 170),
                ft.DataCell(chip("Sí", VERDE, ft.Icons.CHECK) if c.get("autorizado")
                            else chip("No", ROJO, ft.Icons.CLOSE)),
                celda(c.get("conductor"), 110),
                celda(fecha_txt(c.get("certificacion_vence"), False), 90),
                ft.DataCell(chip(texto_estado, color)),
                ft.DataCell(ft.Row([
                    boton_icono(ft.Icons.EDIT_OUTLINED, "Editar", lambda e, c=c: self._formulario(c)),
                    boton_icono(ft.Icons.DELETE_OUTLINE, "Eliminar", lambda e, c=c: self._eliminar(c), ROJO),
                ], spacing=0)),
            ]))
        self.tabla.rows = filas
        self.contador.value = f"{len(camiones)} camión(es)"
        self.app.page.update()

    def _nuevo(self, e):
        self._formulario(None)

    def _eliminar(self, camion):
        async def borrar():
            if await self.app.bd(eliminar_camion, camion["_id"]) is not FALLO:
                self.app.aviso(f"Camión {camion['camion_id']} eliminado", "ok")
                await self.refrescar()

        confirmar(self.app.page, "Eliminar camión",
                  f"¿Eliminar {camion['camion_id']} ({camion['placa']})? Su historial de accesos se conserva.", borrar)

    def _formulario(self, camion):
        es_nuevo = camion is None
        camion = camion or {}
        page = self.app.page

        f_id = ft.TextField(label="ID del camión", value=camion.get("camion_id", ""), hint_text="CAM-123",
                            capitalization=ft.TextCapitalization.CHARACTERS)
        f_placa = ft.TextField(label="Placa", value=camion.get("placa", ""), hint_text="ABC-123-D",
                               capitalization=ft.TextCapitalization.CHARACTERS)
        f_empresa = ft.TextField(label="Empresa", value=camion.get("empresa", ""))
        f_conductor = ft.TextField(label="Conductor", value=camion.get("conductor", ""))
        vence = camion.get("certificacion_vence")
        f_vence = ft.TextField(label="Certificación vence (DD/MM/AAAA)",
                               value=vence.strftime("%d/%m/%Y") if isinstance(vence, datetime) else "")
        f_autorizado = ft.Switch(label="Autorización previa (P)", value=camion.get("autorizado", True),
                                 active_color=MORADO)

        async def guardar(e):
            # --- Validación con mensajes claros ---
            errores = False
            for campo in [f_id, f_placa, f_empresa, f_vence]:
                campo.error = None
            camion_id = (f_id.value or "").strip().upper()
            placa = (f_placa.value or "").strip().upper()
            if not PATRON_ID.match(camion_id):
                f_id.error = "Formato: CAM- seguido de números (ej. CAM-123)"
                errores = True
            if not PATRON_PLACA.match(placa):
                f_placa.error = "Formato: ABC-123-D"
                errores = True
            if not (f_empresa.value or "").strip():
                f_empresa.error = "La empresa es obligatoria"
                errores = True
            fecha = None
            if (f_vence.value or "").strip():
                try:
                    fecha = datetime.strptime(f_vence.value.strip(), "%d/%m/%Y")
                except ValueError:
                    f_vence.error = "Fecha inválida. Usa DD/MM/AAAA"
                    errores = True
            if errores:
                page.update()
                return

            datos = {"camion_id": camion_id, "placa": placa, "empresa": f_empresa.value.strip(),
                     "conductor": (f_conductor.value or "").strip(), "certificacion_vence": fecha,
                     "autorizado": f_autorizado.value}
            if es_nuevo:
                resultado = await self.app.bd(crear_camion, datos)
            else:
                resultado = await self.app.bd(actualizar_camion, camion["_id"], datos)
            if resultado is FALLO:
                return
            page.pop_dialog()
            self.app.aviso(f"Camión {camion_id} {'registrado' if es_nuevo else 'actualizado'}", "ok")
            await self.refrescar()

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Nuevo camión" if es_nuevo else f"Editar {camion.get('camion_id')}"),
            content=ft.Container(ft.Column([f_id, f_placa, f_empresa, f_conductor, f_vence, f_autorizado],
                                           tight=True, spacing=12), width=420),
            actions=[ft.TextButton("Cancelar", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("Guardar", on_click=guardar, bgcolor=MORADO, color=ft.Colors.WHITE)],
        ))
        page.update()


# =============================================================================
# SECCIÓN 20: INTERFAZ: CONTROL DE ACCESO
# =============================================================================
# Control de acceso: búsqueda por placa o formulario P/Q/R/S, semáforo y explicación.

def crear_semaforo():
    """Devuelve (control, función para encender un color)."""
    luces = {}
    columna = []
    for nombre, color in [("rojo", ROJO), ("amarillo", AMARILLO), ("verde", VERDE)]:
        luz = ft.Container(width=46, height=46, border_radius=23, bgcolor=ft.Colors.with_opacity(0.15, color),
                           border=ft.Border.all(2, ft.Colors.with_opacity(0.35, color)),
                           animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT))
        luces[nombre] = (luz, color)
        columna.append(luz)

    control = ft.Container(
        content=ft.Column(columna, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=12, border_radius=40, bgcolor="#141414", width=72,
    )

    def encender(resultado):
        for nombre, (luz, color) in luces.items():
            activo = nombre == resultado
            luz.bgcolor = color if activo else ft.Colors.with_opacity(0.15, color)
            luz.shadow = ft.BoxShadow(blur_radius=24, color=ft.Colors.with_opacity(0.8, color)) if activo else None

    return control, encender


class VistaAcceso:
    def __init__(self, app):
        self.app = app

        # --- Modo búsqueda por placa ---
        self.f_identificador = ft.TextField(label="Placa o ID del camión", hint_text="ABC-123-D o CAM-102",
                                            capitalization=ft.TextCapitalization.CHARACTERS,
                                            prefix_icon=ft.Icons.SEARCH, on_submit=self._evaluar_placa)
        self.f_peso = ft.TextField(label="Peso en báscula (kg)", value="30000", keyboard_type=ft.KeyboardType.NUMBER,
                                   width=200)
        self.f_hora = ft.TextField(label="Hora de llegada (HH:MM)", value=datetime.now().strftime("%H:%M"), width=200)
        self.f_peligrosa = ft.Switch(label="Lleva materiales peligrosos (R)", value=False, active_color=MORADO)
        modo_placa = ft.Column([
            self.f_identificador,
            ft.Row([self.f_peso, self.f_hora], spacing=12),
            self.f_peligrosa,
            ft.FilledButton("Evaluar acceso", icon=ft.Icons.PLAY_ARROW, on_click=self._evaluar_placa,
                            bgcolor=MORADO, color=ft.Colors.WHITE, height=44),
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        # --- Modo manual P/Q/R/S/H/T ---
        self.interruptores = {}
        filas = []
        for clave in ORDEN_PREMISAS:
            interruptor = ft.Switch(value=clave in ("P", "S"), active_color=MORADO)
            self.interruptores[clave] = interruptor
            filas.append(ft.Row([ft.Text(clave, weight=ft.FontWeight.BOLD, width=22), interruptor,
                                 ft.Text(PREMISAS[clave], size=12, expand=True)], spacing=6))
        self.f_id_manual = ft.TextField(label="ID o placa (opcional, para la bitácora)", dense=True,
                                        capitalization=ft.TextCapitalization.CHARACTERS)
        modo_manual = ft.Column(filas + [
            self.f_id_manual,
            ft.FilledButton("Evaluar y registrar", icon=ft.Icons.PLAY_ARROW, on_click=self._evaluar_manual,
                            bgcolor=MORADO, color=ft.Colors.WHITE, height=44),
        ], spacing=6, visible=False)

        self.modo_placa = modo_placa
        self.modo_manual = modo_manual
        selector = ft.SegmentedButton(
            segments=[ft.Segment(value="placa", label=ft.Text("Búsqueda por placa"), icon=ft.Icon(ft.Icons.SEARCH)),
                      ft.Segment(value="manual", label=ft.Text("Formulario P/Q/R/S"), icon=ft.Icon(ft.Icons.TUNE))],
            selected=["placa"], on_change=self._cambiar_modo,
        )

        # --- Resultado ---
        self.semaforo, self.encender = crear_semaforo()
        self.t_decision = ft.Text("Evalúa un camión para ver la decisión", size=18, weight=ft.FontWeight.BOLD)
        self.t_causa = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self.fila_reglas = ft.Row([], spacing=8, wrap=True)
        self.lista_pasos = ft.Column([], spacing=6)
        self.detalle_premisas = ft.Column([], spacing=4)
        self.estado_guardado = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        resultado = tarjeta(ft.Column([
            subtitulo("Resultado", ft.Icons.TRAFFIC),
            ft.Row([
                self.semaforo,
                ft.Column([self.t_decision, self.t_causa, self.fila_reglas, self.estado_guardado],
                          spacing=8, expand=True),
            ], spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Divider(),
            ft.Text("Explicación paso a paso", weight=ft.FontWeight.BOLD),
            self.lista_pasos,
            self.detalle_premisas,
        ], spacing=12), col={"xs": 12, "lg": 7})

        self.tabla = tabla(["Fecha", "Camión", "Semáforo", "Decisión", "Reglas", "Operador", ""])

        self.control = ft.Column([
            titulo_vista("Control de acceso", "El motor de reglas decide y cada decisión se guarda en la bitácora "
                                              "'accesos' con su explicación"),
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Datos de llegada", ft.Icons.LOCAL_SHIPPING), selector,
                                   modo_placa, modo_manual], spacing=14), col={"xs": 12, "lg": 5}),
                resultado,
            ], spacing=16, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            tarjeta(ft.Column([subtitulo("Bitácora de accesos (últimos 30)", ft.Icons.HISTORY),
                               ft.Row([self.tabla], scroll=ft.ScrollMode.AUTO)])),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------
    async def refrescar(self):
        accesos = await self.app.bd(listar_accesos, limite=30)
        if accesos is FALLO:
            return
        self.tabla.rows = [
            ft.DataRow(cells=[
                celda(fecha_txt(a.get("fecha")), 115),
                celda(a.get("camion_id") or a.get("placa") or "manual", 75, negrita=True),
                ft.DataCell(chip(a.get("resultado", "-").upper(), COLOR_RESULTADO.get(a.get("resultado"), MORADO))),
                celda(a.get("decision"), 330),
                celda(", ".join(a.get("reglas_activadas", [])) or "-", 70),
                celda(a.get("operador"), 110),
                ft.DataCell(ft.Row([
                    boton_icono(ft.Icons.INFO_OUTLINE, "Ver explicación", lambda e, a=a: self._ver(a)),
                    boton_icono(ft.Icons.DELETE_OUTLINE, "Eliminar registro", lambda e, a=a: self._eliminar(a), ROJO),
                ], spacing=0)),
            ])
            for a in accesos
        ]
        self.app.page.update()

    def _cambiar_modo(self, e):
        manual = e.control.selected[0] == "manual"
        self.modo_placa.visible = not manual
        self.modo_manual.visible = manual
        self.app.page.update()

    # ------------------------------------------------------------------
    async def _evaluar_placa(self, e=None):
        page = self.app.page
        for campo in [self.f_identificador, self.f_peso, self.f_hora]:
            campo.error = None

        identificador = (self.f_identificador.value or "").strip().upper()
        if not identificador:
            self.f_identificador.error = "Escribe una placa o un ID"
            page.update()
            return
        try:
            peso = float((self.f_peso.value or "").replace(",", ""))
            if peso <= 0:
                raise ValueError
        except ValueError:
            self.f_peso.error = "Peso inválido: escribe un número mayor que 0"
            page.update()
            return
        if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", (self.f_hora.value or "").strip()):
            self.f_hora.error = "Hora inválida. Usa HH:MM (24 h)"
            page.update()
            return

        camion = await self.app.bd(buscar_camion, identificador)
        if camion is FALLO:
            return
        if camion is None:
            self.f_identificador.error = "No existe ese camión en el catálogo"
            page.update()
            return

        hora, minuto = (int(x) for x in self.f_hora.value.strip().split(":"))
        momento = datetime.now().replace(hour=hora, minute=minuto, second=0, microsecond=0)
        premisas, detalle = premisas_desde_camion(camion, peso, self.f_peligrosa.value, momento,
                                                        self.app.ajustes)
        resultado = evaluar_reglas(**premisas)
        documento = {
            "camion_id": camion["camion_id"], "placa": camion["placa"], "empresa": camion.get("empresa"),
            "peso_kg": peso, "carga_peligrosa": self.f_peligrosa.value, "detalle_premisas": detalle,
            "origen": "busqueda_placa", "fecha": momento,
        }
        await self._mostrar_y_guardar(resultado, documento, detalle)

    async def _evaluar_manual(self, e=None):
        premisas = {clave: interruptor.value for clave, interruptor in self.interruptores.items()}
        resultado = evaluar_reglas(**premisas)
        identificador = (self.f_id_manual.value or "").strip().upper() or None
        documento = {"camion_id": identificador if identificador and identificador.startswith("CAM") else None,
                     "placa": identificador if identificador and not identificador.startswith("CAM") else None,
                     "origen": "formulario_manual", "fecha": datetime.now()}
        await self._mostrar_y_guardar(resultado, documento, None)

    async def _mostrar_y_guardar(self, resultado, documento, detalle):
        self.encender(resultado["resultado"])
        self.t_decision.value = resultado["decision"]
        self.t_decision.color = COLOR_RESULTADO[resultado["resultado"]]
        self.t_causa.value = "Causa: " + resultado["causa"]
        self.fila_reglas.controls = [chip_vf(clave, valor) for clave, valor in resultado["reglas"].items()]

        self.lista_pasos.controls = []
        for numero, paso in enumerate(resultado["explicacion"], start=1):
            es_aviso = paso.startswith("Aviso") or paso.startswith("Advertencia") or "retener" in paso
            self.lista_pasos.controls.append(ft.Row([
                ft.Container(ft.Text(str(numero), size=11, color=ft.Colors.WHITE), width=22, height=22,
                             border_radius=11, bgcolor=NARANJA if es_aviso else MORADO,
                             alignment=ft.Alignment.CENTER),
                ft.Text(paso, size=13, expand=True, selectable=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START))

        self.detalle_premisas.controls = []
        if detalle:
            self.detalle_premisas.controls.append(ft.Text("De dónde salió cada premisa", weight=ft.FontWeight.BOLD))
            for clave in ORDEN_PREMISAS:
                self.detalle_premisas.controls.append(ft.Text(
                    f"{clave} = {'V' if resultado['premisas'][clave] else 'F'}: {detalle[clave]}", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT))

        documento.update({
            "premisas": resultado["premisas"], "reglas": resultado["reglas"],
            "reglas_activadas": resultado["reglas_activadas"], "resultado": resultado["resultado"],
            "decision": resultado["decision"], "causa": resultado["causa"],
            "explicacion": resultado["explicacion"], "operador": self.app.ajustes.get("operador"),
        })
        guardado = await self.app.bd(registrar_acceso, documento)
        self.estado_guardado.value = ("Registrado en la bitácora 'accesos'" if guardado is not FALLO
                                      else "No se guardó: sin conexión a MongoDB")
        self.app.page.update()
        await self.refrescar()

    def _ver(self, acceso):
        page = self.app.page
        pasos = [ft.Text(f"{n}. {p}", size=13, selectable=True) for n, p in enumerate(acceso.get("explicacion", []), 1)]
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"{acceso.get('camion_id') or 'Registro manual'} · {fecha_txt(acceso.get('fecha'))}"),
            content=ft.Container(ft.Column([chip(acceso.get("resultado", "").upper(),
                                                 COLOR_RESULTADO.get(acceso.get("resultado"), MORADO)),
                                            ft.Text(acceso.get("decision", ""), weight=ft.FontWeight.BOLD), *pasos],
                                           tight=True, spacing=8, scroll=ft.ScrollMode.AUTO), width=620),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog())],
        ))
        page.update()

    def _eliminar(self, acceso):
        async def borrar():
            if await self.app.bd(eliminar_acceso, acceso["_id"]) is not FALLO:
                self.app.aviso("Registro eliminado de la bitácora", "ok")
                await self.refrescar()

        confirmar(self.app.page, "Eliminar registro", "¿Eliminar este registro de la bitácora de accesos?", borrar)


# =============================================================================
# SECCIÓN 21: INTERFAZ: SIMULADOR DE TABLAS DE VERDAD
# =============================================================================
# Simulador de tablas de verdad: interruptores que cambian A, E, B y V en vivo.

class VistaSimulador:
    def __init__(self, app):
        self.app = app
        self.valores = {"P": True, "Q": False, "R": False, "S": True, "H": False, "T": False}

        interruptores = []
        for clave in ORDEN_PREMISAS:
            nueva = clave in ("H", "T")
            interruptores.append(ft.Container(
                content=ft.Row([
                    ft.Text(clave, size=20, weight=ft.FontWeight.BOLD, width=28,
                            color=MORADO if not nueva else NARANJA),
                    ft.Column([ft.Text(PREMISAS[clave], size=13),
                               ft.Text("premisa nueva" if nueva else "premisa original", size=10,
                                       color=ft.Colors.ON_SURFACE_VARIANT)], spacing=0, expand=True),
                    ft.Switch(value=self.valores[clave], active_color=MORADO,
                              on_change=lambda e, c=clave: self._cambio(c, e.control.value)),
                ], spacing=10),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ))

        self.semaforo, self.encender = crear_semaforo()
        self.t_decision = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
        self.t_avisos = ft.Column([], spacing=4)
        self.tarjetas_reglas = ft.ResponsiveRow([], spacing=10, run_spacing=10)

        self.tabla_ae = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD)) for c in
                     ["P", "Q", "R", "S", "¬Q", "P∧S", "R∨Q", "A", "E"]],
            rows=[], column_spacing=14, heading_row_height=34, data_row_min_height=28, data_row_max_height=28,
        )
        self.tabla_b = self._tabla_pequena("B", ["R", "H"])
        self.tabla_v = self._tabla_pequena("V", ["S", "T"])

        analisis = analizar_reglas()
        conflictos = [ft.Text(f"• {c['reglas']}: {c['descripcion']} en {c['casos']} de 64 combinaciones "
                              f"(ej. {c['ejemplo']}) → {c['resolucion']}", size=12) for c in analisis["conflictos"]]
        panel_analisis = tarjeta(ft.Column([
            subtitulo("Reto opcional: contradicciones y redundancias", ft.Icons.RULE),
            ft.Text("Conflictos entre reglas (se resuelven por prioridad):", weight=ft.FontWeight.BOLD, size=13),
            *conflictos,
            ft.Text("Implicaciones detectadas (X ⇒ Y):", weight=ft.FontWeight.BOLD, size=13),
            ft.Text(", ".join(analisis["implicaciones"]), size=12),
            ft.Text("Veces que cada regla decide el semáforo: " +
                    ", ".join(f"{k}={v}" for k, v in analisis["veces_que_decide"].items()), size=12),
            ft.Text(f"Combinaciones imposibles de premisas (T ∧ ¬S): {analisis['combinaciones_imposibles']} "
                    "de 64; el motor las marca con una advertencia.", size=12),
            ft.Text(analisis["nota_V"], size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=8))

        self.control = ft.Column([
            titulo_vista("Simulador de tablas de verdad",
                         "Activa los interruptores y observa cómo cambian las reglas en vivo"),
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Premisas", ft.Icons.TOGGLE_ON), *interruptores], spacing=8),
                        col={"xs": 12, "lg": 5}),
                tarjeta(ft.Column([
                    subtitulo("Reglas y decisión", ft.Icons.FUNCTIONS),
                    self.tarjetas_reglas,
                    ft.Row([self.semaforo, ft.Column([self.t_decision, self.t_avisos], expand=True, spacing=6)],
                           spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
                ], spacing=14), col={"xs": 12, "lg": 7}),
            ], spacing=16, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Tabla de verdad original (16 filas): A = P ∧ S ∧ ¬Q,  E = P ∧ (R ∨ Q)",
                                             ft.Icons.TABLE_CHART),
                                   ft.Text("La fila resaltada es la combinación actual (H y T no afectan a A ni E).",
                                           size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                   self.tabla_ae]), col={"xs": 12, "lg": 7}),
                tarjeta(ft.Column([subtitulo("Reglas nuevas", ft.Icons.NEW_RELEASES),
                                   ft.Text("B = R ∧ H  (bloqueo por horario restringido)", size=13),
                                   self.tabla_b,
                                   ft.Text("V = S ∧ T  (aviso de renovación de certificación)", size=13),
                                   self.tabla_v]), col={"xs": 12, "lg": 5}),
            ], spacing=16, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            panel_analisis,
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

        self._actualizar(sin_dibujar=True)

    @staticmethod
    def _tabla_pequena(clave, variables):
        return ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD)) for c in variables + [clave]],
            rows=[], column_spacing=26, heading_row_height=32, data_row_min_height=28, data_row_max_height=28,
        )

    async def refrescar(self):
        self._actualizar()

    def _cambio(self, clave, valor):
        self.valores[clave] = valor
        self._actualizar()

    def _actualizar(self, sin_dibujar=False):
        v = self.valores
        resultado = evaluar_reglas(**v)
        reglas = resultado["reglas"]

        tarjetas = []
        for clave, regla in REGLAS.items():
            valor = reglas[clave]
            color = VERDE if valor else ft.Colors.ON_SURFACE_VARIANT
            tarjetas.append(ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text(clave, size=22, weight=ft.FontWeight.BOLD),
                            ft.Text(_vf(valor), size=22, weight=ft.FontWeight.BOLD, color=color)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(regla["formula"], size=12),
                    ft.Text(regla["nombre"], size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=2),
                padding=12, border_radius=12, col={"xs": 6, "md": 3},
                bgcolor=ft.Colors.with_opacity(0.14, VERDE) if valor else ft.Colors.SURFACE_CONTAINER_HIGH,
                border=ft.Border.all(1, VERDE if valor else ft.Colors.OUTLINE_VARIANT),
            ))
        self.tarjetas_reglas.controls = tarjetas

        self.encender(resultado["resultado"])
        self.t_decision.value = resultado["decision"]
        self.t_decision.color = COLOR_RESULTADO[resultado["resultado"]]
        self.t_avisos.controls = [ft.Text("Causa: " + resultado["causa"], size=12,
                                          color=ft.Colors.ON_SURFACE_VARIANT)]
        for aviso in resultado["avisos"] + resultado["advertencias"]:
            color = ROJO if aviso.startswith("Advertencia") else AMARILLO
            self.t_avisos.controls.append(chip(aviso, color, ft.Icons.WARNING_AMBER))

        resaltado = ft.Colors.with_opacity(0.25, MORADO)
        filas = []
        for fila in tabla_original():
            actual = all(fila[k] == v[k] for k in ("P", "Q", "R", "S"))
            filas.append(ft.DataRow(
                color=resaltado if actual else None,
                cells=[ft.DataCell(ft.Text(_vf(fila[k]), size=12,
                                           weight=ft.FontWeight.BOLD if k in ("A", "E") else None,
                                           color=(VERDE if fila[k] else None) if k in ("A", "E") else None))
                       for k in ["P", "Q", "R", "S", "no_Q", "P_y_S", "R_o_Q", "A", "E"]],
            ))
        self.tabla_ae.rows = filas

        for tabla_control, clave in [(self.tabla_b, "B"), (self.tabla_v, "V")]:
            variables = REGLAS[clave]["variables"]
            tabla_control.rows = [
                ft.DataRow(
                    color=resaltado if all(f[x] == v[x] for x in variables) else None,
                    cells=[ft.DataCell(ft.Text(_vf(f[x]), size=12)) for x in variables] +
                          [ft.DataCell(ft.Text(_vf(f[clave]), size=12, weight=ft.FontWeight.BOLD,
                                               color=VERDE if f[clave] else None))],
                )
                for f in tabla_verdad(clave)
            ]

        if not sin_dibujar:
            self.app.page.update()


# =============================================================================
# SECCIÓN 22: INTERFAZ: BANDEJA DE INCIDENTES
# =============================================================================
# Bandeja de incidentes: pegar un correo, clasificar (híbrido), editar, cambiar estado e historial.

NOMBRE_ESTADO = {"nuevo": "Nuevo", "en_atencion": "En atención", "cerrado": "Cerrado"}


def _opciones(valores):
    return [ft.DropdownOption(key=v, text=v.replace("_", " ")) for v in valores]


class VistaIncidentes:
    def __init__(self, app):
        self.app = app
        self.clasificacion = None  # resultado del clasificador pendiente de guardar
        self.filtro_estado = "todos"

        # --- Formulario del correo ---
        self.f_remitente = ft.TextField(label="Remitente", value="operador.caseta@logismart.example", dense=True)
        self.f_asunto = ft.TextField(label="Asunto", dense=True)
        self.f_cuerpo = ft.TextField(label="Cuerpo del correo", multiline=True, min_lines=5, max_lines=8)
        self.boton_clasificar = ft.FilledButton("Clasificar", icon=ft.Icons.AUTO_AWESOME, on_click=self._clasificar,
                                                bgcolor=MORADO, color=ft.Colors.WHITE, height=44)
        self.cargando = ft.Container(cargando("Clasificando con reglas + LLM..."), visible=False)

        formulario = tarjeta(ft.Column([
            subtitulo("Pegar correo de soporte", ft.Icons.MAIL_OUTLINE),
            self.f_remitente, self.f_asunto, self.f_cuerpo,
            ft.Row([self.boton_clasificar,
                    ft.OutlinedButton("Cargar ejemplo", icon=ft.Icons.SHUFFLE, on_click=self._ejemplo),
                    ft.TextButton("Limpiar", on_click=self._limpiar)], spacing=10, wrap=True),
            self.cargando,
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), col={"xs": 12, "lg": 5})

        # --- Resultado editable ---
        self.r_categoria = ft.Dropdown(label="Categoría", options=_opciones(CATEGORIAS_VALIDAS), dense=True,
                                       expand=True)
        self.r_prioridad = ft.Dropdown(label="Prioridad", options=_opciones(ORDEN_PRIORIDAD), dense=True, width=170)
        self.r_resumen = ft.TextField(label="Resumen", multiline=True, min_lines=2, max_lines=3, dense=True)
        self.r_placa = ft.TextField(label="Placa", dense=True, expand=True)
        self.r_camion = ft.TextField(label="ID camión", dense=True, expand=True)
        self.r_peso = ft.TextField(label="Peso (kg)", dense=True, expand=True)
        self.r_ubicacion = ft.TextField(label="Ubicación", dense=True, expand=True)
        self.r_chips = ft.Row([], spacing=8, wrap=True)
        self.r_motivo = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)
        self.r_comparacion = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.boton_guardar = ft.FilledButton("Guardar incidente", icon=ft.Icons.SAVE, on_click=self._guardar,
                                             bgcolor=VERDE, color=ft.Colors.WHITE, height=44)
        self.panel_resultado = ft.Column([
            self.r_chips, self.r_motivo, self.r_comparacion,
            ft.Row([self.r_categoria, self.r_prioridad], spacing=10),
            self.r_resumen,
            ft.Row([self.r_placa, self.r_camion], spacing=10),
            ft.Row([self.r_peso, self.r_ubicacion], spacing=10),
            ft.Row([self.boton_guardar,
                    ft.Text("Puedes corregir la clasificación antes de guardar.", size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT, expand=True)], spacing=12),
        ], spacing=10, visible=False, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.vacio = ft.Text("Pega un correo y presiona Clasificar.", color=ft.Colors.ON_SURFACE_VARIANT)

        resultado = tarjeta(ft.Column([subtitulo("Resultado de la clasificación", ft.Icons.CATEGORY),
                                       self.vacio, self.panel_resultado], spacing=12), col={"xs": 12, "lg": 7})

        # --- Bandeja ---
        self.selector_estado = ft.SegmentedButton(
            segments=[ft.Segment(value="todos", label=ft.Text("Todos"))] +
                     [ft.Segment(value=e, label=ft.Text(NOMBRE_ESTADO[e])) for e in ESTADOS_INCIDENTE],
            selected=["todos"], show_selected_icon=False, on_change=self._cambiar_filtro,
        )
        self.tabla = tabla(["Fecha", "Asunto", "Categoría", "Prioridad", "Estado", "Revisión", ""])
        self.contador = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.control = ft.Column([
            titulo_vista("Bandeja de incidentes",
                         "Clasificador híbrido: reglas + LLM con JSON validado; si discrepan gana la prioridad más alta"),
            ft.ResponsiveRow([formulario, resultado], spacing=16, run_spacing=16,
                             vertical_alignment=ft.CrossAxisAlignment.START),
            tarjeta(ft.Column([
                ft.Row([subtitulo("Incidentes registrados", ft.Icons.INBOX), ft.Container(expand=True),
                        self.contador]),
                self.selector_estado,
                ft.Row([self.tabla], scroll=ft.ScrollMode.AUTO),
            ], spacing=12)),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------
    async def refrescar(self):
        incidentes = await self.app.bd(listar_incidentes, self.filtro_estado)
        if incidentes is FALLO:
            return
        self.tabla.rows = [
            ft.DataRow(cells=[
                celda(fecha_txt(i.get("fecha")), 115),
                celda(i.get("asunto"), 250),
                celda((i.get("categoria") or "").replace("_", " "), 150),
                ft.DataCell(chip(i.get("prioridad", "-"), COLOR_PRIORIDAD.get(i.get("prioridad"), MORADO))),
                ft.DataCell(chip(NOMBRE_ESTADO.get(i.get("estado"), i.get("estado")),
                                 COLOR_ESTADO.get(i.get("estado"), MORADO))),
                ft.DataCell(ft.Icon(ft.Icons.PERSON_SEARCH, color=NARANJA, tooltip="Requiere revisión humana")
                            if i.get("requiere_revision_humana") else ft.Text("")),
                ft.DataCell(ft.Row([
                    boton_icono(ft.Icons.OPEN_IN_NEW, "Ver / editar", lambda e, i=i: self._detalle(i)),
                    boton_icono(ft.Icons.DELETE_OUTLINE, "Eliminar", lambda e, i=i: self._eliminar(i), ROJO),
                ], spacing=0)),
            ])
            for i in incidentes
        ]
        self.contador.value = f"{len(incidentes)} incidente(s)"
        self.app.page.update()

    async def _cambiar_filtro(self, e):
        self.filtro_estado = e.control.selected[0]
        await self.refrescar()

    # ------------------------------------------------------------------
    def _ejemplo(self, e):
        correos = CORREOS_ETIQUETADOS
        correo = random.choice(correos)
        self.f_remitente.value = correo["remitente"]
        self.f_asunto.value = correo["asunto"]
        self.f_cuerpo.value = correo["cuerpo"]
        self.app.page.update()

    def _limpiar(self, e):
        self.f_asunto.value = ""
        self.f_cuerpo.value = ""
        self.panel_resultado.visible = False
        self.vacio.visible = True
        self.clasificacion = None
        self.app.page.update()

    async def _clasificar(self, e=None):
        page = self.app.page
        self.f_asunto.error = None
        self.f_cuerpo.error = None
        if not (self.f_asunto.value or "").strip():
            self.f_asunto.error = "Escribe el asunto del correo"
        if len((self.f_cuerpo.value or "").strip()) < 10:
            self.f_cuerpo.error = "El cuerpo es muy corto (mínimo 10 caracteres)"
        if self.f_asunto.error or self.f_cuerpo.error:
            page.update()
            return

        self.boton_clasificar.disabled = True
        self.cargando.visible = True
        page.update()

        self.app.recargar_ajustes()
        resultado = await en_hilo(clasificar_incidente, self.f_remitente.value or "", self.f_asunto.value,
                                  self.f_cuerpo.value, self.app.ajustes)

        self.boton_clasificar.disabled = False
        self.cargando.visible = False
        self.clasificacion = resultado
        self._mostrar_resultado(resultado)
        if resultado["fuente_clasificacion"] == "reglas_respaldo":
            self.app.aviso("El LLM no respondió con un JSON válido: se usó el clasificador por reglas.", "aviso")
        page.update()

    def _mostrar_resultado(self, r):
        detalle = r["detalle_clasificacion"]
        chips = [chip(f"Fuente: {r['fuente_clasificacion']}", MORADO, ft.Icons.MEMORY)]
        if r["requiere_revision_humana"]:
            chips.append(chip("Requiere revisión humana", NARANJA, ft.Icons.PERSON_SEARCH))
        else:
            chips.append(chip("Sin discrepancias", VERDE, ft.Icons.CHECK_CIRCLE))
        if detalle.get("llm_latencia_ms"):
            chips.append(chip(f"LLM {detalle['llm_latencia_ms'] / 1000:.1f} s · {detalle.get('llm_intentos')} intento(s)",
                              CIAN, ft.Icons.TIMER))
        self.r_chips.controls = chips
        self.r_motivo.value = r.get("motivo_revision", "")

        reglas_r = detalle["reglas"]
        llm_r = detalle.get("llm")
        self.r_comparacion.value = (f"Reglas: {reglas_r['categoria']} / {reglas_r['prioridad']}  ·  "
                                    f"LLM: {llm_r['categoria'] + ' / ' + llm_r['prioridad'] if llm_r else 'sin respuesta'}")

        self.r_categoria.value = r["categoria"]
        self.r_prioridad.value = r["prioridad"]
        self.r_resumen.value = r["resumen"]
        entidades = r["entidades"]
        self.r_placa.value = entidades.get("placa") or ""
        self.r_camion.value = entidades.get("camion_id") or ""
        self.r_peso.value = str(entidades.get("peso_reportado_kg") or "")
        self.r_ubicacion.value = entidades.get("ubicacion") or ""
        self.panel_resultado.visible = True
        self.vacio.visible = False

    async def _guardar(self, e):
        if not self.clasificacion:
            return
        self.r_peso.error = None
        peso = None
        if (self.r_peso.value or "").strip():
            try:
                peso = float(self.r_peso.value.replace(",", ""))
            except ValueError:
                self.r_peso.error = "Debe ser un número"
                self.app.page.update()
                return

        incidente = dict(self.clasificacion)
        editado = (self.r_categoria.value != incidente["categoria"] or self.r_prioridad.value != incidente["prioridad"])
        incidente.update({
            "categoria": self.r_categoria.value,
            "prioridad": self.r_prioridad.value,
            "resumen": self.r_resumen.value,
            "entidades": {"placa": self.r_placa.value.strip().upper() or None,
                          "camion_id": self.r_camion.value.strip().upper() or None,
                          "peso_reportado_kg": peso,
                          "ubicacion": self.r_ubicacion.value.strip() or None},
            "editado_por_operador": editado,
        })

        # Envío del correo al equipo de soporte (simulado o SMTP según la configuración)
        asunto, cuerpo = correo_para_soporte(incidente)
        envio = await en_hilo(enviar_correo_soporte, incidente["remitente"],
                              self.app.ajustes.get("correo_soporte"), asunto, cuerpo,
                              self.app.ajustes.get("modo_simulacion_correo", True))
        incidente["correo_soporte"] = {"destinatario": self.app.ajustes.get("correo_soporte"), **envio}

        resultado = await self.app.bd(crear_incidente, incidente, self.app.ajustes.get("operador"))
        if resultado is FALLO:
            return
        modo = "simulado" if envio["modo"] == "simulacion" else "SMTP"
        self.app.aviso(f"Incidente guardado. Correo a soporte: {'enviado' if envio['enviado'] else 'falló'} ({modo}).",
                       "ok" if envio["enviado"] else "aviso")
        self._limpiar(None)
        await self.refrescar()

    # ------------------------------------------------------------------
    def _eliminar(self, incidente):
        async def borrar():
            if await self.app.bd(eliminar_incidente, incidente["_id"]) is not FALLO:
                self.app.aviso("Incidente eliminado", "ok")
                await self.refrescar()

        confirmar(self.app.page, "Eliminar incidente", f"¿Eliminar «{incidente.get('asunto')}»?", borrar)

    def _detalle(self, incidente):
        page = self.app.page
        d_estado = ft.Dropdown(label="Estado", value=incidente.get("estado"), dense=True, width=180,
                               options=[ft.DropdownOption(key=e, text=NOMBRE_ESTADO[e]) for e in ESTADOS_INCIDENTE])
        d_categoria = ft.Dropdown(label="Categoría", value=incidente.get("categoria"), dense=True, width=240,
                                  options=_opciones(CATEGORIAS_VALIDAS))
        d_prioridad = ft.Dropdown(label="Prioridad", value=incidente.get("prioridad"), dense=True, width=150,
                                  options=_opciones(ORDEN_PRIORIDAD))
        d_revision = ft.Checkbox(label="Requiere revisión humana", value=bool(incidente.get("requiere_revision_humana")))

        historial = [
            ft.Row([ft.Icon(ft.Icons.CIRCLE, size=8, color=MORADO),
                    ft.Text(f"{fecha_txt(h.get('fecha'))} · {h.get('accion')} · {h.get('detalle')} · {h.get('usuario')}",
                            size=12, expand=True)], spacing=8)
            for h in incidente.get("historial", [])
        ]
        entidades = incidente.get("entidades", {})
        texto_entidades = ", ".join(f"{k}: {v}" for k, v in entidades.items() if v) or "ninguna"

        async def guardar(e):
            cambios = {}
            if d_estado.value != incidente.get("estado"):
                cambios["estado"] = d_estado.value
            if d_categoria.value != incidente.get("categoria"):
                cambios["categoria"] = d_categoria.value
            if d_prioridad.value != incidente.get("prioridad"):
                cambios["prioridad"] = d_prioridad.value
            if d_revision.value != bool(incidente.get("requiere_revision_humana")):
                cambios["requiere_revision_humana"] = d_revision.value
            page.pop_dialog()
            if not cambios:
                return
            accion = "cambio_estado" if list(cambios) == ["estado"] else "editado"
            if await self.app.bd(actualizar_incidente, incidente["_id"], cambios,
                                 self.app.ajustes.get("operador"), accion) is not FALLO:
                self.app.aviso("Incidente actualizado", "ok")
                await self.refrescar()

        page.show_dialog(ft.AlertDialog(
            title=ft.Text(incidente.get("asunto", "Incidente")),
            content=ft.Container(ft.Column([
                ft.Text(f"De: {incidente.get('remitente')} · {fecha_txt(incidente.get('fecha'))}", size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(ft.Text(incidente.get("cuerpo", ""), selectable=True), padding=12, border_radius=10,
                             bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH),
                ft.Text(f"Resumen: {incidente.get('resumen', '-')}", size=13),
                ft.Text(f"Entidades: {texto_entidades}", size=13),
                ft.Text(f"Fuente: {incidente.get('fuente_clasificacion')} · {incidente.get('motivo_revision') or ''}",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row([d_estado, d_categoria, d_prioridad], spacing=10, wrap=True),
                d_revision,
                ft.Text("Historial", weight=ft.FontWeight.BOLD),
                *historial,
            ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO), width=680, height=520),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("Guardar cambios", on_click=guardar, bgcolor=MORADO, color=ft.Colors.WHITE)],
        ))
        page.update()


# =============================================================================
# SECCIÓN 23: INTERFAZ: ASISTENTE
# =============================================================================
# Asistente (chat LLM): responde solo con datos de MongoDB y muestra las fuentes consultadas.

SUGERENCIAS = [
    "¿Por qué CAM-102 fue enviado a inspección?",
    "¿Qué incidentes abiertos hay?",
    "¿Cuáles son los riesgos éticos más altos?",
    "¿Qué accesos fueron rechazados esta semana?",
    "¿Qué pasó con la placa ZZZ-000-Z?",
]

ICONO_COLECCION = {"camiones": ft.Icons.LOCAL_SHIPPING, "accesos": ft.Icons.TRAFFIC,
                   "incidentes": ft.Icons.INBOX, "riesgos_eticos": ft.Icons.SHIELD}


class VistaAsistente:
    def __init__(self, app):
        self.app = app
        self.historial = []  # mensajes previos para preguntas de seguimiento
        self.ocupado = False

        self.chat = ft.ListView(expand=True, spacing=14, auto_scroll=True, padding=ft.Padding.only(right=12))
        self.campo = ft.TextField(hint_text="Pregunta, por ejemplo: ¿por qué CAM-102 fue enviado a inspección?",
                                  expand=True, border_radius=28, filled=True, on_submit=self._enviar,
                                  content_padding=ft.Padding.symmetric(horizontal=20, vertical=14))
        self.boton = ft.IconButton(ft.Icons.SEND_ROUNDED, on_click=self._enviar, bgcolor=MORADO,
                                   icon_color=ft.Colors.WHITE, width=52, height=52, tooltip="Enviar")
        self.barra = ft.ProgressBar(color=CIAN, visible=False)

        sugerencias = ft.Row(
            [ft.OutlinedButton(s, on_click=self._al_sugerir(s)) for s in SUGERENCIAS],
            spacing=8, wrap=True,
        )

        self.control = ft.Column([
            titulo_vista("Asistente explicativo",
                         "RAG sencillo: primero consulta MongoDB, después le pasa esos registros al LLM y cita la fuente",
                         [ft.OutlinedButton("Limpiar chat", icon=ft.Icons.DELETE_SWEEP, on_click=self._limpiar)]),
            sugerencias,
            tarjeta(self.chat, padding=16, expand=True),
            self.barra,
            ft.Row([self.campo, self.boton], spacing=12),
        ], spacing=12, expand=True)

        self._bienvenida()

    def _bienvenida(self):
        self.chat.controls.append(self._burbuja_asistente(
            "Hola. Respondo **solo con información registrada en MongoDB** (camiones, accesos, incidentes y "
            "riesgos) y cito el registro de origen. Si no encuentro datos, te diré que no tengo información.",
            [], None))

    async def refrescar(self):
        self.app.page.update()

    def _limpiar(self, e):
        self.historial = []
        self.chat.controls = []
        self._bienvenida()
        self.app.page.update()

    def _al_sugerir(self, texto):
        # Flet necesita una función async para esperar la respuesta (una lambda no sirve)
        async def manejador(e):
            self.campo.value = texto
            await self._enviar()
        return manejador

    # ------------------------------------------------------------------
    def _burbuja_usuario(self, texto):
        return ft.Row([
            ft.Container(width=140),
            ft.Container(
                content=ft.Text(texto, color=ft.Colors.WHITE, selectable=True),
                padding=ft.Padding.symmetric(horizontal=16, vertical=10),
                border_radius=ft.BorderRadius(top_left=18, top_right=18, bottom_left=18, bottom_right=4),
                gradient=ft.LinearGradient(colors=[MORADO, ROSA], begin=ft.Alignment.TOP_LEFT,
                                           end=ft.Alignment.BOTTOM_RIGHT),
                expand_loose=True,
            ),
        ], alignment=ft.MainAxisAlignment.END)

    def _burbuja_asistente(self, texto, fuentes, latencia_ms, sin_datos=False):
        contenido = [ft.Markdown(texto, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)]
        if fuentes:
            contenido.append(ft.Text("Fuentes consultadas en MongoDB:", size=11, weight=ft.FontWeight.BOLD,
                                     color=ft.Colors.ON_SURFACE_VARIANT))
            contenido.append(ft.Row(
                [chip(f["ref"], CIAN, ICONO_COLECCION.get(f["coleccion"])) for f in fuentes],
                spacing=6, wrap=True))
            citadas = [f["ref"] for f in fuentes if f["ref"] in texto]
            if not citadas:
                contenido.append(ft.Text("Aviso: la respuesta no citó explícitamente las fuentes.", size=11,
                                         color=NARANJA))
        if sin_datos:
            contenido.append(chip("Sin datos en MongoDB: no se consultó al LLM", NARANJA, ft.Icons.INFO_OUTLINE))
        if latencia_ms:
            contenido.append(ft.Text(f"{latencia_ms / 1000:.1f} s · {self.app.ajustes.get('modelo_ollama')}",
                                     size=10, color=ft.Colors.ON_SURFACE_VARIANT))

        return ft.Row([
            ft.Container(ft.Icon(ft.Icons.SMART_TOY, color=ft.Colors.WHITE, size=18), width=36, height=36,
                         border_radius=18, bgcolor=CIAN, alignment=ft.Alignment.CENTER),
            ft.Container(
                content=ft.Column(contenido, spacing=8),
                padding=ft.Padding.symmetric(horizontal=16, vertical=12),
                border_radius=ft.BorderRadius(top_left=18, top_right=18, bottom_left=4, bottom_right=18),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                expand=True,
            ),
            ft.Container(width=80),
        ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=10)

    # ------------------------------------------------------------------
    async def _enviar(self, e=None):
        if self.ocupado:
            return
        pregunta = (self.campo.value or "").strip()
        if len(pregunta) < 3:
            self.campo.error = "Escribe una pregunta"
            self.app.page.update()
            return
        self.campo.error = None
        self.campo.value = ""
        self.chat.controls.append(self._burbuja_usuario(pregunta))
        pensando = ft.Row([cargando("Consultando MongoDB y preparando la respuesta...")])
        self.chat.controls.append(pensando)
        self.ocupado = True
        self.campo.disabled = True
        self.boton.disabled = True
        self.barra.visible = True
        self.app.page.update()

        self.app.recargar_ajustes()
        inicio = time.perf_counter()
        respuesta = await en_hilo(responder_asistente, pregunta, self.historial, self.app.ajustes)
        total_ms = (time.perf_counter() - inicio) * 1000

        self.chat.controls.remove(pensando)
        self.chat.controls.append(self._burbuja_asistente(
            respuesta["respuesta"], respuesta["fuentes"], total_ms if not respuesta["sin_datos"] else None,
            respuesta["sin_datos"]))
        if respuesta.get("error") and respuesta.get("detalle"):
            self.app.aviso("El LLM no respondió; se muestran los registros encontrados.", "aviso")

        self.historial.append({"role": "user", "content": pregunta})
        self.historial.append({"role": "assistant", "content": respuesta["respuesta"]})

        self.ocupado = False
        self.campo.disabled = False
        self.boton.disabled = False
        self.barra.visible = False
        self.app.page.update()
        await self.campo.focus()


# =============================================================================
# SECCIÓN 24: INTERFAZ: RIESGOS ÉTICOS
# =============================================================================
# Riesgos éticos: gráficas, alta/edición/baja y riesgo residual.

class VistaRiesgos:
    def __init__(self, app):
        self.app = app
        self.riesgos = []
        self.grafica_matriz = ft.Container(height=420, alignment=ft.Alignment.CENTER)
        self.grafica_barras = ft.Container(height=420, alignment=ft.Alignment.CENTER)
        self.resumen = ft.Row([], spacing=10, wrap=True)
        self.tabla = tabla(["#", "Módulo", "Riesgo", "Categoría", "Inherente", "Residual", "Reducción", ""])

        self.control = ft.Column([
            titulo_vista("Matriz de riesgos éticos", "Puntaje = probabilidad × impacto (1-25). Residual = después "
                                                     "de aplicar la mitigación",
                         [ft.FilledButton("Nuevo riesgo", icon=ft.Icons.ADD, on_click=lambda e: self._formulario(None),
                                          bgcolor=MORADO, color=ft.Colors.WHITE)]),
            self.resumen,
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Mapa de calor", ft.Icons.GRID_ON), self.grafica_matriz]),
                        col={"xs": 12, "lg": 5}),
                tarjeta(ft.Column([subtitulo("Antes y después de mitigar", ft.Icons.BAR_CHART), self.grafica_barras]),
                        col={"xs": 12, "lg": 7}),
            ], spacing=16, run_spacing=16),
            tarjeta(ft.Column([subtitulo("Riesgos registrados", ft.Icons.LIST_ALT),
                               ft.Text("El número (#) coincide con el de las gráficas.", size=11,
                                       color=ft.Colors.ON_SURFACE_VARIANT),
                               ft.Row([self.tabla], scroll=ft.ScrollMode.AUTO)])),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    async def refrescar(self):
        riesgos = await self.app.bd(listar_riesgos)
        if riesgos is FALLO:
            return
        self.riesgos = riesgos
        oscuro = self.app.oscuro
        self.grafica_matriz.content = imagen(matriz_riesgos(riesgos, oscuro), alto=410)
        self.grafica_barras.content = imagen(riesgo_antes_despues(riesgos, oscuro), alto=410)

        res = resumen_riesgos(riesgos)
        self.resumen.controls = [
            chip(f"{res['total']} riesgos", MORADO, ft.Icons.SHIELD),
            chip(f"Críticos: {res['por_nivel']['crítico']} → {res['por_nivel_residual']['crítico']}", ROJO,
                 ft.Icons.WARNING_AMBER),
            chip(f"Altos: {res['por_nivel']['alto']} → {res['por_nivel_residual']['alto']}", "#ec835a"),
            chip(f"Promedio: {res['promedio_inherente']} → {res['promedio_residual']}", "#00B8D4"),
            chip(f"Reducción total: {res['reduccion_total_pct']} %", "#0ca30c", ft.Icons.TRENDING_DOWN),
        ]

        filas = []
        for numero, r in enumerate(riesgos, start=1):
            e = enriquecer_riesgo(r)
            filas.append(ft.DataRow(cells=[
                celda(numero, 24, negrita=True),
                celda(r.get("modulo"), 140),
                celda(r.get("descripcion"), 280),
                celda(r.get("categoria"), 95),
                ft.DataCell(chip(f"{e['puntaje_inherente']} {e['nivel_inherente']}",
                                 color_nivel(e["puntaje_inherente"]))),
                ft.DataCell(chip(f"{e['puntaje_residual']} {e['nivel_residual']}",
                                 color_nivel(e["puntaje_residual"]))),
                celda(f"{e['reduccion_pct']} %", 60),
                ft.DataCell(ft.Row([
                    boton_icono(ft.Icons.EDIT_OUTLINED, "Editar", lambda ev, r=r: self._formulario(r)),
                    boton_icono(ft.Icons.HISTORY, "Histórico", lambda ev, r=r: self._historico(r)),
                    boton_icono(ft.Icons.DELETE_OUTLINE, "Eliminar", lambda ev, r=r: self._eliminar(r), ROJO),
                ], spacing=0)),
            ]))
        self.tabla.rows = filas
        self.app.page.update()

    # ------------------------------------------------------------------
    def _eliminar(self, riesgo):
        async def borrar():
            if await self.app.bd(eliminar_riesgo, riesgo["_id"]) is not FALLO:
                self.app.aviso("Riesgo eliminado", "ok")
                await self.refrescar()

        confirmar(self.app.page, "Eliminar riesgo", f"¿Eliminar «{riesgo.get('descripcion')}»?", borrar)

    def _historico(self, riesgo):
        page = self.app.page
        lineas = []
        for h in riesgo.get("historico", []):
            cambios = "; ".join(f"{campo}: {antes} → {despues}" for campo, (antes, despues) in h.get("cambios", {}).items())
            lineas.append(ft.Text(f"{fecha_txt(h.get('fecha'))} · {h.get('accion')} · {h.get('usuario')}"
                                  + (f" · {cambios}" if cambios else ""), size=12, selectable=True))
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Histórico del riesgo"),
            content=ft.Container(ft.Column([ft.Text(riesgo.get("descripcion"), weight=ft.FontWeight.BOLD), *lineas],
                                           tight=True, spacing=8, scroll=ft.ScrollMode.AUTO), width=600),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog())],
        ))
        page.update()

    def _formulario(self, riesgo):
        es_nuevo = riesgo is None
        riesgo = riesgo or {"probabilidad": 3, "impacto": 3, "probabilidad_residual": 2, "impacto_residual": 2,
                            "categoria": "sesgo"}
        page = self.app.page

        f_modulo = ft.TextField(label="Módulo del sistema", value=riesgo.get("modulo", ""))
        f_descripcion = ft.TextField(label="Descripción del riesgo", value=riesgo.get("descripcion", ""),
                                     multiline=True, min_lines=2)
        f_categoria = ft.Dropdown(label="Categoría", value=riesgo.get("categoria"),
                                  options=[ft.DropdownOption(key=c, text=c) for c in CATEGORIAS_RIESGO])
        f_mitigacion = ft.TextField(label="Mitigación", value=riesgo.get("mitigacion", ""), multiline=True,
                                    min_lines=2)
        puntajes = ft.Text("", size=13, weight=ft.FontWeight.BOLD)
        errores = ft.Text("", color=ROJO, size=12)

        def deslizador(etiqueta, valor):
            texto = ft.Text(f"{etiqueta}: {valor}", size=12)
            control = ft.Slider(min=1, max=5, divisions=4, value=valor, label="{value}", active_color=MORADO)

            def cambio(e):
                texto.value = f"{etiqueta}: {int(control.value)}"
                actualizar()

            control.on_change = cambio
            return control, ft.Column([texto, control], spacing=0, expand=True)

        s_p, c_p = deslizador("Probabilidad (antes)", riesgo.get("probabilidad", 3))
        s_i, c_i = deslizador("Impacto (antes)", riesgo.get("impacto", 3))
        s_pr, c_pr = deslizador("Probabilidad (después de mitigar)", riesgo.get("probabilidad_residual", 2))
        s_ir, c_ir = deslizador("Impacto (después de mitigar)", riesgo.get("impacto_residual", 2))

        def actualizar():
            inh = int(s_p.value) * int(s_i.value)
            res = int(s_pr.value) * int(s_ir.value)
            puntajes.value = (f"Inherente: {inh} ({nivel_riesgo(inh)})   →   Residual: {res} ({nivel_riesgo(res)})")
            puntajes.color = color_nivel(res)
            page.update()

        async def guardar(e):
            datos = {
                "modulo": (f_modulo.value or "").strip(),
                "descripcion": (f_descripcion.value or "").strip(),
                "categoria": f_categoria.value,
                "mitigacion": (f_mitigacion.value or "").strip(),
                "probabilidad": int(s_p.value), "impacto": int(s_i.value),
                "probabilidad_residual": int(s_pr.value), "impacto_residual": int(s_ir.value),
            }
            lista_errores = validar_riesgo(datos)
            if lista_errores:
                errores.value = "\n".join(lista_errores)
                page.update()
                return
            operador = self.app.ajustes.get("operador")
            if es_nuevo:
                resultado = await self.app.bd(crear_riesgo, datos, operador)
            else:
                resultado = await self.app.bd(actualizar_riesgo, riesgo["_id"], datos, operador)
            if resultado is FALLO:
                return
            page.pop_dialog()
            self.app.aviso("Riesgo guardado", "ok")
            await self.refrescar()

        inicial = int(riesgo.get("probabilidad", 3)) * int(riesgo.get("impacto", 3))
        residual = int(riesgo.get("probabilidad_residual", 2)) * int(riesgo.get("impacto_residual", 2))
        puntajes.value = (f"Inherente: {inicial} ({nivel_riesgo(inicial)})   →   "
                          f"Residual: {residual} ({nivel_riesgo(residual)})")

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Nuevo riesgo" if es_nuevo else "Editar riesgo"),
            content=ft.Container(ft.Column([f_modulo, f_descripcion, f_categoria, ft.Row([c_p, c_i], spacing=10),
                                            f_mitigacion, ft.Row([c_pr, c_ir], spacing=10), puntajes, errores],
                                           tight=True, spacing=10, scroll=ft.ScrollMode.AUTO,
                                           horizontal_alignment=ft.CrossAxisAlignment.STRETCH), width=620),
            actions=[ft.TextButton("Cancelar", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("Guardar", on_click=guardar, bgcolor=MORADO, color=ft.Colors.WHITE)],
        ))
        page.update()


# =============================================================================
# SECCIÓN 25: INTERFAZ: REPORTES
# =============================================================================
# Reportes: exportar a PDF/CSV/JSON y ver los resultados del experimento de clasificación.

COLECCIONES = [
    ("accesos", "Bitácora de accesos", ft.Icons.TRAFFIC),
    ("incidentes", "Incidentes", ft.Icons.INBOX),
    ("riesgos_eticos", "Riesgos éticos", ft.Icons.SHIELD),
    ("camiones", "Camiones", ft.Icons.LOCAL_SHIPPING),
    ("evaluaciones_llm", "Evaluaciones del LLM", ft.Icons.SMART_TOY),
]


class VistaReportes:
    def __init__(self, app):
        self.app = app
        self.filtro = FiltroFechas(app.page, self._nada, inicial="todo")
        self.archivos = ft.Column([], spacing=6)
        self.experimento = ft.Column([], spacing=12)
        self.boton_experimento = ft.FilledButton("Ejecutar experimento completo", icon=ft.Icons.SCIENCE,
                                                 on_click=self._ejecutar_experimento, bgcolor=MORADO,
                                                 color=ft.Colors.WHITE)
        self.estado_experimento = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        tarjetas = []
        for clave, nombre, icono in COLECCIONES:
            tarjetas.append(tarjeta(ft.Column([
                ft.Row([ft.Icon(icono, color=MORADO), ft.Text(nombre, weight=ft.FontWeight.BOLD)], spacing=8),
                ft.Row([
                    ft.OutlinedButton("CSV", icon=ft.Icons.TABLE_VIEW, on_click=self._al_exportar(clave, "csv")),
                    ft.OutlinedButton("JSON", icon=ft.Icons.DATA_OBJECT, on_click=self._al_exportar(clave, "json")),
                ], spacing=8),
            ], spacing=10), padding=16, col={"xs": 12, "sm": 6, "lg": 4}))

        tarjetas.append(tarjeta(ft.Column([
            ft.Row([ft.Icon(ft.Icons.PICTURE_AS_PDF, color=ROSA),
                    ft.Text("Reporte general", weight=ft.FontWeight.BOLD)], spacing=8),
            ft.FilledButton("Generar PDF", icon=ft.Icons.PICTURE_AS_PDF, on_click=self._pdf, bgcolor=ROSA,
                            color=ft.Colors.WHITE),
        ], spacing=10), padding=16, col={"xs": 12, "sm": 6, "lg": 4}))

        self.control = ft.Column([
            titulo_vista("Reportes", f"Los archivos se guardan en: {CARPETA_EXPORTACIONES}"),
            ft.Row([ft.Text("Periodo:", size=13), self.filtro.control], spacing=10, wrap=True),
            ft.ResponsiveRow(tarjetas, spacing=14, run_spacing=14),
            tarjeta(ft.Column([subtitulo("Archivos generados en esta sesión", ft.Icons.FOLDER_OPEN), self.archivos],
                              spacing=8)),
            tarjeta(ft.Column([
                ft.Row([subtitulo("Experimento: reglas vs LLM vs híbrido", ft.Icons.SCIENCE),
                        ft.Container(expand=True), self.boton_experimento]),
                ft.Text("Usa los 36 correos etiquetados a mano (sección 14 del archivo). "
                        "También se puede correr en terminal: python3 logismart.py --experimento", size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                self.estado_experimento,
                self.experimento,
            ], spacing=10)),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    async def _nada(self):
        self.app.page.update()

    async def refrescar(self):
        self._mostrar_experimento()
        self.app.page.update()

    # ------------------------------------------------------------------
    def _registrar_archivo(self, ruta):
        self.archivos.controls.insert(0, ft.Row([ft.Icon(ft.Icons.INSERT_DRIVE_FILE, size=16, color=CIAN),
                                                 ft.Text(str(ruta), size=12, selectable=True)], spacing=8))
        self.app.aviso(f"Archivo generado: {ruta.name}", "ok")

    @staticmethod
    def _consultar(coleccion, desde, hasta):
        if coleccion == "accesos":
            return listar_accesos(desde, hasta, limite=100000)
        if coleccion == "incidentes":
            return listar_incidentes(None, desde, hasta, limite=100000)
        if coleccion == "riesgos_eticos":
            return [enriquecer_riesgo(r) for r in listar_riesgos()]
        if coleccion == "camiones":
            return listar_camiones()
        return listar_evaluaciones(limite=100000)

    def _al_exportar(self, coleccion, formato):
        async def manejador(e):
            await self._exportar(coleccion, formato)
        return manejador

    async def _exportar(self, coleccion, formato):
        desde, hasta = self.filtro.rango()
        datos = await self.app.bd(self._consultar, coleccion, desde, hasta)
        if datos is FALLO:
            return
        if formato == "csv":
            ruta = await en_hilo(exportar_csv, coleccion, datos)
        else:
            ruta = await en_hilo(exportar_json, coleccion, datos)
        self._registrar_archivo(ruta)
        self.app.page.update()

    async def _pdf(self, e):
        desde, hasta = self.filtro.rango()

        def preparar():
            datos_ind = indicadores(desde, hasta)
            accesos = listar_accesos(desde, hasta, limite=50)
            incidentes = listar_incidentes(None, desde, hasta, limite=50)
            riesgos = listar_riesgos()
            imagenes = [
                incidentes_por_semana(incidentes_por_categoria_semana(desde, hasta), False),
                accesos_por_resultado(datos_ind, False),
                riesgo_antes_despues(riesgos, False),
            ]
            return reporte_pdf(datos_ind, accesos, incidentes, riesgos, imagenes,
                                        self.filtro.descripcion())

        self.app.aviso("Generando PDF...", "info")
        ruta = await self.app.bd(preparar)
        if ruta is FALLO:
            return
        self._registrar_archivo(ruta)
        self.app.page.update()

    # ------------------------------------------------------------------
    def _mostrar_experimento(self):
        archivo = SALIDA_JSON
        if not archivo.exists():
            self.experimento.controls = [ft.Text("Aún no hay resultados. Ejecuta el experimento.",
                                                 color=ft.Colors.ON_SURFACE_VARIANT)]
            return
        resultados = json.loads(archivo.read_text(encoding="utf-8"))

        filas = []
        for m in resultados["clasificadores"]:
            filas.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(m["clasificador"], weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(f"{m['exactitud_categoria'] * 100:.1f} %")),
                ft.DataCell(ft.Text(f"{m['exactitud_prioridad'] * 100:.1f} %")),
                ft.DataCell(ft.Text(f"{m['exactitud_formal'] * 100:.1f} %")),
                ft.DataCell(ft.Text(f"{m['exactitud_informal'] * 100:.1f} %")),
                ft.DataCell(ft.Text(f"{m['latencia_promedio_ms']:.1f} ms")),
            ]))
        tabla_resultados = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD)) for c in
                     ["Clasificador", "Exactitud categoría", "Exactitud prioridad", "Formal", "Informal",
                      "Latencia prom."]],
            rows=filas,
        )

        datos = [chip(f"{resultados['total_correos']} correos", MORADO),
                 chip(f"{resultados['correos_informales']} informales", NARANJA),
                 chip(f"Modelo {resultados['modelo']}", CIAN)]
        if "json_validos_pct" in resultados:
            datos.append(chip(f"JSON válidos {resultados['json_validos_pct']} %", VERDE))
            datos.append(chip(f"Revisión humana {resultados['revision_humana_pct']} %", NARANJA))
        else:
            datos.append(chip("Solo reglas: ejecuta el experimento completo para comparar con el LLM", NARANJA))

        matrices = []
        for m in resultados["clasificadores"]:
            png = grafica_matriz_confusion(m["matriz_confusion"], CATEGORIAS_VALIDAS,
                                            f"Matriz de confusión · {m['clasificador']}", self.app.oscuro)
            matrices.append(ft.Container(imagen(png, alto=380), col={"xs": 12, "lg": 4}))

        self.experimento.controls = [
            ft.Text(f"Última ejecución: {resultados['fecha']}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Row(datos, spacing=8, wrap=True),
            ft.Row([tabla_resultados], scroll=ft.ScrollMode.AUTO),
            ft.ResponsiveRow(matrices, spacing=12),
        ]

    async def _ejecutar_experimento(self, e):
        self.boton_experimento.disabled = True
        self.estado_experimento.value = ("Ejecutando... clasifica 36 correos con el LLM, puede tardar varios "
                                         "minutos. El avance se ve en la terminal.")
        self.app.page.update()
        try:
            await en_hilo(ejecutar_experimento, False, True, None)
            self.estado_experimento.value = "Experimento terminado. Resultados también en la carpeta resultados_experimento/"
            self.app.aviso("Experimento terminado", "ok")
        except Exception as error:  # noqa: BLE001
            self.estado_experimento.value = f"Error: {error}"
            self.app.aviso(f"El experimento falló: {error}", "error")
        self.boton_experimento.disabled = False
        self._mostrar_experimento()
        self.app.page.update()


# =============================================================================
# SECCIÓN 26: INTERFAZ: CONFIGURACIÓN
# =============================================================================
# Configuración: modelo de Ollama, umbrales, modo simulación de correo y datos de demostración.

def _ocultar_contrasena(uri):
    return re.sub(r"//([^:/]+):([^@]+)@", r"//\1:****@", uri)


class VistaConfiguracion:
    def __init__(self, app):
        self.app = app
        a = app.ajustes

        self.f_modelo = ft.Dropdown(label="Modelo de Ollama", value=a["modelo_ollama"], editable=True,
                                    options=[ft.DropdownOption(key=a["modelo_ollama"], text=a["modelo_ollama"])],
                                    width=320)
        self.f_temperatura = ft.Slider(min=0, max=1, divisions=10, value=a["temperatura"], label="{value}",
                                       active_color=MORADO)
        self.f_ctx = ft.Dropdown(label="Contexto (num_ctx)", value=str(a["num_ctx"]), width=200,
                                 options=[ft.DropdownOption(key=v, text=v) for v in ["2048", "4096", "8192"]])
        self.f_reintentos = ft.Dropdown(label="Reintentos si el JSON es inválido", value=str(a["reintentos_llm"]),
                                        width=260, options=[ft.DropdownOption(key=v, text=v) for v in ["0", "1", "2"]])

        self.f_peso = ft.TextField(label="Peso límite (kg) → premisa Q", value=str(a["peso_limite_kg"]), width=260)
        self.f_inicio = ft.TextField(label="Horario restringido: inicio (0-23)", value=str(a["hora_restringida_inicio"]),
                                     width=260)
        self.f_fin = ft.TextField(label="Horario restringido: fin (0-23)", value=str(a["hora_restringida_fin"]),
                                  width=260)
        self.f_dias = ft.TextField(label="Días de aviso de certificación → T", value=str(a["dias_aviso_certificacion"]),
                                   width=260)

        self.f_simulacion = ft.Switch(label="Modo simulación de correo (no envía correos reales)",
                                      value=a["modo_simulacion_correo"], active_color=MORADO)
        self.f_correo = ft.TextField(label="Correo del equipo de soporte", value=a["correo_soporte"], width=360)
        self.f_operador = ft.TextField(label="Operador (se guarda en cada decisión)", value=a["operador"], width=360)

        self.estado_demo = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.control = ft.Column([
            titulo_vista("Configuración", "Los ajustes se guardan en json; la conexión se define en .env",
                         [ft.FilledButton("Guardar cambios", icon=ft.Icons.SAVE, on_click=self._guardar,
                                          bgcolor=MORADO, color=ft.Colors.WHITE)]),
            ft.ResponsiveRow([
                tarjeta(ft.Column([
                    subtitulo("LLM local (Ollama)", ft.Icons.SMART_TOY),
                    ft.Row([self.f_modelo, ft.IconButton(ft.Icons.REFRESH, tooltip="Cargar modelos instalados",
                                                         on_click=self._cargar_modelos)]),
                    ft.Text("Temperatura (0 = más consistente)", size=12), self.f_temperatura,
                    ft.Row([self.f_ctx, self.f_reintentos], spacing=12, wrap=True),
                    ft.Text(f"Servidor: {OLLAMA_HOST}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=12), col={"xs": 12, "lg": 6}),
                tarjeta(ft.Column([
                    subtitulo("Umbrales del motor de reglas", ft.Icons.RULE),
                    self.f_peso, ft.Row([self.f_inicio, self.f_fin], spacing=12, wrap=True), self.f_dias,
                ], spacing=12), col={"xs": 12, "lg": 6}),
                tarjeta(ft.Column([
                    subtitulo("Correo y operador", ft.Icons.MAIL_OUTLINE),
                    self.f_simulacion, self.f_correo, self.f_operador,
                    ft.Text("Para envío real define SMTP_HOST, SMTP_PORT, SMTP_USER y SMTP_PASSWORD en el entorno.",
                            size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=12), col={"xs": 12, "lg": 6}),
                tarjeta(ft.Column([
                    subtitulo("Base de datos", ft.Icons.STORAGE),
                    ft.Text(f"MONGO_URI: {_ocultar_contrasena(MONGO_URI)}", size=12, selectable=True),
                    ft.Text(f"Base: {MONGO_DB}", size=12),
                    ft.Text("Para usar el clúster Atlas del profesor cambia MONGO_URI en el archivo .env y "
                            "reinicia la aplicación.", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row([
                        ft.OutlinedButton("Cargar datos demo", icon=ft.Icons.DATASET,
                                          on_click=lambda e: self._demo(False)),
                        ft.OutlinedButton("Reiniciar con datos demo", icon=ft.Icons.RESTART_ALT,
                                          on_click=lambda e: self._demo(True), style=ft.ButtonStyle(color=ROJO)),
                    ], spacing=10, wrap=True),
                    self.estado_demo,
                ], spacing=12), col={"xs": 12, "lg": 6}),
            ], spacing=16, run_spacing=16),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    async def refrescar(self):
        await self._cargar_modelos()

    async def _cargar_modelos(self, e=None):
        modelos = await en_hilo(listar_modelos)
        actual = self.f_modelo.value
        nombres = sorted(set(modelos + ([actual] if actual else [])))
        self.f_modelo.options = [ft.DropdownOption(key=m, text=m) for m in nombres]
        if e is not None:
            self.app.aviso(f"{len(modelos)} modelo(s) instalados en Ollama" if modelos else
                           "No se pudo consultar Ollama", "info" if modelos else "aviso")
        self.app.page.update()

    async def _guardar(self, e):
        campos_enteros = [(self.f_peso, 1, 200000), (self.f_inicio, 0, 23), (self.f_fin, 0, 23), (self.f_dias, 0, 365)]
        hay_error = False
        for campo, minimo, maximo in campos_enteros:
            campo.error = None
            try:
                valor = int(float(campo.value))
                if not minimo <= valor <= maximo:
                    raise ValueError
            except (TypeError, ValueError):
                campo.error = f"Número entero entre {minimo} y {maximo}"
                hay_error = True
        if not (self.f_modelo.value or "").strip():
            self.f_modelo.error_text = "Elige un modelo"
            hay_error = True
        if hay_error:
            self.app.page.update()
            return

        ajustes = cargar_config()
        ajustes.update({
            "modelo_ollama": self.f_modelo.value.strip(),
            "temperatura": round(float(self.f_temperatura.value), 2),
            "num_ctx": int(self.f_ctx.value),
            "reintentos_llm": int(self.f_reintentos.value),
            "peso_limite_kg": int(float(self.f_peso.value)),
            "hora_restringida_inicio": int(self.f_inicio.value),
            "hora_restringida_fin": int(self.f_fin.value),
            "dias_aviso_certificacion": int(self.f_dias.value),
            "modo_simulacion_correo": self.f_simulacion.value,
            "correo_soporte": self.f_correo.value.strip(),
            "operador": self.f_operador.value.strip() or "operador",
        })
        await en_hilo(guardar_config, ajustes)
        self.app.recargar_ajustes()
        self.app.texto_operador.value = f"Operador: {ajustes['operador']}"
        await self.app.verificar_conexiones()
        self.app.aviso("Configuración guardada", "ok")

    def _demo(self, reiniciar):
        async def cargar():
            self.estado_demo.value = "Cargando datos de demostración..."
            self.app.page.update()
            resultado = await self.app.bd(cargar_datos_demo, reiniciar)
            if resultado is not FALLO:
                self.estado_demo.value = resultado
                self.app.aviso(resultado, "ok")
                if self.app.vista_actual is not self:
                    await self.app.vista_actual.refrescar()
            self.app.page.update()

        if reiniciar:
            confirmar(self.app.page, "Reiniciar base de datos",
                      "Se BORRARÁN todas las colecciones y se cargarán los datos de demostración. ¿Continuar?",
                      cargar, "Borrar y cargar")
        else:
            self.app.page.run_task(cargar)


# =============================================================================
# SECCIÓN 27: INTERFAZ: VENTANA PRINCIPAL
# =============================================================================
# Ventana principal de LogiSmart (Flet).
#
# Estructura:
#     - Barra de navegación lateral con las 9 pantallas.
#     - Barra de estado con la conexión a MongoDB y a Ollama.
#     - Área de contenido donde se muestra la pantalla seleccionada.

class App:
    """Estado compartido de la aplicación y navegación entre pantallas."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.ajustes = cargar_config()
        self.oscuro = True
        self.vistas = {}
        self.vista_actual = None
        self.mongo_ok = False

    # ------------------------------------------------------------------
    # Acceso a datos con manejo de errores
    # ------------------------------------------------------------------
    async def bd(self, funcion, *args, **kwargs):
        """
        Ejecuta una operación de base de datos en segundo plano.
        Si MongoDB falla muestra el error y devuelve FALLO.
        """
        try:
            resultado = await en_hilo(funcion, *args, **kwargs)
            if not self.mongo_ok:
                self.mongo_ok = True
                self.actualizar_insignia_mongo(True, "MongoDB conectado")
            return resultado
        except ErrorBaseDatos as error:
            reiniciar_conexion()
            self.mongo_ok = False
            self.actualizar_insignia_mongo(False, "Sin conexión a MongoDB")
            aviso(self.page, str(error), "error")
            return FALLO

    def aviso(self, texto, tipo="info"):
        aviso(self.page, texto, tipo)

    def recargar_ajustes(self):
        self.ajustes = cargar_config()

    # ------------------------------------------------------------------
    # Insignias de conexión
    # ------------------------------------------------------------------
    def actualizar_insignia_mongo(self, ok, texto):
        self.punto_mongo.color = VERDE if ok else ROJO
        self.texto_mongo.value = texto
        self.page.update()

    def actualizar_insignia_ollama(self, ok, texto):
        self.punto_ollama.color = VERDE if ok else ROJO
        self.texto_ollama.value = texto
        self.page.update()

    async def verificar_conexiones(self, e=None):
        self.texto_mongo.value = "Verificando..."
        self.texto_ollama.value = "Verificando..."
        self.page.update()

        ok_mongo, mensaje_mongo = await en_hilo(verificar_conexion)
        self.mongo_ok = ok_mongo
        self.actualizar_insignia_mongo(ok_mongo, mensaje_mongo if ok_mongo else "Sin conexión a MongoDB")
        if not ok_mongo:
            self.aviso(mensaje_mongo, "error")

        ok_llm, mensaje_llm = await en_hilo(verificar_ollama)
        modelo = self.ajustes.get("modelo_ollama")
        self.actualizar_insignia_ollama(ok_llm, f"{modelo} · Ollama" if ok_llm else "Ollama sin conexión")
        return ok_mongo

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------
    async def ir_a(self, indice):
        clave = DESTINOS[indice][0]
        if clave not in self.vistas:
            self.vistas[clave] = CONSTRUCTORES[clave](self)
        vista = self.vistas[clave]
        self.vista_actual = vista
        self.riel.selected_index = indice
        self.contenido.content = vista.control
        self.page.update()
        await vista.refrescar()

    async def al_navegar(self, e):
        await self.ir_a(e.control.selected_index)

    async def cambiar_tema(self, e):
        self.oscuro = e.control.value
        self.page.theme_mode = ft.ThemeMode.DARK if self.oscuro else ft.ThemeMode.LIGHT
        self.page.update()
        if self.vista_actual:
            await self.vista_actual.refrescar()  # las gráficas se redibujan con el tema nuevo

    # ------------------------------------------------------------------
    # Construcción de la ventana
    # ------------------------------------------------------------------
    def construir(self):
        page = self.page
        page.title = "LogiSmart · Centro de control inteligente"
        page.window.width = 1360
        page.window.height = 860
        page.window.min_width = 1100
        page.window.min_height = 680
        page.padding = 0
        page.spacing = 0
        # Fuente DejaVu (viene con matplotlib): tiene los símbolos lógicos (∧ ∨ ¬ → ⇒ ≥)
        page.fonts = {"DejaVu Sans": "/DejaVuSans.ttf", "DejaVu Sans Bold": "/DejaVuSans-Bold.ttf"}
        page.theme = ft.Theme(color_scheme_seed=MORADO, font_family="DejaVu Sans")
        page.dark_theme = ft.Theme(color_scheme_seed=MORADO, font_family="DejaVu Sans")
        page.theme_mode = ft.ThemeMode.DARK

        logo = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.LOCAL_SHIPPING, color=ft.Colors.WHITE, size=26),
                        padding=10, border_radius=14,
                        gradient=ft.LinearGradient(colors=[MORADO, ROSA],
                                                   begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT),
                    ),
                    ft.Text("LogiSmart", size=13, weight=ft.FontWeight.BOLD),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
            ),
            padding=ft.Padding.only(top=16, bottom=12),
        )

        self.riel = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=96,
            leading=logo,
            group_alignment=-0.85,
            destinations=[
                ft.NavigationRailDestination(icon=icono, selected_icon=icono_sel, label=etiqueta)
                for _, etiqueta, icono, icono_sel in DESTINOS
            ],
            trailing=ft.Container(
                content=ft.Column(
                    [ft.Switch(value=True, on_change=self.cambiar_tema, active_color=MORADO),
                     ft.Text("Oscuro", size=10)],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0,
                ),
                padding=ft.Padding.only(top=12),
            ),
            on_change=self.al_navegar,
        )

        self.punto_mongo = ft.Icon(ft.Icons.CIRCLE, size=10, color=ft.Colors.AMBER)
        self.texto_mongo = ft.Text("Verificando...", size=12)
        self.punto_ollama = ft.Icon(ft.Icons.CIRCLE, size=10, color=ft.Colors.AMBER)
        self.texto_ollama = ft.Text("Verificando...", size=12)

        def insignia(icono, punto, texto):
            return ft.Container(
                content=ft.Row([ft.Icon(icono, size=16), punto, texto], spacing=6, tight=True),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                border_radius=20, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            )

        self.texto_operador = ft.Text(f"Operador: {self.ajustes.get('operador')}", size=12,
                                      color=ft.Colors.ON_SURFACE_VARIANT)

        barra_estado = ft.Container(
            content=ft.Row(
                [
                    self.texto_operador,
                    ft.Container(expand=True),
                    insignia(ft.Icons.STORAGE, self.punto_mongo, self.texto_mongo),
                    insignia(ft.Icons.SMART_TOY_OUTLINED, self.punto_ollama, self.texto_ollama),
                    ft.IconButton(ft.Icons.REFRESH, tooltip="Volver a probar conexiones",
                                  on_click=self.verificar_conexiones),
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=24, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        self.contenido = ft.Container(expand=True, padding=ft.Padding.only(left=28, right=28, top=20, bottom=12))

        page.add(
            ft.Row(
                [
                    self.riel,
                    ft.VerticalDivider(width=1),
                    ft.Column([barra_estado, self.contenido], expand=True, spacing=0),
                ],
                expand=True,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )


# Las importaciones de las vistas van aquí para evitar importaciones circulares

# (clave, etiqueta, icono, icono seleccionado)
DESTINOS = [
    ("panel", "Panel", ft.Icons.DASHBOARD_OUTLINED, ft.Icons.DASHBOARD),
    ("camiones", "Camiones", ft.Icons.LOCAL_SHIPPING_OUTLINED, ft.Icons.LOCAL_SHIPPING),
    ("acceso", "Acceso", ft.Icons.TRAFFIC_OUTLINED, ft.Icons.TRAFFIC),
    ("simulador", "Simulador", ft.Icons.TOGGLE_ON_OUTLINED, ft.Icons.TOGGLE_ON),
    ("incidentes", "Incidentes", ft.Icons.INBOX_OUTLINED, ft.Icons.INBOX),
    ("asistente", "Asistente", ft.Icons.CHAT_OUTLINED, ft.Icons.CHAT),
    ("riesgos", "Riesgos", ft.Icons.SHIELD_OUTLINED, ft.Icons.SHIELD),
    ("reportes", "Reportes", ft.Icons.DESCRIPTION_OUTLINED, ft.Icons.DESCRIPTION),
    ("configuracion", "Ajustes", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS),
]

CONSTRUCTORES = {
    "panel": VistaPanel,
    "camiones": VistaCamiones,
    "acceso": VistaAcceso,
    "simulador": VistaSimulador,
    "incidentes": VistaIncidentes,
    "asistente": VistaAsistente,
    "riesgos": VistaRiesgos,
    "reportes": VistaReportes,
    "configuracion": VistaConfiguracion,
}


async def main(page: ft.Page):
    app = App(page)
    app.construir()
    page.update()
    await app.verificar_conexiones()
    await app.ir_a(0)


# =============================================================================
# SECCIÓN 28: PRUEBAS UNITARIAS
# =============================================================================
# Incluyen las pruebas ORIGINALES de logiuncodigo.py sin cambiar sus valores esperados.
# Usan MongoDB simulado (mongomock) y un LLM simulado (unittest.mock).
# Ejecutar: python3 logismart.py --tests


def _parche(nombre, **opciones):
    """Reemplaza temporalmente una función de este archivo (por ejemplo, el LLM) en una prueba."""
    return mock.patch.object(sys.modules[__name__], nombre, **opciones)

# Pruebas del motor de reglas.
#
# Incluye las pruebas ORIGINALES de logiuncodigo.py (sección 2) para
# demostrar que separar el código en capas no cambió el comportamiento
# de A y E, más pruebas de las reglas nuevas B y V.

def evaluar_camion(P, Q, R, S):
    """Adaptador con la firma original: devuelve solo A y E."""
    r = evaluar_reglas(P, Q, R, S)
    return {"acceso_estandar": r["reglas"]["A"], "inspeccion_especial": r["reglas"]["E"]}


class TestReglasOriginales(unittest.TestCase):
    """Pruebas portadas sin cambios del script original."""

    ESPERADO = {
        (1, 1, 1, 1): (0, 1), (1, 1, 1, 0): (0, 1), (1, 1, 0, 1): (0, 1), (1, 1, 0, 0): (0, 1),
        (1, 0, 1, 1): (1, 1), (1, 0, 1, 0): (0, 1), (1, 0, 0, 1): (1, 0), (1, 0, 0, 0): (0, 0),
        (0, 1, 1, 1): (0, 0), (0, 1, 1, 0): (0, 0), (0, 1, 0, 1): (0, 0), (0, 1, 0, 0): (0, 0),
        (0, 0, 1, 1): (0, 0), (0, 0, 1, 0): (0, 0), (0, 0, 0, 1): (0, 0), (0, 0, 0, 0): (0, 0),
    }

    def test_tabla_completa(self):
        for (p, q, r, s), (a, e) in self.ESPERADO.items():
            res = evaluar_camion(bool(p), bool(q), bool(r), bool(s))
            self.assertEqual(res["acceso_estandar"], bool(a), f"A mal en {(p, q, r, s)}")
            self.assertEqual(res["inspeccion_especial"], bool(e), f"E mal en {(p, q, r, s)}")

    def test_sin_autorizacion_nunca_pasa(self):
        for q, r, s in itertools.product([True, False], repeat=3):
            res = evaluar_camion(False, q, r, s)
            self.assertFalse(res["acceso_estandar"])
            self.assertFalse(res["inspeccion_especial"])

    def test_sobrepeso_bloquea_acceso_estandar(self):
        for r, s in itertools.product([True, False], repeat=2):
            self.assertFalse(evaluar_camion(True, True, r, s)["acceso_estandar"])

    def test_caso_ambas_reglas_verdaderas(self):
        self.assertEqual(evaluar_camion(True, False, True, True),
                         {"acceso_estandar": True, "inspeccion_especial": True})

    def test_tipo_invalido(self):
        with self.assertRaises(TypeError):
            evaluar_reglas(1, False, False, True)

    def test_tabla_verdad_tiene_16_filas(self):
        self.assertEqual(len(tabla_original()), 16)


class TestReglasNuevas(unittest.TestCase):

    def test_tabla_B(self):
        esperado = {(True, True): True, (True, False): False, (False, True): False, (False, False): False}
        for fila in tabla_verdad("B"):
            self.assertEqual(fila["B"], esperado[(fila["R"], fila["H"])])

    def test_tabla_V(self):
        for fila in tabla_verdad("V"):
            self.assertEqual(fila["V"], fila["S"] and fila["T"])

    def test_bloqueo_horario_gana_sobre_acceso(self):
        r = evaluar_reglas(P=True, Q=False, R=True, S=True, H=True, T=False)
        self.assertTrue(r["reglas"]["A"])
        self.assertTrue(r["reglas"]["B"])
        self.assertEqual(r["resultado"], "rojo")

    def test_inspeccion_gana_sobre_acceso(self):
        r = evaluar_reglas(P=True, Q=False, R=True, S=True, H=False)
        self.assertEqual(r["resultado"], "amarillo")

    def test_acceso_con_aviso_de_renovacion(self):
        r = evaluar_reglas(P=True, Q=False, R=False, S=True, H=False, T=True)
        self.assertEqual(r["resultado"], "verde")
        self.assertTrue(any("renovación" in a for a in r["avisos"]))

    def test_sin_certificacion_es_rojo(self):
        self.assertEqual(evaluar_reglas(True, False, False, False)["resultado"], "rojo")

    def test_explicacion_menciona_formulas(self):
        texto = " ".join(evaluar_reglas(True, True, False, True)["explicacion"])
        self.assertIn("A = P ∧ S ∧ ¬Q", texto)
        self.assertIn("Decisión", texto)

    def test_contradiccion_de_premisas(self):
        r = evaluar_reglas(P=True, Q=False, R=False, S=False, H=False, T=True)
        self.assertTrue(r["advertencias"])

    def test_tabla_completa_64(self):
        self.assertEqual(len(tabla_completa()), 64)

    def test_analisis_detecta_conflictos(self):
        analisis = analizar_reglas()
        reglas_en_conflicto = {c["reglas"] for c in analisis["conflictos"]}
        self.assertIn("A y B", reglas_en_conflicto)
        self.assertIn("B ⇒ R", analisis["implicaciones"])
        self.assertEqual(analisis["combinaciones_imposibles"], 16)


class TestPremisasDesdeDatos(unittest.TestCase):

    def test_horario_cruza_medianoche(self):
        self.assertTrue(es_horario_restringido(23, 22, 6))
        self.assertTrue(es_horario_restringido(3, 22, 6))
        self.assertFalse(es_horario_restringido(12, 22, 6))

    def test_premisas_de_camion(self):
        manana = datetime(2026, 10, 3, 10, 0)
        camion = {"autorizado": True, "certificacion_vence": manana + timedelta(days=10)}
        p, detalle = premisas_desde_camion(camion, 45000, False, manana, {"peso_limite_kg": 40000})
        self.assertEqual(p, {"P": True, "Q": True, "R": False, "S": True, "H": False, "T": True})
        self.assertIn("45,000", detalle["Q"])

    def test_certificacion_vencida(self):
        hoy = datetime(2026, 10, 3, 10, 0)
        camion = {"autorizado": True, "certificacion_vence": hoy - timedelta(days=1)}
        p, _ = premisas_desde_camion(camion, 30000, False, hoy)
        self.assertFalse(p["S"])
        self.assertFalse(p["T"])

# Pruebas del clasificador: reglas (portadas del script original),
# validación pydantic, reintento, respaldo y fusión híbrida.
# El LLM se simula para que las pruebas no dependan de Ollama.

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
        c = clasificar_por_reglas(CORREO["asunto"], CORREO["cuerpo"])
        d = extraer_entidades(CORREO["asunto"], CORREO["cuerpo"])
        self.assertEqual(c["categoria"], "materiales_peligrosos")
        self.assertEqual(c["prioridad"], "critica")
        self.assertEqual(d["placa"], "ABC-123-D")
        self.assertEqual(d["camion_id"], "CAM-102")
        self.assertEqual(d["peso_reportado_kg"], 48500.0)
        self.assertEqual(d["ubicacion"], "andén 3")

    def test_campos_faltantes_son_none(self):
        self.assertEqual(clasificar_por_reglas("Consulta", "Hola, tengo una duda general.")["categoria"], "otro")
        d = extraer_entidades("Consulta", "Hola")
        self.assertIsNone(d["placa"])
        self.assertIsNone(d["peso_reportado_kg"])

    def test_urgencia_escala_prioridad(self):
        self.assertEqual(clasificar_por_reglas("Pantalla lenta", "El sistema carga lento")["prioridad"], "baja")
        self.assertEqual(clasificar_por_reglas("Pantalla lenta urgente", "El sistema carga lento")["prioridad"], "media")

    def test_envio_simulado_y_fallo_smtp(self):
        self.assertTrue(enviar_correo_soporte("a@b.c", "d@e.f", "x", "y", simulacion=True)["enviado"])
        for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
            os.environ.pop(var, None)
        r = enviar_correo_soporte("a@b.c", "d@e.f", "x", "y", simulacion=False)
        self.assertFalse(r["enviado"])
        self.assertIsNotNone(r["error"])


class TestClasificadorLLM(unittest.TestCase):

    @_parche("chat_llm")
    def test_json_valido(self, chat):
        chat.return_value = (JSON_VALIDO, 120.0, "llama3.2")
        r = clasificar_con_llm(CORREO["asunto"], CORREO["cuerpo"])
        self.assertTrue(r["ok"])
        self.assertEqual(r["clasificacion"]["entidades"]["camion_id"], "CAM-102")  # normalizado
        self.assertEqual(r["intentos"], 1)

    @_parche("chat_llm")
    def test_reintenta_si_json_invalido(self, chat):
        chat.side_effect = [("esto no es json", 50.0, "llama3.2"), (JSON_VALIDO, 60.0, "llama3.2")]
        r = clasificar_con_llm(CORREO["asunto"], CORREO["cuerpo"], {"reintentos_llm": 1})
        self.assertTrue(r["ok"])
        self.assertEqual(r["intentos"], 2)
        self.assertEqual(r["latencia_ms"], 110.0)

    @_parche("chat_llm")
    def test_categoria_fuera_del_esquema_es_invalida(self, chat):
        malo = json.loads(JSON_VALIDO)
        malo["categoria"] = "inventada"
        chat.return_value = (json.dumps(malo), 50.0, "llama3.2")
        r = clasificar_con_llm(CORREO["asunto"], CORREO["cuerpo"], {"reintentos_llm": 1})
        self.assertFalse(r["ok"])
        self.assertEqual(r["intentos"], 2)

    @_parche("chat_llm")
    def test_campo_extra_es_invalido(self, chat):
        malo = json.loads(JSON_VALIDO)
        malo["opinion"] = "no debería estar"
        chat.return_value = (json.dumps(malo), 50.0, "llama3.2")
        self.assertFalse(clasificar_con_llm("a", "bbbbbbbbbbbb", {"reintentos_llm": 0})["ok"])

    @_parche("chat_llm", side_effect=ErrorLLM("sin conexión"))
    def test_sin_ollama_no_reintenta(self, chat):
        r = clasificar_con_llm("a", "b", {"reintentos_llm": 3})
        self.assertFalse(r["ok"])
        self.assertEqual(chat.call_count, 1)


class TestHibrido(unittest.TestCase):

    def test_coinciden(self):
        cat, pri, revision, _ = fusionar({"categoria": "sobrepeso", "prioridad": "media"},
                                                 {"categoria": "sobrepeso", "prioridad": "media"})
        self.assertEqual((cat, pri, revision), ("sobrepeso", "media", False))

    def test_discrepan_gana_prioridad_mas_alta(self):
        cat, pri, revision, motivo = fusionar({"categoria": "otro", "prioridad": "baja"},
                                                      {"categoria": "materiales_peligrosos", "prioridad": "critica"})
        self.assertEqual((cat, pri, revision), ("materiales_peligrosos", "critica", True))
        self.assertIn("Discrepancia", motivo)

    def test_misma_prioridad_distinta_categoria(self):
        cat, pri, revision, _ = fusionar({"categoria": "acceso_no_autorizado", "prioridad": "alta"},
                                                 {"categoria": "somnolencia_conductor", "prioridad": "alta"})
        self.assertTrue(revision)
        self.assertEqual(pri, "alta")

    @_parche("registrar_evaluacion")
    @_parche("chat_llm", side_effect=ErrorLLM("sin conexión"))
    def test_respaldo_por_reglas(self, chat, registrar):
        r = clasificar_incidente(**CORREO)
        self.assertEqual(r["fuente_clasificacion"], "reglas_respaldo")
        self.assertEqual(r["categoria"], "materiales_peligrosos")
        registrar.assert_called_once()
        self.assertFalse(registrar.call_args[0][0]["json_valido"])

    @_parche("registrar_evaluacion")
    @_parche("chat_llm")
    def test_hibrido_completo(self, chat, registrar):
        chat.return_value = (JSON_VALIDO, 100.0, "llama3.2")
        r = clasificar_incidente(**CORREO)
        self.assertEqual(r["fuente_clasificacion"], "hibrido")
        self.assertFalse(r["requiere_revision_humana"])
        self.assertTrue(registrar.call_args[0][0]["coincidio_con_reglas"])

# Pruebas de persistencia (MongoDB simulado con mongomock), matriz de
# riesgos (portadas de la sección 4 original) y asistente RAG.

def base_simulada():
    import mongomock
    db = mongomock.MongoClient().logismart_pruebas
    crear_indices(db)
    usar_db_de_pruebas(db)
    return db


class TestRepositorios(unittest.TestCase):

    def setUp(self):
        self.db = base_simulada()
        cargar_datos_demo()

    def test_datos_demo(self):
        self.assertEqual(self.db.camiones.count_documents({}), 12)
        self.assertGreater(self.db.accesos.count_documents({}), 50)
        self.assertEqual(self.db.riesgos_eticos.count_documents({}), 8)

    def test_crud_camion_y_duplicado(self):
        id_nuevo = crear_camion({"camion_id": "cam-900", "placa": "zzz-900-z", "empresa": "Prueba",
                                              "autorizado": True})
        self.assertEqual(buscar_camion("ZZZ-900-Z")["camion_id"], "CAM-900")
        with self.assertRaises(ErrorBaseDatos):
            crear_camion({"camion_id": "CAM-900", "placa": "YYY-900-Y", "empresa": "x"})
        actualizar_camion(id_nuevo, {"empresa": "Otra"})
        self.assertEqual(buscar_camion("CAM-900")["empresa"], "Otra")
        eliminar_camion(id_nuevo)
        self.assertIsNone(buscar_camion("CAM-900"))

    def test_incidente_historial(self):
        id_inc = crear_incidente({"asunto": "x", "categoria": "otro", "prioridad": "baja"})
        actualizar_incidente(id_inc, {"estado": "en_atencion"}, "tester", "cambio_estado")
        inc = obtener_incidente(id_inc)
        self.assertEqual(inc["estado"], "en_atencion")
        self.assertEqual(len(inc["historial"]), 2)
        with self.assertRaises(ErrorBaseDatos):
            actualizar_incidente(id_inc, {"estado": "inventado"})

    def test_agregacion_por_categoria_y_semana(self):
        filas = incidentes_por_categoria_semana()
        self.assertTrue(filas)
        self.assertEqual(set(filas[0]), {"categoria", "semana", "total"})
        self.assertEqual(sum(f["total"] for f in filas), self.db.incidentes.count_documents({}))

    def test_riesgo_historico(self):
        riesgo = listar_riesgos()[0]
        actualizar_riesgo(riesgo["_id"], {"probabilidad": 1}, "tester")
        actualizado = self.db.riesgos_eticos.find_one({"_id": riesgo["_id"]})
        self.assertEqual(actualizado["historico"][-1]["cambios"]["probabilidad"], [riesgo["probabilidad"], 1])

    def test_indicadores(self):
        ind = indicadores()
        self.assertEqual(ind["accesos_registrados"], ind["accesos_verde"] + ind["accesos_amarillo"] + ind["accesos_rojo"])

    def test_id_invalido(self):
        with self.assertRaises(ErrorBaseDatos):
            eliminar_riesgo("no-es-un-id")


class TestMatrizRiesgos(unittest.TestCase):
    """Niveles y validaciones (portado de la sección 4 original)."""

    def test_niveles_limite(self):
        casos = {(1, 4): "bajo", (1, 5): "medio", (2, 5): "alto", (4, 4): "alto", (5, 4): "crítico"}
        for (p, i), esperado in casos.items():
            self.assertEqual(nivel_riesgo(puntaje_riesgo(p, i)), esperado, f"{(p, i)}")

    def test_validaciones(self):
        base = {"modulo": "m", "descripcion": "d", "categoria": "sesgo", "probabilidad": 3, "impacto": 3,
                "probabilidad_residual": 2, "impacto_residual": 2}
        self.assertEqual(validar_riesgo(base), [])
        self.assertTrue(validar_riesgo({**base, "probabilidad": 6}))
        self.assertTrue(validar_riesgo({**base, "categoria": "inventada"}))
        self.assertTrue(validar_riesgo({**base, "modulo": "  "}))
        self.assertTrue(validar_riesgo({**base, "probabilidad_residual": 5, "impacto_residual": 5}))

    def test_riesgo_residual(self):
        e = enriquecer_riesgo({"probabilidad": 4, "impacto": 5, "probabilidad_residual": 2, "impacto_residual": 4})
        self.assertEqual((e["puntaje_inherente"], e["puntaje_residual"]), (20, 8))
        self.assertEqual((e["nivel_inherente"], e["nivel_residual"]), ("crítico", "medio"))
        self.assertEqual(e["reduccion_pct"], 60.0)


class TestAsistenteRAG(unittest.TestCase):

    def setUp(self):
        base_simulada()
        cargar_datos_demo()

    @_parche("chat_llm")
    def test_sin_datos_no_llama_al_llm(self, chat):
        r = responder_asistente("¿Qué pasó con la placa ZZZ-000-Z?")
        self.assertTrue(r["sin_datos"])
        self.assertIn("No tengo información", r["respuesta"])
        chat.assert_not_called()

    def test_recupera_camion_y_accesos(self):
        fuentes = recuperar_fuentes("¿Por qué CAM-102 fue enviado a inspección?")
        colecciones = {f["coleccion"] for f in fuentes}
        self.assertIn("camiones", colecciones)
        self.assertIn("accesos", colecciones)

    @_parche("chat_llm")
    def test_contexto_solo_con_registros(self, chat):
        chat.return_value = ("Respuesta [x]", 10.0, "llama3.2")
        r = responder_asistente("¿Por qué CAM-102 fue enviado a inspección?")
        mensajes = chat.call_args[0][0]
        self.assertIn("CONTEXTO:", mensajes[-1]["content"])
        self.assertIn("CAM-102", mensajes[-1]["content"])
        self.assertFalse(r["sin_datos"])


# =============================================================================
# SECCIÓN 29: PUNTO DE ENTRADA
# =============================================================================

def ejecutar_cli():
    parser = argparse.ArgumentParser(description="LogiSmart · Centro de control inteligente")
    parser.add_argument("--tests", action="store_true", help="ejecuta las pruebas unitarias")
    parser.add_argument("--demo", action="store_true", help="carga los datos de demostración en MongoDB")
    parser.add_argument("--reiniciar", action="store_true", help="con --demo: borra las colecciones antes de cargar")
    parser.add_argument("--experimento", action="store_true", help="experimento: reglas vs LLM vs híbrido")
    parser.add_argument("--solo-reglas", action="store_true", help="con --experimento: sin LLM")
    parser.add_argument("--sin-mongo", action="store_true", help="con --experimento: no guarda en evaluaciones_llm")
    parser.add_argument("--limite", type=int, default=None, help="con --experimento: usa solo N correos")
    parser.add_argument("--tablas", action="store_true", help="imprime tablas de verdad, análisis de reglas y PEAS")
    parser.add_argument("--web", action="store_true", help="abre la interfaz en el navegador (plan B)")
    args = parser.parse_args()

    if args.tests:
        unittest.main(argv=[sys.argv[0], "-v"])
    elif args.demo or args.experimento:
        try:
            if args.demo:
                cargar_datos_demo(args.reiniciar)
            else:
                imprimir_resultados(ejecutar_experimento(args.solo_reglas, not args.sin_mongo, args.limite))
        except ErrorBaseDatos as error:
            print(f"\n[ERROR] {error}")
            print("Sugerencia: enciende MongoDB (sudo systemctl start mongod) o usa --sin-mongo en el experimento.")
            sys.exit(1)
    elif args.tablas:
        print(peas_como_texto())
        print()
        for clave in REGLAS:
            print(tabla_como_texto(clave))
            print()
        print(json.dumps(analizar_reglas(), ensure_ascii=False, indent=2))
    elif args.web:
        print("Abre en tu navegador: http://localhost:8550")
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=8550, no_cdn=True, assets_dir=str(CARPETA_FUENTES))
    else:
        ft.run(main, assets_dir=str(CARPETA_FUENTES))


if __name__ == "__main__":
    ejecutar_cli()