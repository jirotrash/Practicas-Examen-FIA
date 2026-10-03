"""
Exportación de reportes a CSV, JSON y PDF.

Los archivos se guardan en la carpeta exportaciones/ del proyecto.
"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import matplotlib
from bson import ObjectId
from fpdf import FPDF

import config
from riesgos import matriz

# Fuente con soporte de acentos y símbolos (viene incluida con matplotlib)
FUENTE_TTF = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
FUENTE_TTF_NEGRITA = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"


def _carpeta():
    config.CARPETA_EXPORTACIONES.mkdir(parents=True, exist_ok=True)
    return config.CARPETA_EXPORTACIONES


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
    for n, r in enumerate([matriz.enriquecer(r) for r in riesgos], start=1):
        filas.append((n, r.get("modulo"), r.get("descripcion"), r.get("categoria"),
                      f"{r['puntaje_inherente']} ({r['nivel_inherente']})",
                      f"{r['puntaje_residual']} ({r['nivel_residual']})"))
    _tabla(pdf, ["#", "Módulo", "Riesgo", "Categoría", "Inherente", "Residual"], filas, [8, 34, 70, 24, 27, 27])

    ruta = _carpeta() / f"reporte_logismart_{_sello()}.pdf"
    pdf.output(str(ruta))
    return ruta
