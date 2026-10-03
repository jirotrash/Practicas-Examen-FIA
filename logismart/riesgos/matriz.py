"""
Matriz de riesgos éticos.

Puntaje = probabilidad (1-5) x impacto (1-5)  -> rango 1..25
    1-4 bajo | 5-9 medio | 10-16 alto | 17-25 crítico

Riesgo residual: el mismo cálculo DESPUÉS de aplicar la mitigación
(probabilidad_residual x impacto_residual).
"""

CATEGORIAS_RIESGO = ["sesgo", "privacidad", "transparencia", "seguridad", "responsabilidad", "otro"]

NIVELES = [
    (17, "crítico", "#D32F2F"),
    (10, "alto", "#F57C00"),
    (5, "medio", "#FBC02D"),
    (1, "bajo", "#388E3C"),
]


def puntaje(probabilidad, impacto):
    return int(probabilidad or 0) * int(impacto or 0)


def nivel(valor):
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
        if puntaje(datos["probabilidad_residual"], datos["impacto_residual"]) > puntaje(datos["probabilidad"], datos["impacto"]):
            errores.append("El riesgo residual no puede ser mayor que el inherente (la mitigación no debe empeorarlo).")
    return errores


def enriquecer(riesgo):
    """Agrega puntajes, niveles y reducción (%) a un documento de riesgo."""
    inherente = puntaje(riesgo.get("probabilidad"), riesgo.get("impacto"))
    residual = puntaje(riesgo.get("probabilidad_residual"), riesgo.get("impacto_residual"))
    reduccion = round(100 * (inherente - residual) / inherente, 1) if inherente else 0
    return {
        **riesgo,
        "puntaje_inherente": inherente,
        "nivel_inherente": nivel(inherente),
        "puntaje_residual": residual,
        "nivel_residual": nivel(residual),
        "reduccion_pct": reduccion,
    }


def resumen(riesgos):
    """Estadísticas de la matriz."""
    enriquecidos = [enriquecer(r) for r in riesgos]
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
