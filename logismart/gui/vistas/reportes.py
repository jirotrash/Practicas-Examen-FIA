"""Reportes: exportar a PDF/CSV/JSON y ver los resultados del experimento de clasificación."""

import json

import flet as ft

import config
from db import repositorios
from experimento import evaluar
from gui.comun import (CIAN, FALLO, MORADO, NARANJA, ROSA, VERDE, FiltroFechas, chip, en_hilo, imagen, subtitulo,
                       tarjeta, titulo_vista)
from reportes import exportar, graficas
from riesgos import matriz

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
            titulo_vista("Reportes", f"Los archivos se guardan en: {config.CARPETA_EXPORTACIONES}"),
            ft.Row([ft.Text("Periodo:", size=13), self.filtro.control], spacing=10, wrap=True),
            ft.ResponsiveRow(tarjetas, spacing=14, run_spacing=14),
            tarjeta(ft.Column([subtitulo("Archivos generados en esta sesión", ft.Icons.FOLDER_OPEN), self.archivos],
                              spacing=8)),
            tarjeta(ft.Column([
                ft.Row([subtitulo("Experimento: reglas vs LLM vs híbrido", ft.Icons.SCIENCE),
                        ft.Container(expand=True), self.boton_experimento]),
                ft.Text("Usa los 36 correos etiquetados a mano de experimento/correos_etiquetados.json. "
                        "También se puede correr en terminal: python -m experimento.evaluar", size=12,
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
            return repositorios.listar_accesos(desde, hasta, limite=100000)
        if coleccion == "incidentes":
            return repositorios.listar_incidentes(None, desde, hasta, limite=100000)
        if coleccion == "riesgos_eticos":
            return [matriz.enriquecer(r) for r in repositorios.listar_riesgos()]
        if coleccion == "camiones":
            return repositorios.listar_camiones()
        return repositorios.listar_evaluaciones(limite=100000)

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
            ruta = await en_hilo(exportar.exportar_csv, coleccion, datos)
        else:
            ruta = await en_hilo(exportar.exportar_json, coleccion, datos)
        self._registrar_archivo(ruta)
        self.app.page.update()

    async def _pdf(self, e):
        desde, hasta = self.filtro.rango()

        def preparar():
            indicadores = repositorios.indicadores(desde, hasta)
            accesos = repositorios.listar_accesos(desde, hasta, limite=50)
            incidentes = repositorios.listar_incidentes(None, desde, hasta, limite=50)
            riesgos = repositorios.listar_riesgos()
            imagenes = [
                graficas.incidentes_por_semana(repositorios.incidentes_por_categoria_semana(desde, hasta), False),
                graficas.accesos_por_resultado(indicadores, False),
                graficas.riesgo_antes_despues(riesgos, False),
            ]
            return exportar.reporte_pdf(indicadores, accesos, incidentes, riesgos, imagenes,
                                        self.filtro.descripcion())

        self.app.aviso("Generando PDF...", "info")
        ruta = await self.app.bd(preparar)
        if ruta is FALLO:
            return
        self._registrar_archivo(ruta)
        self.app.page.update()

    # ------------------------------------------------------------------
    def _mostrar_experimento(self):
        archivo = config.RAIZ / "experimento" / "resultados.json"
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
            png = graficas.matriz_confusion(m["matriz_confusion"], evaluar.CATEGORIAS_VALIDAS,
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
            await en_hilo(evaluar.ejecutar, False, True, None)
            self.estado_experimento.value = "Experimento terminado. Resultados también en docs/resultados_experimento.md"
            self.app.aviso("Experimento terminado", "ok")
        except Exception as error:  # noqa: BLE001
            self.estado_experimento.value = f"Error: {error}"
            self.app.aviso(f"El experimento falló: {error}", "error")
        self.boton_experimento.disabled = False
        self._mostrar_experimento()
        self.app.page.update()
