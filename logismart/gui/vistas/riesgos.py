"""Riesgos éticos: gráficas, alta/edición/baja y riesgo residual."""

import flet as ft

from db import repositorios
from gui.comun import (FALLO, MORADO, ROJO, boton_icono, celda, chip, confirmar, fecha_txt, imagen, subtitulo,
                       tabla, tarjeta, titulo_vista)
from reportes import graficas
from riesgos import matriz


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
        riesgos = await self.app.bd(repositorios.listar_riesgos)
        if riesgos is FALLO:
            return
        self.riesgos = riesgos
        oscuro = self.app.oscuro
        self.grafica_matriz.content = imagen(graficas.matriz_riesgos(riesgos, oscuro), alto=410)
        self.grafica_barras.content = imagen(graficas.riesgo_antes_despues(riesgos, oscuro), alto=410)

        res = matriz.resumen(riesgos)
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
            e = matriz.enriquecer(r)
            filas.append(ft.DataRow(cells=[
                celda(numero, 24, negrita=True),
                celda(r.get("modulo"), 140),
                celda(r.get("descripcion"), 280),
                celda(r.get("categoria"), 95),
                ft.DataCell(chip(f"{e['puntaje_inherente']} {e['nivel_inherente']}",
                                 matriz.color_nivel(e["puntaje_inherente"]))),
                ft.DataCell(chip(f"{e['puntaje_residual']} {e['nivel_residual']}",
                                 matriz.color_nivel(e["puntaje_residual"]))),
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
            if await self.app.bd(repositorios.eliminar_riesgo, riesgo["_id"]) is not FALLO:
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
                                  options=[ft.DropdownOption(key=c, text=c) for c in matriz.CATEGORIAS_RIESGO])
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
            puntajes.value = (f"Inherente: {inh} ({matriz.nivel(inh)})   →   Residual: {res} ({matriz.nivel(res)})")
            puntajes.color = matriz.color_nivel(res)
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
            lista_errores = matriz.validar_riesgo(datos)
            if lista_errores:
                errores.value = "\n".join(lista_errores)
                page.update()
                return
            operador = self.app.ajustes.get("operador")
            if es_nuevo:
                resultado = await self.app.bd(repositorios.crear_riesgo, datos, operador)
            else:
                resultado = await self.app.bd(repositorios.actualizar_riesgo, riesgo["_id"], datos, operador)
            if resultado is FALLO:
                return
            page.pop_dialog()
            self.app.aviso("Riesgo guardado", "ok")
            await self.refrescar()

        inicial = int(riesgo.get("probabilidad", 3)) * int(riesgo.get("impacto", 3))
        residual = int(riesgo.get("probabilidad_residual", 2)) * int(riesgo.get("impacto_residual", 2))
        puntajes.value = (f"Inherente: {inicial} ({matriz.nivel(inicial)})   →   "
                          f"Residual: {residual} ({matriz.nivel(residual)})")

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
