"""
Ventana principal de LogiSmart (Flet).

Estructura:
    - Barra de navegación lateral con las 9 pantallas.
    - Barra de estado con la conexión a MongoDB y a Ollama.
    - Área de contenido donde se muestra la pantalla seleccionada.
"""

import flet as ft

import config
from db import conexion
from db.conexion import ErrorBaseDatos
from gui import comun
from gui.comun import MORADO, ROSA, en_hilo
from llm import cliente as cliente_llm


class App:
    """Estado compartido de la aplicación y navegación entre pantallas."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.ajustes = config.cargar_config()
        self.oscuro = True
        self.vistas = {}
        self.vista_actual = None
        self.mongo_ok = False

    # ------------------------------------------------------------------
    # Acceso a datos con manejo de errores
    # ------------------------------------------------------------------
    async def bd(self, funcion, *args, **kwargs):
        """
        Ejecuta una operación de base de datos en segundo plano.
        Si MongoDB falla muestra el error y devuelve comun.FALLO.
        """
        try:
            resultado = await en_hilo(funcion, *args, **kwargs)
            if not self.mongo_ok:
                self.mongo_ok = True
                self.actualizar_insignia_mongo(True, "MongoDB conectado")
            return resultado
        except ErrorBaseDatos as error:
            conexion.reiniciar_conexion()
            self.mongo_ok = False
            self.actualizar_insignia_mongo(False, "Sin conexión a MongoDB")
            comun.aviso(self.page, str(error), "error")
            return comun.FALLO

    def aviso(self, texto, tipo="info"):
        comun.aviso(self.page, texto, tipo)

    def recargar_ajustes(self):
        self.ajustes = config.cargar_config()

    # ------------------------------------------------------------------
    # Insignias de conexión
    # ------------------------------------------------------------------
    def actualizar_insignia_mongo(self, ok, texto):
        self.punto_mongo.color = comun.VERDE if ok else comun.ROJO
        self.texto_mongo.value = texto
        self.page.update()

    def actualizar_insignia_ollama(self, ok, texto):
        self.punto_ollama.color = comun.VERDE if ok else comun.ROJO
        self.texto_ollama.value = texto
        self.page.update()

    async def verificar_conexiones(self, e=None):
        self.texto_mongo.value = "Verificando..."
        self.texto_ollama.value = "Verificando..."
        self.page.update()

        ok_mongo, mensaje_mongo = await en_hilo(conexion.verificar_conexion)
        self.mongo_ok = ok_mongo
        self.actualizar_insignia_mongo(ok_mongo, mensaje_mongo if ok_mongo else "Sin conexión a MongoDB")
        if not ok_mongo:
            self.aviso(mensaje_mongo, "error")

        ok_llm, mensaje_llm = await en_hilo(cliente_llm.verificar)
        modelo = self.ajustes.get("modelo_ollama")
        self.actualizar_insignia_ollama(ok_llm, f"{modelo} · Ollama" if ok_llm else "Ollama sin conexión")
        return ok_mongo

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------
    async def ir_a(self, indice):
        clave = DESTINOS[indice][0]
        if clave not in self.vistas:
            self.vistas[clave] = CONSTRUCTORES[clave](self)
        vista = self.vistas[clave]
        self.vista_actual = vista
        self.riel.selected_index = indice
        self.contenido.content = vista.control
        self.page.update()
        await vista.refrescar()

    async def al_navegar(self, e):
        await self.ir_a(e.control.selected_index)

    async def cambiar_tema(self, e):
        self.oscuro = e.control.value
        self.page.theme_mode = ft.ThemeMode.DARK if self.oscuro else ft.ThemeMode.LIGHT
        self.page.update()
        if self.vista_actual:
            await self.vista_actual.refrescar()  # las gráficas se redibujan con el tema nuevo

    # ------------------------------------------------------------------
    # Construcción de la ventana
    # ------------------------------------------------------------------
    def construir(self):
        page = self.page
        page.title = "LogiSmart · Centro de control inteligente"
        page.window.width = 1360
        page.window.height = 860
        page.window.min_width = 1100
        page.window.min_height = 680
        page.padding = 0
        page.spacing = 0
        # Fuente incluida en assets/fonts: tiene los símbolos lógicos (∧ ∨ ¬ → ⇒ ≥)
        page.fonts = {"DejaVu Sans": "/fonts/DejaVuSans.ttf", "DejaVu Sans Bold": "/fonts/DejaVuSans-Bold.ttf"}
        page.theme = ft.Theme(color_scheme_seed=MORADO, font_family="DejaVu Sans")
        page.dark_theme = ft.Theme(color_scheme_seed=MORADO, font_family="DejaVu Sans")
        page.theme_mode = ft.ThemeMode.DARK

        logo = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Icon(ft.Icons.LOCAL_SHIPPING, color=ft.Colors.WHITE, size=26),
                        padding=10, border_radius=14,
                        gradient=ft.LinearGradient(colors=[MORADO, ROSA],
                                                   begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT),
                    ),
                    ft.Text("LogiSmart", size=13, weight=ft.FontWeight.BOLD),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
            ),
            padding=ft.Padding.only(top=16, bottom=12),
        )

        self.riel = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=96,
            leading=logo,
            group_alignment=-0.85,
            destinations=[
                ft.NavigationRailDestination(icon=icono, selected_icon=icono_sel, label=etiqueta)
                for _, etiqueta, icono, icono_sel in DESTINOS
            ],
            trailing=ft.Container(
                content=ft.Column(
                    [ft.Switch(value=True, on_change=self.cambiar_tema, active_color=MORADO),
                     ft.Text("Oscuro", size=10)],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=0,
                ),
                padding=ft.Padding.only(top=12),
            ),
            on_change=self.al_navegar,
        )

        self.punto_mongo = ft.Icon(ft.Icons.CIRCLE, size=10, color=ft.Colors.AMBER)
        self.texto_mongo = ft.Text("Verificando...", size=12)
        self.punto_ollama = ft.Icon(ft.Icons.CIRCLE, size=10, color=ft.Colors.AMBER)
        self.texto_ollama = ft.Text("Verificando...", size=12)

        def insignia(icono, punto, texto):
            return ft.Container(
                content=ft.Row([ft.Icon(icono, size=16), punto, texto], spacing=6, tight=True),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                border_radius=20, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            )

        self.texto_operador = ft.Text(f"Operador: {self.ajustes.get('operador')}", size=12,
                                      color=ft.Colors.ON_SURFACE_VARIANT)

        barra_estado = ft.Container(
            content=ft.Row(
                [
                    self.texto_operador,
                    ft.Container(expand=True),
                    insignia(ft.Icons.STORAGE, self.punto_mongo, self.texto_mongo),
                    insignia(ft.Icons.SMART_TOY_OUTLINED, self.punto_ollama, self.texto_ollama),
                    ft.IconButton(ft.Icons.REFRESH, tooltip="Volver a probar conexiones",
                                  on_click=self.verificar_conexiones),
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=24, vertical=8),
            border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        )

        self.contenido = ft.Container(expand=True, padding=ft.Padding.only(left=28, right=28, top=20, bottom=12))

        page.add(
            ft.Row(
                [
                    self.riel,
                    ft.VerticalDivider(width=1),
                    ft.Column([barra_estado, self.contenido], expand=True, spacing=0),
                ],
                expand=True,
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        )


# Las importaciones de las vistas van aquí para evitar importaciones circulares
from gui.vistas.acceso import VistaAcceso  # noqa: E402
from gui.vistas.asistente import VistaAsistente  # noqa: E402
from gui.vistas.camiones import VistaCamiones  # noqa: E402
from gui.vistas.configuracion import VistaConfiguracion  # noqa: E402
from gui.vistas.incidentes import VistaIncidentes  # noqa: E402
from gui.vistas.panel import VistaPanel  # noqa: E402
from gui.vistas.reportes import VistaReportes  # noqa: E402
from gui.vistas.riesgos import VistaRiesgos  # noqa: E402
from gui.vistas.simulador import VistaSimulador  # noqa: E402

# (clave, etiqueta, icono, icono seleccionado)
DESTINOS = [
    ("panel", "Panel", ft.Icons.DASHBOARD_OUTLINED, ft.Icons.DASHBOARD),
    ("camiones", "Camiones", ft.Icons.LOCAL_SHIPPING_OUTLINED, ft.Icons.LOCAL_SHIPPING),
    ("acceso", "Acceso", ft.Icons.TRAFFIC_OUTLINED, ft.Icons.TRAFFIC),
    ("simulador", "Simulador", ft.Icons.TOGGLE_ON_OUTLINED, ft.Icons.TOGGLE_ON),
    ("incidentes", "Incidentes", ft.Icons.INBOX_OUTLINED, ft.Icons.INBOX),
    ("asistente", "Asistente", ft.Icons.CHAT_OUTLINED, ft.Icons.CHAT),
    ("riesgos", "Riesgos", ft.Icons.SHIELD_OUTLINED, ft.Icons.SHIELD),
    ("reportes", "Reportes", ft.Icons.DESCRIPTION_OUTLINED, ft.Icons.DESCRIPTION),
    ("configuracion", "Ajustes", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS),
]

CONSTRUCTORES = {
    "panel": VistaPanel,
    "camiones": VistaCamiones,
    "acceso": VistaAcceso,
    "simulador": VistaSimulador,
    "incidentes": VistaIncidentes,
    "asistente": VistaAsistente,
    "riesgos": VistaRiesgos,
    "reportes": VistaReportes,
    "configuracion": VistaConfiguracion,
}


async def main(page: ft.Page):
    app = App(page)
    app.construir()
    page.update()
    await app.verificar_conexiones()
    await app.ir_a(0)
