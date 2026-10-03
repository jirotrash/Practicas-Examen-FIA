"""
Componentes y utilidades compartidas por todas las pantallas.
"""

import asyncio
from datetime import datetime, timedelta

import flet as ft

# Colores de marca (mismo estilo que el tutor de la práctica 2)
MORADO = "#7C4DFF"
ROSA = "#FF4081"
CIAN = "#00B8D4"

# Colores de estado (semáforo y niveles de riesgo)
VERDE = "#0ca30c"
AMARILLO = "#fab219"
NARANJA = "#ec835a"
ROJO = "#d03b3b"

COLOR_RESULTADO = {"verde": VERDE, "amarillo": AMARILLO, "rojo": ROJO}
COLOR_PRIORIDAD = {"baja": VERDE, "media": AMARILLO, "alta": NARANJA, "critica": ROJO}
COLOR_ESTADO = {"nuevo": CIAN, "en_atencion": AMARILLO, "cerrado": VERDE}


# Valor que devuelve App.bd() cuando MongoDB falla (None puede ser un resultado válido)
FALLO = object()


async def en_hilo(funcion, *args, **kwargs):
    """Ejecuta una función lenta (MongoDB, LLM) sin congelar la interfaz."""
    return await asyncio.to_thread(funcion, *args, **kwargs)


def fecha_txt(valor, con_hora=True):
    if not isinstance(valor, datetime):
        return "-" if valor is None else str(valor)
    return valor.strftime("%d/%m/%Y %H:%M" if con_hora else "%d/%m/%Y")


