"""
Conexión a MongoDB (local o Atlas).

Toda la aplicación obtiene la base de datos con obtener_db().
Si MongoDB no responde se lanza ErrorBaseDatos con un mensaje
claro, para que la interfaz lo muestre sin "tronar".
"""

from pymongo import MongoClient
from pymongo.errors import PyMongoError

import config


class ErrorBaseDatos(Exception):
    """Error de conexión u operación con MongoDB, con mensaje amigable."""


_cliente = None
_db = None


def obtener_db():
    """Devuelve la base de datos; crea la conexión la primera vez."""
    global _cliente, _db

    if _db is not None:
        return _db

    try:
        # serverSelectionTimeoutMS: si en 4 s no responde, se da por caído
        _cliente = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=4000)
        _cliente.admin.command("ping")
        _db = _cliente[config.MONGO_DB]
        crear_indices(_db)
        return _db
    except PyMongoError as error:
        _cliente = None
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
        destino = "Atlas" if "mongodb.net" in config.MONGO_URI else "local"
        return True, f"MongoDB {destino} · base '{config.MONGO_DB}'"
    except (ErrorBaseDatos, PyMongoError) as error:
        reiniciar_conexion()
        return False, str(error)


def reiniciar_conexion():
    """Olvida la conexión actual (para reintentar después de un error)."""
    global _cliente, _db
    _cliente = None
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
