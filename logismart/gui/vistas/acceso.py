"""Control de acceso: búsqueda por placa o formulario P/Q/R/S, semáforo y explicación."""

import re
from datetime import datetime

import flet as ft

from db import repositorios
from gui import comun
from gui.comun import (AMARILLO, COLOR_RESULTADO, FALLO, MORADO, ROJO, VERDE, boton_icono, celda, chip, chip_vf,
                       confirmar, fecha_txt, subtitulo, tabla, tarjeta, titulo_vista)
from reglas import motor


def crear_semaforo():
    """Devuelve (control, función para encender un color)."""
    luces = {}
    columna = []
    for nombre, color in [("rojo", ROJO), ("amarillo", AMARILLO), ("verde", VERDE)]:
        luz = ft.Container(width=46, height=46, border_radius=23, bgcolor=ft.Colors.with_opacity(0.15, color),
                           border=ft.Border.all(2, ft.Colors.with_opacity(0.35, color)),
                           animate=ft.Animation(300, ft.AnimationCurve.EASE_OUT))
        luces[nombre] = (luz, color)
        columna.append(luz)

    control = ft.Container(
        content=ft.Column(columna, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=12, border_radius=40, bgcolor="#141414", width=72,
    )

    def encender(resultado):
        for nombre, (luz, color) in luces.items():
            activo = nombre == resultado
            luz.bgcolor = color if activo else ft.Colors.with_opacity(0.15, color)
            luz.shadow = ft.BoxShadow(blur_radius=24, color=ft.Colors.with_opacity(0.8, color)) if activo else None

    return control, encender


class VistaAcceso:
    def __init__(self, app):
        self.app = app

        # --- Modo búsqueda por placa ---
        self.f_identificador = ft.TextField(label="Placa o ID del camión", hint_text="ABC-123-D o CAM-102",
                                            capitalization=ft.TextCapitalization.CHARACTERS,
                                            prefix_icon=ft.Icons.SEARCH, on_submit=self._evaluar_placa)
        self.f_peso = ft.TextField(label="Peso en báscula (kg)", value="30000", keyboard_type=ft.KeyboardType.NUMBER,
                                   width=200)
        self.f_hora = ft.TextField(label="Hora de llegada (HH:MM)", value=datetime.now().strftime("%H:%M"), width=200)
        self.f_peligrosa = ft.Switch(label="Lleva materiales peligrosos (R)", value=False, active_color=MORADO)
        modo_placa = ft.Column([
            self.f_identificador,
            ft.Row([self.f_peso, self.f_hora], spacing=12),
            self.f_peligrosa,
            ft.FilledButton("Evaluar acceso", icon=ft.Icons.PLAY_ARROW, on_click=self._evaluar_placa,
                            bgcolor=MORADO, color=ft.Colors.WHITE, height=44),
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

        # --- Modo manual P/Q/R/S/H/T ---
        self.interruptores = {}
        filas = []
        for clave in motor.ORDEN_PREMISAS:
            interruptor = ft.Switch(value=clave in ("P", "S"), active_color=MORADO)
            self.interruptores[clave] = interruptor
            filas.append(ft.Row([ft.Text(clave, weight=ft.FontWeight.BOLD, width=22), interruptor,
                                 ft.Text(motor.PREMISAS[clave], size=12, expand=True)], spacing=6))
        self.f_id_manual = ft.TextField(label="ID o placa (opcional, para la bitácora)", dense=True,
                                        capitalization=ft.TextCapitalization.CHARACTERS)
        modo_manual = ft.Column(filas + [
            self.f_id_manual,
            ft.FilledButton("Evaluar y registrar", icon=ft.Icons.PLAY_ARROW, on_click=self._evaluar_manual,
                            bgcolor=MORADO, color=ft.Colors.WHITE, height=44),
        ], spacing=6, visible=False)

        self.modo_placa = modo_placa
        self.modo_manual = modo_manual
        selector = ft.SegmentedButton(
            segments=[ft.Segment(value="placa", label=ft.Text("Búsqueda por placa"), icon=ft.Icon(ft.Icons.SEARCH)),
                      ft.Segment(value="manual", label=ft.Text("Formulario P/Q/R/S"), icon=ft.Icon(ft.Icons.TUNE))],
            selected=["placa"], on_change=self._cambiar_modo,
        )

        # --- Resultado ---
        self.semaforo, self.encender = crear_semaforo()
        self.t_decision = ft.Text("Evalúa un camión para ver la decisión", size=18, weight=ft.FontWeight.BOLD)
        self.t_causa = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
        self.fila_reglas = ft.Row([], spacing=8, wrap=True)
        self.lista_pasos = ft.Column([], spacing=6)
        self.detalle_premisas = ft.Column([], spacing=4)
        self.estado_guardado = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        resultado = tarjeta(ft.Column([
            subtitulo("Resultado", ft.Icons.TRAFFIC),
            ft.Row([
                self.semaforo,
                ft.Column([self.t_decision, self.t_causa, self.fila_reglas, self.estado_guardado],
                          spacing=8, expand=True),
            ], spacing=20, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Divider(),
            ft.Text("Explicación paso a paso", weight=ft.FontWeight.BOLD),
            self.lista_pasos,
            self.detalle_premisas,
        ], spacing=12), col={"xs": 12, "lg": 7})

        self.tabla = tabla(["Fecha", "Camión", "Semáforo", "Decisión", "Reglas", "Operador", ""])

        self.control = ft.Column([
            titulo_vista("Control de acceso", "El motor de reglas decide y cada decisión se guarda en la bitácora "
                                              "'accesos' con su explicación"),
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Datos de llegada", ft.Icons.LOCAL_SHIPPING), selector,
                                   modo_placa, modo_manual], spacing=14), col={"xs": 12, "lg": 5}),
                resultado,
            ], spacing=16, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            tarjeta(ft.Column([subtitulo("Bitácora de accesos (últimos 30)", ft.Icons.HISTORY),
                               ft.Row([self.tabla], scroll=ft.ScrollMode.AUTO)])),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    # ------------------------------------------------------------------
    async def refrescar(self):
        accesos = await self.app.bd(repositorios.listar_accesos, limite=30)
        if accesos is FALLO:
            return
        self.tabla.rows = [
            ft.DataRow(cells=[
                celda(fecha_txt(a.get("fecha")), 115),
                celda(a.get("camion_id") or a.get("placa") or "manual", 75, negrita=True),
                ft.DataCell(comun.chip(a.get("resultado", "-").upper(), COLOR_RESULTADO.get(a.get("resultado"), MORADO))),
                celda(a.get("decision"), 330),
                celda(", ".join(a.get("reglas_activadas", [])) or "-", 70),
                celda(a.get("operador"), 110),
                ft.DataCell(ft.Row([
                    boton_icono(ft.Icons.INFO_OUTLINE, "Ver explicación", lambda e, a=a: self._ver(a)),
                    boton_icono(ft.Icons.DELETE_OUTLINE, "Eliminar registro", lambda e, a=a: self._eliminar(a), ROJO),
                ], spacing=0)),
            ])
            for a in accesos
        ]
        self.app.page.update()

    def _cambiar_modo(self, e):
        manual = e.control.selected[0] == "manual"
        self.modo_placa.visible = not manual
        self.modo_manual.visible = manual
        self.app.page.update()

    # ------------------------------------------------------------------
    async def _evaluar_placa(self, e=None):
        page = self.app.page
        for campo in [self.f_identificador, self.f_peso, self.f_hora]:
            campo.error = None

        identificador = (self.f_identificador.value or "").strip().upper()
        if not identificador:
            self.f_identificador.error = "Escribe una placa o un ID"
            page.update()
            return
        try:
            peso = float((self.f_peso.value or "").replace(",", ""))
            if peso <= 0:
                raise ValueError
        except ValueError:
            self.f_peso.error = "Peso inválido: escribe un número mayor que 0"
            page.update()
            return
        if not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", (self.f_hora.value or "").strip()):
            self.f_hora.error = "Hora inválida. Usa HH:MM (24 h)"
            page.update()
            return

        camion = await self.app.bd(repositorios.buscar_camion, identificador)
        if camion is FALLO:
            return
        if camion is None:
            self.f_identificador.error = "No existe ese camión en el catálogo"
            page.update()
            return

        hora, minuto = (int(x) for x in self.f_hora.value.strip().split(":"))
        momento = datetime.now().replace(hour=hora, minute=minuto, second=0, microsecond=0)
        premisas, detalle = motor.premisas_desde_camion(camion, peso, self.f_peligrosa.value, momento,
                                                        self.app.ajustes)
        resultado = motor.evaluar(**premisas)
        documento = {
            "camion_id": camion["camion_id"], "placa": camion["placa"], "empresa": camion.get("empresa"),
            "peso_kg": peso, "carga_peligrosa": self.f_peligrosa.value, "detalle_premisas": detalle,
            "origen": "busqueda_placa", "fecha": momento,
        }
        await self._mostrar_y_guardar(resultado, documento, detalle)

    async def _evaluar_manual(self, e=None):
        premisas = {clave: interruptor.value for clave, interruptor in self.interruptores.items()}
        resultado = motor.evaluar(**premisas)
        identificador = (self.f_id_manual.value or "").strip().upper() or None
        documento = {"camion_id": identificador if identificador and identificador.startswith("CAM") else None,
                     "placa": identificador if identificador and not identificador.startswith("CAM") else None,
                     "origen": "formulario_manual", "fecha": datetime.now()}
        await self._mostrar_y_guardar(resultado, documento, None)

    async def _mostrar_y_guardar(self, resultado, documento, detalle):
        self.encender(resultado["resultado"])
        self.t_decision.value = resultado["decision"]
        self.t_decision.color = COLOR_RESULTADO[resultado["resultado"]]
        self.t_causa.value = "Causa: " + resultado["causa"]
        self.fila_reglas.controls = [chip_vf(clave, valor) for clave, valor in resultado["reglas"].items()]

        self.lista_pasos.controls = []
        for numero, paso in enumerate(resultado["explicacion"], start=1):
            es_aviso = paso.startswith("Aviso") or paso.startswith("Advertencia") or "retener" in paso
            self.lista_pasos.controls.append(ft.Row([
                ft.Container(ft.Text(str(numero), size=11, color=ft.Colors.WHITE), width=22, height=22,
                             border_radius=11, bgcolor=comun.NARANJA if es_aviso else MORADO,
                             alignment=ft.Alignment.CENTER),
                ft.Text(paso, size=13, expand=True, selectable=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START))

        self.detalle_premisas.controls = []
        if detalle:
            self.detalle_premisas.controls.append(ft.Text("De dónde salió cada premisa", weight=ft.FontWeight.BOLD))
            for clave in motor.ORDEN_PREMISAS:
                self.detalle_premisas.controls.append(ft.Text(
                    f"{clave} = {'V' if resultado['premisas'][clave] else 'F'}: {detalle[clave]}", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT))

        documento.update({
            "premisas": resultado["premisas"], "reglas": resultado["reglas"],
            "reglas_activadas": resultado["reglas_activadas"], "resultado": resultado["resultado"],
            "decision": resultado["decision"], "causa": resultado["causa"],
            "explicacion": resultado["explicacion"], "operador": self.app.ajustes.get("operador"),
        })
        guardado = await self.app.bd(repositorios.registrar_acceso, documento)
        self.estado_guardado.value = ("Registrado en la bitácora 'accesos'" if guardado is not FALLO
                                      else "No se guardó: sin conexión a MongoDB")
        self.app.page.update()
        await self.refrescar()

    def _ver(self, acceso):
        page = self.app.page
        pasos = [ft.Text(f"{n}. {p}", size=13, selectable=True) for n, p in enumerate(acceso.get("explicacion", []), 1)]
        page.show_dialog(ft.AlertDialog(
            title=ft.Text(f"{acceso.get('camion_id') or 'Registro manual'} · {fecha_txt(acceso.get('fecha'))}"),
            content=ft.Container(ft.Column([chip(acceso.get("resultado", "").upper(),
                                                 COLOR_RESULTADO.get(acceso.get("resultado"), MORADO)),
                                            ft.Text(acceso.get("decision", ""), weight=ft.FontWeight.BOLD), *pasos],
                                           tight=True, spacing=8, scroll=ft.ScrollMode.AUTO), width=620),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: page.pop_dialog())],
        ))
        page.update()

    def _eliminar(self, acceso):
        async def borrar():
            if await self.app.bd(repositorios.eliminar_acceso, acceso["_id"]) is not FALLO:
                self.app.aviso("Registro eliminado de la bitácora", "ok")
                await self.refrescar()

        confirmar(self.app.page, "Eliminar registro", "¿Eliminar este registro de la bitácora de accesos?", borrar)
