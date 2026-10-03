"""Catálogo de camiones: alta, búsqueda, edición y baja (CRUD)."""

import re
from datetime import datetime

import flet as ft

from db import repositorios
from gui import comun
from gui.comun import (FALLO, MORADO, NARANJA, ROJO, VERDE, boton_icono, celda, chip, confirmar, fecha_txt, tabla,
                       tarjeta, titulo_vista)

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
        camiones = await self.app.bd(repositorios.listar_camiones, self.busqueda.value or None)
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
            if await self.app.bd(repositorios.eliminar_camion, camion["_id"]) is not FALLO:
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
                resultado = await self.app.bd(repositorios.crear_camion, datos)
            else:
                resultado = await self.app.bd(repositorios.actualizar_camion, camion["_id"], datos)
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
