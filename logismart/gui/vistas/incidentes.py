"""Bandeja de incidentes: pegar un correo, clasificar (híbrido), editar, cambiar estado e historial."""

import json
import random

import flet as ft

import config
from clasificador import reglas as clasif_reglas
from clasificador.hibrido import clasificar_incidente
from clasificador.reglas import CATEGORIAS_VALIDAS, ORDEN_PRIORIDAD
from db import repositorios
from db.repositorios import ESTADOS_INCIDENTE
from gui import comun
from gui.comun import (COLOR_ESTADO, COLOR_PRIORIDAD, FALLO, MORADO, NARANJA, ROJO, VERDE, boton_icono, celda,
                       chip, confirmar, en_hilo, fecha_txt, subtitulo, tabla, tarjeta, titulo_vista)

NOMBRE_ESTADO = {"nuevo": "Nuevo", "en_atencion": "En atención", "cerrado": "Cerrado"}


def _opciones(valores):
    return [ft.DropdownOption(key=v, text=v.replace("_", " ")) for v in valores]


class VistaIncidentes:
    def __init__(self, app):
        self.app = app
        self.clasificacion = None  # resultado del clasificador pendiente de guardar
        self.filtro_estado = "todos"

        # --- Formulario del correo ---
        self.f_remitente = ft.TextField(label="Remitente", value="operador.caseta@logismart.example", dense=True)
        self.f_asunto = ft.TextField(label="Asunto", dense=True)
        self.f_cuerpo = ft.TextField(label="Cuerpo del correo", multiline=True, min_lines=5, max_lines=8)
        self.boton_clasificar = ft.FilledButton("Clasificar", icon=ft.Icons.AUTO_AWESOME, on_click=self._clasificar,
                                                bgcolor=MORADO, color=ft.Colors.WHITE, height=44)
        self.cargando = ft.Container(comun.cargando("Clasificando con reglas + LLM..."), visible=False)

        formulario = tarjeta(ft.Column([
            subtitulo("Pegar correo de soporte", ft.Icons.MAIL_OUTLINE),
            self.f_remitente, self.f_asunto, self.f_cuerpo,
            ft.Row([self.boton_clasificar,
                    ft.OutlinedButton("Cargar ejemplo", icon=ft.Icons.SHUFFLE, on_click=self._ejemplo),
                    ft.TextButton("Limpiar", on_click=self._limpiar)], spacing=10, wrap=True),
            self.cargando,
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), col={"xs": 12, "lg": 5})

        # --- Resultado editable ---
        self.r_categoria = ft.Dropdown(label="Categoría", options=_opciones(CATEGORIAS_VALIDAS), dense=True,
                                       expand=True)
        self.r_prioridad = ft.Dropdown(label="Prioridad", options=_opciones(ORDEN_PRIORIDAD), dense=True, width=170)
        self.r_resumen = ft.TextField(label="Resumen", multiline=True, min_lines=2, max_lines=3, dense=True)
        self.r_placa = ft.TextField(label="Placa", dense=True, expand=True)
        self.r_camion = ft.TextField(label="ID camión", dense=True, expand=True)
        self.r_peso = ft.TextField(label="Peso (kg)", dense=True, expand=True)
        self.r_ubicacion = ft.TextField(label="Ubicación", dense=True, expand=True)
        self.r_chips = ft.Row([], spacing=8, wrap=True)
        self.r_motivo = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)
        self.r_comparacion = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.boton_guardar = ft.FilledButton("Guardar incidente", icon=ft.Icons.SAVE, on_click=self._guardar,
                                             bgcolor=VERDE, color=ft.Colors.WHITE, height=44)
        self.panel_resultado = ft.Column([
            self.r_chips, self.r_motivo, self.r_comparacion,
            ft.Row([self.r_categoria, self.r_prioridad], spacing=10),
            self.r_resumen,
            ft.Row([self.r_placa, self.r_camion], spacing=10),
            ft.Row([self.r_peso, self.r_ubicacion], spacing=10),
            ft.Row([self.boton_guardar,
                    ft.Text("Puedes corregir la clasificación antes de guardar.", size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT, expand=True)], spacing=12),
        ], spacing=10, visible=False, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.vacio = ft.Text("Pega un correo y presiona Clasificar.", color=ft.Colors.ON_SURFACE_VARIANT)

        resultado = tarjeta(ft.Column([subtitulo("Resultado de la clasificación", ft.Icons.CATEGORY),
                                       self.vacio, self.panel_resultado], spacing=12), col={"xs": 12, "lg": 7})

        # --- Bandeja ---
        self.selector_estado = ft.SegmentedButton(
            segments=[ft.Segment(value="todos", label=ft.Text("Todos"))] +
                     [ft.Segment(value=e, label=ft.Text(NOMBRE_ESTADO[e])) for e in ESTADOS_INCIDENTE],
            selected=["todos"], show_selected_icon=False, on_change=self._cambiar_filtro,
        )
        self.tabla = tabla(["Fecha", "Asunto", "Categoría", "Prioridad", "Estado", "Revisión", ""])
        self.contador = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.control = ft.Column([
            titulo_vista("Bandeja de incidentes",
                         "Clasificador híbrido: reglas + LLM con JSON validado; si discrepan gana la prioridad más alta"),
            ft.ResponsiveRow([formulario, resultado], spacing=16, run_spacing=16,
                             vertical_alignment=ft.CrossAxisAlignment.START),
            tarjeta(ft.Column([
                ft.Row([subtitulo("Incidentes registrados", ft.Icons.INBOX), ft.Container(expand=True),
                        self.contador]),
                self.selector_estado,
                ft.Row([self.tabla], scroll=ft.ScrollMode.AUTO),
            ], spacing=12)),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------
    async def refrescar(self):
        incidentes = await self.app.bd(repositorios.listar_incidentes, self.filtro_estado)
        if incidentes is FALLO:
            return
        self.tabla.rows = [
            ft.DataRow(cells=[
                celda(fecha_txt(i.get("fecha")), 115),
                celda(i.get("asunto"), 250),
                celda((i.get("categoria") or "").replace("_", " "), 150),
                ft.DataCell(chip(i.get("prioridad", "-"), COLOR_PRIORIDAD.get(i.get("prioridad"), MORADO))),
                ft.DataCell(chip(NOMBRE_ESTADO.get(i.get("estado"), i.get("estado")),
                                 COLOR_ESTADO.get(i.get("estado"), MORADO))),
                ft.DataCell(ft.Icon(ft.Icons.PERSON_SEARCH, color=NARANJA, tooltip="Requiere revisión humana")
                            if i.get("requiere_revision_humana") else ft.Text("")),
                ft.DataCell(ft.Row([
                    boton_icono(ft.Icons.OPEN_IN_NEW, "Ver / editar", lambda e, i=i: self._detalle(i)),
                    boton_icono(ft.Icons.DELETE_OUTLINE, "Eliminar", lambda e, i=i: self._eliminar(i), ROJO),
                ], spacing=0)),
            ])
            for i in incidentes
        ]
        self.contador.value = f"{len(incidentes)} incidente(s)"
        self.app.page.update()

    async def _cambiar_filtro(self, e):
        self.filtro_estado = e.control.selected[0]
        await self.refrescar()

    # ------------------------------------------------------------------
    def _ejemplo(self, e):
        correos = json.loads((config.RAIZ / "experimento" / "correos_etiquetados.json").read_text(encoding="utf-8"))
        correo = random.choice(correos)
        self.f_remitente.value = correo["remitente"]
        self.f_asunto.value = correo["asunto"]
        self.f_cuerpo.value = correo["cuerpo"]
        self.app.page.update()

    def _limpiar(self, e):
        self.f_asunto.value = ""
        self.f_cuerpo.value = ""
        self.panel_resultado.visible = False
        self.vacio.visible = True
        self.clasificacion = None
        self.app.page.update()

    async def _clasificar(self, e=None):
        page = self.app.page
        self.f_asunto.error = None
        self.f_cuerpo.error = None
        if not (self.f_asunto.value or "").strip():
            self.f_asunto.error = "Escribe el asunto del correo"
        if len((self.f_cuerpo.value or "").strip()) < 10:
            self.f_cuerpo.error = "El cuerpo es muy corto (mínimo 10 caracteres)"
        if self.f_asunto.error or self.f_cuerpo.error:
            page.update()
            return

        self.boton_clasificar.disabled = True
        self.cargando.visible = True
        page.update()

        self.app.recargar_ajustes()
        resultado = await en_hilo(clasificar_incidente, self.f_remitente.value or "", self.f_asunto.value,
                                  self.f_cuerpo.value, self.app.ajustes)

        self.boton_clasificar.disabled = False
        self.cargando.visible = False
        self.clasificacion = resultado
        self._mostrar_resultado(resultado)
        if resultado["fuente_clasificacion"] == "reglas_respaldo":
            self.app.aviso("El LLM no respondió con un JSON válido: se usó el clasificador por reglas.", "aviso")
        page.update()

    def _mostrar_resultado(self, r):
        detalle = r["detalle_clasificacion"]
        chips = [chip(f"Fuente: {r['fuente_clasificacion']}", MORADO, ft.Icons.MEMORY)]
        if r["requiere_revision_humana"]:
            chips.append(chip("Requiere revisión humana", NARANJA, ft.Icons.PERSON_SEARCH))
        else:
            chips.append(chip("Sin discrepancias", VERDE, ft.Icons.CHECK_CIRCLE))
        if detalle.get("llm_latencia_ms"):
            chips.append(chip(f"LLM {detalle['llm_latencia_ms'] / 1000:.1f} s · {detalle.get('llm_intentos')} intento(s)",
                              comun.CIAN, ft.Icons.TIMER))
        self.r_chips.controls = chips
        self.r_motivo.value = r.get("motivo_revision", "")

        reglas_r = detalle["reglas"]
        llm_r = detalle.get("llm")
        self.r_comparacion.value = (f"Reglas: {reglas_r['categoria']} / {reglas_r['prioridad']}  ·  "
                                    f"LLM: {llm_r['categoria'] + ' / ' + llm_r['prioridad'] if llm_r else 'sin respuesta'}")

        self.r_categoria.value = r["categoria"]
        self.r_prioridad.value = r["prioridad"]
        self.r_resumen.value = r["resumen"]
        entidades = r["entidades"]
        self.r_placa.value = entidades.get("placa") or ""
        self.r_camion.value = entidades.get("camion_id") or ""
        self.r_peso.value = str(entidades.get("peso_reportado_kg") or "")
        self.r_ubicacion.value = entidades.get("ubicacion") or ""
        self.panel_resultado.visible = True
        self.vacio.visible = False

    async def _guardar(self, e):
        if not self.clasificacion:
            return
        self.r_peso.error = None
        peso = None
        if (self.r_peso.value or "").strip():
            try:
                peso = float(self.r_peso.value.replace(",", ""))
            except ValueError:
                self.r_peso.error = "Debe ser un número"
                self.app.page.update()
                return

        incidente = dict(self.clasificacion)
        editado = (self.r_categoria.value != incidente["categoria"] or self.r_prioridad.value != incidente["prioridad"])
        incidente.update({
            "categoria": self.r_categoria.value,
            "prioridad": self.r_prioridad.value,
            "resumen": self.r_resumen.value,
            "entidades": {"placa": self.r_placa.value.strip().upper() or None,
                          "camion_id": self.r_camion.value.strip().upper() or None,
                          "peso_reportado_kg": peso,
                          "ubicacion": self.r_ubicacion.value.strip() or None},
            "editado_por_operador": editado,
        })

        # Envío del correo al equipo de soporte (simulado o SMTP según la configuración)
        asunto, cuerpo = clasif_reglas.correo_para_soporte(incidente)
        envio = await en_hilo(clasif_reglas.enviar_correo_soporte, incidente["remitente"],
                              self.app.ajustes.get("correo_soporte"), asunto, cuerpo,
                              self.app.ajustes.get("modo_simulacion_correo", True))
        incidente["correo_soporte"] = {"destinatario": self.app.ajustes.get("correo_soporte"), **envio}

        resultado = await self.app.bd(repositorios.crear_incidente, incidente, self.app.ajustes.get("operador"))
        if resultado is FALLO:
            return
        modo = "simulado" if envio["modo"] == "simulacion" else "SMTP"
        self.app.aviso(f"Incidente guardado. Correo a soporte: {'enviado' if envio['enviado'] else 'falló'} ({modo}).",
                       "ok" if envio["enviado"] else "aviso")
        self._limpiar(None)
        await self.refrescar()

    # ------------------------------------------------------------------
    def _eliminar(self, incidente):
        async def borrar():
            if await self.app.bd(repositorios.eliminar_incidente, incidente["_id"]) is not FALLO:
                self.app.aviso("Incidente eliminado", "ok")
                await self.refrescar()

        confirmar(self.app.page, "Eliminar incidente", f"¿Eliminar «{incidente.get('asunto')}»?", borrar)

    def _detalle(self, incidente):
        page = self.app.page
        d_estado = ft.Dropdown(label="Estado", value=incidente.get("estado"), dense=True, width=180,
                               options=[ft.DropdownOption(key=e, text=NOMBRE_ESTADO[e]) for e in ESTADOS_INCIDENTE])
        d_categoria = ft.Dropdown(label="Categoría", value=incidente.get("categoria"), dense=True, width=240,
                                  options=_opciones(CATEGORIAS_VALIDAS))
        d_prioridad = ft.Dropdown(label="Prioridad", value=incidente.get("prioridad"), dense=True, width=150,
                                  options=_opciones(ORDEN_PRIORIDAD))
        d_revision = ft.Checkbox(label="Requiere revisión humana", value=bool(incidente.get("requiere_revision_humana")))

        historial = [
            ft.Row([ft.Icon(ft.Icons.CIRCLE, size=8, color=MORADO),
                    ft.Text(f"{fecha_txt(h.get('fecha'))} · {h.get('accion')} · {h.get('detalle')} · {h.get('usuario')}",
                            size=12, expand=True)], spacing=8)
            for h in incidente.get("historial", [])
        ]
        entidades = incidente.get("entidades", {})
        texto_entidades = ", ".join(f"{k}: {v}" for k, v in entidades.items() if v) or "ninguna"

        async def guardar(e):
            cambios = {}
            if d_estado.value != incidente.get("estado"):
                cambios["estado"] = d_estado.value
            if d_categoria.value != incidente.get("categoria"):
                cambios["categoria"] = d_categoria.value
            if d_prioridad.value != incidente.get("prioridad"):
                cambios["prioridad"] = d_prioridad.value
            if d_revision.value != bool(incidente.get("requiere_revision_humana")):
                cambios["requiere_revision_humana"] = d_revision.value
            page.pop_dialog()
            if not cambios:
                return
            accion = "cambio_estado" if list(cambios) == ["estado"] else "editado"
            if await self.app.bd(repositorios.actualizar_incidente, incidente["_id"], cambios,
                                 self.app.ajustes.get("operador"), accion) is not FALLO:
                self.app.aviso("Incidente actualizado", "ok")
                await self.refrescar()

        page.show_dialog(ft.AlertDialog(
            title=ft.Text(incidente.get("asunto", "Incidente")),
            content=ft.Container(ft.Column([
                ft.Text(f"De: {incidente.get('remitente')} · {fecha_txt(incidente.get('fecha'))}", size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Container(ft.Text(incidente.get("cuerpo", ""), selectable=True), padding=12, border_radius=10,
                             bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH),
                ft.Text(f"Resumen: {incidente.get('resumen', '-')}", size=13),
                ft.Text(f"Entidades: {texto_entidades}", size=13),
                ft.Text(f"Fuente: {incidente.get('fuente_clasificacion')} · {incidente.get('motivo_revision') or ''}",
                        size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row([d_estado, d_categoria, d_prioridad], spacing=10, wrap=True),
                d_revision,
                ft.Text("Historial", weight=ft.FontWeight.BOLD),
                *historial,
            ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO), width=680, height=520),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog()),
                     ft.FilledButton("Guardar cambios", on_click=guardar, bgcolor=MORADO, color=ft.Colors.WHITE)],
        ))
        page.update()