def titulo_vista(titulo, subtitulo="", acciones=None):
    return ft.Row(
        [
            ft.Column(
                [
                    ft.Text(titulo, size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(subtitulo, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=2,
                expand=True,
            ),
            *(acciones or []),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def tarjeta(contenido, padding=20, expand=False, width=None, col=None):
    return ft.Container(
        content=contenido,
        padding=padding,
        border_radius=16,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        expand=expand,
        width=width,
        col=col if col is not None else 12,
    )


def subtitulo(texto, icono=None):
    controles = []
    if icono:
        controles.append(ft.Icon(icono, size=18, color=MORADO))
    controles.append(ft.Text(texto, size=15, weight=ft.FontWeight.BOLD))
    return ft.Row(controles, spacing=8)


def kpi(titulo, valor, icono, color, detalle=None):
    """Tarjeta de indicador. 'valor' y 'detalle' son controles ft.Text para poder actualizarlos."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Container(
                    content=ft.Icon(icono, color=ft.Colors.WHITE, size=24),
                    width=48, height=48, border_radius=14, bgcolor=color,
                    alignment=ft.Alignment.CENTER,
                ),
                ft.Column(
                    [ft.Text(titulo, size=12, color=ft.Colors.ON_SURFACE_VARIANT), valor] +
                    ([detalle] if detalle else []),
                    spacing=0,
                    expand=True,
                ),
            ],
            spacing=14,
        ),
        padding=16,
        border_radius=16,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        col={"xs": 12, "sm": 6, "lg": 3},
    )


def chip(texto, color, icono=None):
    """Etiqueta de color con texto (el color nunca va solo: siempre con texto)."""
    controles = []
    if icono:
        controles.append(ft.Icon(icono, size=14, color=color))
    controles.append(ft.Text(texto, size=12, weight=ft.FontWeight.BOLD, color=color))
    return ft.Container(
        content=ft.Row(controles, spacing=4, tight=True),
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=20,
        bgcolor=ft.Colors.with_opacity(0.14, color),
        border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color)),
    )


def chip_vf(nombre, valor):
    color = VERDE if valor else ft.Colors.ON_SURFACE_VARIANT
    return chip(f"{nombre} = {'V' if valor else 'F'}", color)


def imagen(png, alto=None):
    return ft.Image(src=png, fit=ft.BoxFit.CONTAIN, height=alto, border_radius=12)


def cargando(texto="Cargando..."):
    return ft.Row(
        [ft.ProgressRing(width=18, height=18, stroke_width=2, color=MORADO),
         ft.Text(texto, italic=True, color=ft.Colors.ON_SURFACE_VARIANT)],
        spacing=10,
    )


def aviso(page, texto, tipo="info"):
    colores = {"info": MORADO, "ok": VERDE, "error": ROJO, "aviso": NARANJA}
    page.show_dialog(ft.SnackBar(
        content=ft.Text(texto, color=ft.Colors.WHITE),
        bgcolor=colores.get(tipo, MORADO),
        behavior=ft.SnackBarBehavior.FLOATING,
        show_close_icon=True,
        duration=ft.Duration(seconds=5),
    ))
    page.update()


def confirmar(page, titulo, mensaje, al_confirmar, texto_boton="Eliminar"):
    """Diálogo de confirmación. al_confirmar puede ser async."""

    async def aceptar(e):
        page.pop_dialog()
        resultado = al_confirmar()
        if asyncio.iscoroutine(resultado):
            await resultado

    def cancelar(e):
        page.pop_dialog()

    page.show_dialog(ft.AlertDialog(
        modal=True,
        title=ft.Text(titulo),
        content=ft.Text(mensaje),
        actions=[
            ft.TextButton("Cancelar", on_click=cancelar),
            ft.FilledButton(texto_boton, on_click=aceptar, bgcolor=ROJO, color=ft.Colors.WHITE),
        ],
    ))


def tabla(columnas, filas_controles=None):
    return ft.DataTable(
        columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD, size=12)) for c in columnas],
        rows=filas_controles or [],
        column_spacing=18,
        heading_row_height=40,
        data_row_min_height=40,
        data_row_max_height=64,
        horizontal_lines=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT),
    )


def celda(texto, ancho=None, color=None, negrita=False):
    return ft.DataCell(ft.Container(
        ft.Text(str(texto) if texto is not None else "-", size=12, color=color,
                weight=ft.FontWeight.BOLD if negrita else None,
                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
        width=ancho,
    ))


def boton_icono(icono, ayuda, al_hacer_clic, color=None):
    return ft.IconButton(icon=icono, tooltip=ayuda, on_click=al_hacer_clic, icon_color=color, icon_size=20)


# -----------------------------------------------------------------------------
# Filtro de fechas reutilizable
# -----------------------------------------------------------------------------

class FiltroFechas:
    """
    Selector de periodo: Hoy, 7 días, 30 días, Todo o rango personalizado.
    al_cambiar() se llama (async) cuando cambia el periodo.
    """

    def __init__(self, page, al_cambiar, inicial="30"):
        self.page = page
        self.al_cambiar = al_cambiar
        self.opcion = inicial
        self.desde_personal = None
        self.hasta_personal = None
        self.texto_rango = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.segmentos = ft.SegmentedButton(
            segments=[
                ft.Segment(value="hoy", label=ft.Text("Hoy")),
                ft.Segment(value="7", label=ft.Text("7 días")),
                ft.Segment(value="30", label=ft.Text("30 días")),
                ft.Segment(value="todo", label=ft.Text("Todo")),
                ft.Segment(value="personal", label=ft.Text("Rango…")),
            ],
            selected=[inicial],
            show_selected_icon=False,
            on_change=self._cambio,
        )
        self.control = ft.Row([self.segmentos, self.texto_rango], spacing=12, wrap=True)
        self._actualizar_texto()

    def rango(self):
        ahora = datetime.now()
        inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        if self.opcion == "hoy":
            return inicio_hoy, None
        if self.opcion == "7":
            return inicio_hoy - timedelta(days=7), None
        if self.opcion == "30":
            return inicio_hoy - timedelta(days=30), None
        if self.opcion == "personal" and self.desde_personal:
            hasta = (self.hasta_personal or ahora).replace(hour=23, minute=59, second=59)
            return self.desde_personal, hasta
        return None, None

    def descripcion(self):
        desde, hasta = self.rango()
        if desde is None:
            return "Todo el historial"
        return f"{fecha_txt(desde, False)} a {fecha_txt(hasta or datetime.now(), False)}"

    def _actualizar_texto(self):
        self.texto_rango.value = self.descripcion()

    async def _cambio(self, e):
        self.opcion = e.control.selected[0] if e.control.selected else "todo"
        if self.opcion == "personal":
            self._pedir_fecha("desde")
            return
        self._actualizar_texto()
        await self.al_cambiar()

    def _pedir_fecha(self, cual):
        async def elegida(e):
            valor = e.control.value
            if isinstance(valor, datetime):
                valor = valor.replace(tzinfo=None)
            else:
                valor = datetime(valor.year, valor.month, valor.day)
            if cual == "desde":
                self.desde_personal = valor.replace(hour=0, minute=0, second=0)
                self._pedir_fecha("hasta")
            else:
                self.hasta_personal = valor
                if self.hasta_personal < self.desde_personal:
                    self.desde_personal, self.hasta_personal = self.hasta_personal, self.desde_personal
                self._actualizar_texto()
                await self.al_cambiar()

        self.page.show_dialog(ft.DatePicker(
            first_date=datetime(2024, 1, 1),
            last_date=datetime.now() + timedelta(days=1),
            help_text="Fecha inicial" if cual == "desde" else "Fecha final",
            on_change=elegida,
        ))
        self.page.update()
