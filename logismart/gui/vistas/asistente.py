"""Asistente (chat LLM): responde solo con datos de MongoDB y muestra las fuentes consultadas."""

import time

import flet as ft

from asistente import rag
from gui import comun
from gui.comun import CIAN, MORADO, NARANJA, ROSA, chip, en_hilo, tarjeta, titulo_vista

SUGERENCIAS = [
    "¿Por qué CAM-102 fue enviado a inspección?",
    "¿Qué incidentes abiertos hay?",
    "¿Cuáles son los riesgos éticos más altos?",
    "¿Qué accesos fueron rechazados esta semana?",
    "¿Qué pasó con la placa ZZZ-000-Z?",
]

ICONO_COLECCION = {"camiones": ft.Icons.LOCAL_SHIPPING, "accesos": ft.Icons.TRAFFIC,
                   "incidentes": ft.Icons.INBOX, "riesgos_eticos": ft.Icons.SHIELD}


class VistaAsistente:
    def __init__(self, app):
        self.app = app
        self.historial = []  # mensajes previos para preguntas de seguimiento
        self.ocupado = False

        self.chat = ft.ListView(expand=True, spacing=14, auto_scroll=True, padding=ft.Padding.only(right=12))
        self.campo = ft.TextField(hint_text="Pregunta, por ejemplo: ¿por qué CAM-102 fue enviado a inspección?",
                                  expand=True, border_radius=28, filled=True, on_submit=self._enviar,
                                  content_padding=ft.Padding.symmetric(horizontal=20, vertical=14))
        self.boton = ft.IconButton(ft.Icons.SEND_ROUNDED, on_click=self._enviar, bgcolor=MORADO,
                                   icon_color=ft.Colors.WHITE, width=52, height=52, tooltip="Enviar")
        self.barra = ft.ProgressBar(color=CIAN, visible=False)

        sugerencias = ft.Row(
            [ft.OutlinedButton(s, on_click=self._al_sugerir(s)) for s in SUGERENCIAS],
            spacing=8, wrap=True,
        )

        self.control = ft.Column([
            titulo_vista("Asistente explicativo",
                         "RAG sencillo: primero consulta MongoDB, después le pasa esos registros al LLM y cita la fuente",
                         [ft.OutlinedButton("Limpiar chat", icon=ft.Icons.DELETE_SWEEP, on_click=self._limpiar)]),
            sugerencias,
            tarjeta(self.chat, padding=16, expand=True),
            self.barra,
            ft.Row([self.campo, self.boton], spacing=12),
        ], spacing=12, expand=True)

        self._bienvenida()

    def _bienvenida(self):
        self.chat.controls.append(self._burbuja_asistente(
            "Hola. Respondo **solo con información registrada en MongoDB** (camiones, accesos, incidentes y "
            "riesgos) y cito el registro de origen. Si no encuentro datos, te diré que no tengo información.",
            [], None))

    async def refrescar(self):
        self.app.page.update()

    def _limpiar(self, e):
        self.historial = []
        self.chat.controls = []
        self._bienvenida()
        self.app.page.update()

    def _al_sugerir(self, texto):
        # Flet necesita una función async para esperar la respuesta (una lambda no sirve)
        async def manejador(e):
            self.campo.value = texto
            await self._enviar()
        return manejador

    # ------------------------------------------------------------------
    def _burbuja_usuario(self, texto):
        return ft.Row([
            ft.Container(width=140),
            ft.Container(
                content=ft.Text(texto, color=ft.Colors.WHITE, selectable=True),
                padding=ft.Padding.symmetric(horizontal=16, vertical=10),
                border_radius=ft.BorderRadius(top_left=18, top_right=18, bottom_left=18, bottom_right=4),
                gradient=ft.LinearGradient(colors=[MORADO, ROSA], begin=ft.Alignment.TOP_LEFT,
                                           end=ft.Alignment.BOTTOM_RIGHT),
                expand_loose=True,
            ),
        ], alignment=ft.MainAxisAlignment.END)

    def _burbuja_asistente(self, texto, fuentes, latencia_ms, sin_datos=False):
        contenido = [ft.Markdown(texto, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)]
        if fuentes:
            contenido.append(ft.Text("Fuentes consultadas en MongoDB:", size=11, weight=ft.FontWeight.BOLD,
                                     color=ft.Colors.ON_SURFACE_VARIANT))
            contenido.append(ft.Row(
                [chip(f["ref"], CIAN, ICONO_COLECCION.get(f["coleccion"])) for f in fuentes],
                spacing=6, wrap=True))
            citadas = [f["ref"] for f in fuentes if f["ref"] in texto]
            if not citadas:
                contenido.append(ft.Text("Aviso: la respuesta no citó explícitamente las fuentes.", size=11,
                                         color=NARANJA))
        if sin_datos:
            contenido.append(chip("Sin datos en MongoDB: no se consultó al LLM", NARANJA, ft.Icons.INFO_OUTLINE))
        if latencia_ms:
            contenido.append(ft.Text(f"{latencia_ms / 1000:.1f} s · {self.app.ajustes.get('modelo_ollama')}",
                                     size=10, color=ft.Colors.ON_SURFACE_VARIANT))

        return ft.Row([
            ft.Container(ft.Icon(ft.Icons.SMART_TOY, color=ft.Colors.WHITE, size=18), width=36, height=36,
                         border_radius=18, bgcolor=CIAN, alignment=ft.Alignment.CENTER),
            ft.Container(
                content=ft.Column(contenido, spacing=8),
                padding=ft.Padding.symmetric(horizontal=16, vertical=12),
                border_radius=ft.BorderRadius(top_left=18, top_right=18, bottom_left=4, bottom_right=18),
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                expand=True,
            ),
            ft.Container(width=80),
        ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=10)

    # ------------------------------------------------------------------
    async def _enviar(self, e=None):
        if self.ocupado:
            return
        pregunta = (self.campo.value or "").strip()
        if len(pregunta) < 3:
            self.campo.error = "Escribe una pregunta"
            self.app.page.update()
            return
        self.campo.error = None
        self.campo.value = ""
        self.chat.controls.append(self._burbuja_usuario(pregunta))
        pensando = ft.Row([comun.cargando("Consultando MongoDB y preparando la respuesta...")])
        self.chat.controls.append(pensando)
        self.ocupado = True
        self.campo.disabled = True
        self.boton.disabled = True
        self.barra.visible = True
        self.app.page.update()

        self.app.recargar_ajustes()
        inicio = time.perf_counter()
        respuesta = await en_hilo(rag.responder, pregunta, self.historial, self.app.ajustes)
        total_ms = (time.perf_counter() - inicio) * 1000

        self.chat.controls.remove(pensando)
        self.chat.controls.append(self._burbuja_asistente(
            respuesta["respuesta"], respuesta["fuentes"], total_ms if not respuesta["sin_datos"] else None,
            respuesta["sin_datos"]))
        if respuesta.get("error") and respuesta.get("detalle"):
            self.app.aviso("El LLM no respondió; se muestran los registros encontrados.", "aviso")

        self.historial.append({"role": "user", "content": pregunta})
        self.historial.append({"role": "assistant", "content": respuesta["respuesta"]})

        self.ocupado = False
        self.campo.disabled = False
        self.boton.disabled = False
        self.barra.visible = False
        self.app.page.update()
        await self.campo.focus()
