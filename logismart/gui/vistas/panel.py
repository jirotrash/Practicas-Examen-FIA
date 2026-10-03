"""Panel de control: indicadores con filtro de fechas, gráficas y últimos accesos."""

import flet as ft

from db import repositorios
from gui import comun
from gui.comun import (CIAN, FALLO, COLOR_RESULTADO, MORADO, NARANJA, ROJO, FiltroFechas, celda, chip, fecha_txt,
                       imagen, kpi, tabla, tarjeta, titulo_vista)
from reglas.peas import peas_como_texto
from reportes import graficas


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

        self.grafica_semana = ft.Container(comun.cargando(), height=330, alignment=ft.Alignment.CENTER)
        self.grafica_accesos = ft.Container(comun.cargando(), height=330, alignment=ft.Alignment.CENTER)
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
                    tarjeta(ft.Column([comun.subtitulo("Incidentes por categoría y semana", ft.Icons.BAR_CHART),
                                       ft.Text("Agregación de MongoDB: $group por categoría y semana ISO",
                                               size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                       self.grafica_semana]), col={"xs": 12, "lg": 7}),
                    tarjeta(ft.Column([comun.subtitulo("Semáforo de accesos", ft.Icons.TRAFFIC),
                                       ft.Text("Decisiones del motor de reglas en el periodo",
                                               size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                       self.grafica_accesos]), col={"xs": 12, "lg": 5}),
                ], spacing=14, run_spacing=14),
                tarjeta(ft.Column([comun.subtitulo("Últimas decisiones de acceso", ft.Icons.HISTORY),
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
        self.grafica_semana.content = imagen(graficas.incidentes_por_semana(semana, oscuro), alto=320)
        self.grafica_accesos.content = imagen(graficas.accesos_por_resultado(ind, oscuro), alto=320)

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
        return (repositorios.indicadores(desde, hasta),
                repositorios.incidentes_por_categoria_semana(desde, hasta),
                repositorios.listar_accesos(desde, hasta, limite=8))
