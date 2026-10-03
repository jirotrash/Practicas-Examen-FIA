"""
Diseño PEAS del agente LogiSmart (sección 1 del script original).

P = medida de desempeño, E = entorno, A = actuadores, S = sensores.
Se agregan los nuevos componentes de software de esta versión.
"""

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
