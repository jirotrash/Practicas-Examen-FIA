"""
Gráficas con matplotlib (se devuelven como PNG en bytes).

Se usan en la interfaz (como imagen) y en el reporte PDF.
Colores: paleta categórica validada para daltonismo (orden fijo) y
colores de estado reservados para niveles de riesgo y semáforo.
"""

import io

import matplotlib

matplotlib.use("Agg")  # sin ventana: solo genera imágenes
import matplotlib.pyplot as plt  # noqa: E402

from riesgos import matriz  # noqa: E402

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
            ax.add_patch(plt.Rectangle((i - 0.5, p - 0.5), 1, 1, color=matriz.color_nivel(p * i),
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
        ax.scatter([x1], [y1], s=150, color=matriz.color_nivel(pi * ii), edgecolors=SUPERFICIE[oscuro],
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

    enriquecidos = [matriz.enriquecer(r) for r in riesgos]
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

def matriz_confusion(matriz_valores, etiquetas, titulo, oscuro=False):
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
