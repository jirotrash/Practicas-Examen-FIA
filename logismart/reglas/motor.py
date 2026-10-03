"""
Motor de reglas de LogiSmart (lógica proposicional).

PREMISAS
    P : el vehículo tiene autorización previa
    Q : el peso excede el límite
    R : lleva materiales peligrosos
    S : el conductor tiene certificación vigente
    H : es horario restringido (por defecto 22:00 a 06:00)     <- nueva
    T : la certificación vence en 30 días o menos              <- nueva

REGLAS ORIGINALES
    A (Acceso estándar)      = P ∧ S ∧ ¬Q
    E (Inspección especial)  = P ∧ (R ∨ Q)

REGLAS NUEVAS
    B (Bloqueo por horario)  = R ∧ H
        Los materiales peligrosos no ingresan en horario nocturno:
        hay menos personal de seguridad, menor visibilidad y la
        respuesta ante un derrame es más lenta. Se reprograma la cita.

    V (Aviso de renovación)  = S ∧ T
        La certificación sigue vigente pero está por vencer: se permite
        el paso y se avisa para renovarla antes de que el conductor sea
        rechazado.

PRIORIDAD AL DECIDIR (de mayor a menor; ante la duda, seguridad)
    1. ¬P        -> ROJO     (sin autorización no se evalúa nada más)
    2. B         -> ROJO     (bloqueo por horario)
    3. E         -> AMARILLO (inspección especial)
    4. A         -> VERDE    (acceso estándar; con aviso si V)
    5. otro caso -> ROJO     (autorizado pero sin certificación vigente)
"""

import itertools
from datetime import date, datetime

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

def evaluar(P, Q, R, S, H=False, T=False):
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
        resultado = evaluar(P, Q, R, S)
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
        resultado = evaluar(**premisas)
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


if __name__ == "__main__":
    for clave in REGLAS:
        print(tabla_como_texto(clave))
        print()
    import json
    print(json.dumps(analizar_reglas(), ensure_ascii=False, indent=2))
