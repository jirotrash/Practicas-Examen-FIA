# ============================================================
# PRACTICA 2
# ASESOR DE VIDEOJUEGOS CON LLM - VERSION CON INTERFAZ FLET
# ============================================================
#
# Objetivo:
# Crear un asistente especializado utilizando un modelo de
# lenguaje LLM ejecutado mediante Ollama.
#
# Cambios respecto a la version de consola:
#
# 1. Nueva configuracion del sistema: asesor de videojuegos.
# 2. Interfaz grafica moderna con Flet (Material Design):
#    burbujas de chat, respuestas en tiempo real (streaming),
#    modo claro/oscuro e indicadores de carga.
# 3. Resumen del historial de la conversacion.
#
# Modelo:
# llama3.2
#
# Requisitos:
# pip install ollama "flet[all]>=1.0"
#
# Ejecucion:
# python3 p02primertutor_llm.py
#
# ============================================================


# ------------------------------------------------------------
# 1. IMPORTAR LAS BIBLIOTECAS
# ------------------------------------------------------------

import os
import time

import flet as ft
import ollama


# ------------------------------------------------------------
# 2. CONFIGURACION DEL MODELO
# ------------------------------------------------------------
#
# HOST_OLLAMA: direccion del servidor de Ollama.
#
# NUM_CTX: tamaño de la memoria de contexto del modelo.
# El valor por defecto de Ollama es pequeño y en
# conversaciones largas el modelo "olvidaria" el inicio.
#
# ------------------------------------------------------------

MODELO = "llama3.2"

HOST_OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

NUM_CTX = 8192

# Cliente asincrono: permite esperar la respuesta del LLM
# sin congelar la interfaz.
cliente = ollama.AsyncClient(host=HOST_OLLAMA)


# ------------------------------------------------------------
# 3. CONFIGURACION DE LA APLICACION
# ------------------------------------------------------------
#
# MODO_WEB = False -> la app se abre como ventana de escritorio.
# MODO_WEB = True  -> la app se abre en el navegador
#                     (plan B si la ventana no abre en WSL).
#
# ------------------------------------------------------------

MODO_WEB = False

PUERTO = 8550

# Colores tipo "neon" para el estilo gamer
COLOR_MORADO = "#7C4DFF"
COLOR_ROSA = "#FF4081"
COLOR_CIAN = "#00E5FF"
COLOR_VERDE = "#00E676"
COLOR_ROJO = "#FF5252"

# Fuente de Google Fonts (si no carga, Flet usa la de sistema)
FUENTES = {
    "Poppins": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf",
}


# ------------------------------------------------------------
# 4. CONFIGURACION DEL SISTEMA
# ------------------------------------------------------------
#
# El mensaje "system" establece el comportamiento general
# que queremos que tenga nuestro asistente.
#
# En esta version el asistente es un asesor experto
# en videojuegos.
#
# ------------------------------------------------------------

mensaje_sistema = """
Eres un asesor experto en videojuegos.

Tu función es ayudar a jugadores de todos los niveles.

Debes:

1. Recomendar juegos según los gustos, la plataforma y el
   presupuesto del jugador, explicando por qué le podrían gustar.
2. Explicar géneros, mecánicas y términos gamer de forma
   clara y con ejemplos sencillos.
3. Dar consejos y estrategias paso a paso cuando el jugador
   esté atorado en un juego.
4. No revelar spoilers de la historia, a menos que el jugador
   lo pida explícitamente.
5. Mencionar la clasificación por edades (ESRB o PEGI) cuando
   recomiendes un juego.
6. Si no conoces un juego o un dato, decirlo con honestidad
   en lugar de inventarlo.
7. Responder siempre en español y con un tono amigable.
"""


# ------------------------------------------------------------
# 5. CONFIGURACION DEL RESUMEN
# ------------------------------------------------------------
#
# Para el resumen se hace una consulta aparte al LLM con
# otro mensaje "system". Esta consulta NO se agrega al
# historial del asesor.
#
# ------------------------------------------------------------

mensaje_resumen = """
Eres un asistente que resume conversaciones.

Recibirás una conversación entre un jugador y su asesor
de videojuegos. Escribe un resumen breve en español con
este formato exacto en Markdown:

**Temas y juegos mencionados**
- ...

**Gustos del jugador**
- ... (escribe "No se mencionaron" si no hubo)

**Recomendaciones que se le dieron**
- ...

No inventes información que no aparezca en la conversación.
"""


# Preguntas sugeridas para el panel lateral
SUGERENCIAS = [
    ("Recomiéndame un juego de terror", ft.Icons.NIGHTLIGHT_ROUND),
    ("¿Qué es un roguelike?", ft.Icons.QUESTION_ANSWER),
    ("Tips para empezar en Minecraft", ft.Icons.LIGHTBULB_OUTLINE),
]


# ============================================================
# 6. APLICACION
# ============================================================
#
# En Flet toda la interfaz se construye dentro de la funcion
# main(page). Cada pestaña del navegador que abra la app
# tiene su propia conversacion.
#
# ============================================================

async def main(page: ft.Page):

    # --------------------------------------------------------
    # 6.1 CONFIGURACION DE LA PAGINA
    # --------------------------------------------------------

    page.title = "Asesor de Videojuegos con LLM"

    # Tamaño de la ventana (solo aplica en modo escritorio)
    page.window.width = 1280
    page.window.height = 820
    page.window.min_width = 980
    page.window.min_height = 640

    page.padding = 0
    page.spacing = 0
    page.fonts = FUENTES

    page.theme = ft.Theme(color_scheme_seed=COLOR_MORADO, font_family="Poppins")
    page.dark_theme = ft.Theme(color_scheme_seed=COLOR_MORADO, font_family="Poppins")
    page.theme_mode = ft.ThemeMode.DARK


    # --------------------------------------------------------
    # 6.2 CREAR HISTORIAL
    # --------------------------------------------------------
    #
    # El historial permite que el programa mantenga el
    # contexto de la conversacion.
    #
    # --------------------------------------------------------

    mensajes = [

        {
            "role": "system",
            "content": mensaje_sistema
        }

    ]

    # Tiempos de respuesta del LLM (en segundos)
    tiempos_respuesta = []

    # Indica si el programa esta esperando una respuesta
    estado = {"esperando": False}


    # --------------------------------------------------------
    # 6.3 FUNCIONES AUXILIARES
    # --------------------------------------------------------

    def contar_mensajes(rol):

        total = 0

        for mensaje in mensajes:
            if mensaje["role"] == rol:
                total = total + 1

        return total


    def tiempo_promedio():

        if len(tiempos_respuesta) == 0:
            return 0

        return sum(tiempos_respuesta) / len(tiempos_respuesta)


    def mostrar_aviso(texto, color):

        # Notificacion flotante en la parte inferior
        page.show_dialog(
            ft.SnackBar(
                content=ft.Text(texto, color=ft.Colors.WHITE),
                bgcolor=color,
                behavior=ft.SnackBarBehavior.FLOATING,
                show_close_icon=True,
                duration=ft.Duration(seconds=4),
            )
        )


    def cambiar_estado(texto, color):

        texto_estado.value = texto
        texto_estado.color = color


    async def copiar_texto(texto):

        await ft.Clipboard().set(texto)
        mostrar_aviso("Copiado al portapapeles", COLOR_MORADO)


    # --------------------------------------------------------
    # 6.4 BURBUJAS DEL CHAT
    # --------------------------------------------------------
    #
    # Mensajes del jugador: a la derecha, con degradado neon.
    # Mensajes del asesor: a la izquierda, en tarjeta oscura.
    #
    # El espacio vacio de 120 px evita que una burbuja ocupe
    # todo el ancho. La burbuja del jugador usa "expand_loose"
    # para ajustarse a su texto; la del asesor usa "expand"
    # porque sus respuestas suelen ser largas.
    #
    # --------------------------------------------------------

    def crear_avatar(icono, colores):

        return ft.Container(
            content=ft.Icon(icono, color=ft.Colors.WHITE, size=20),
            width=38,
            height=38,
            border_radius=19,
            alignment=ft.Alignment.CENTER,
            gradient=ft.LinearGradient(
                colors=colores,
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
            ),
        )


    def crear_markdown(texto):

        # El LLM responde con Markdown (negritas, listas, codigo);
        # este control lo muestra con formato.

        return ft.Markdown(
            value=texto,
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
        )


    def mensaje_jugador(texto):

        burbuja = ft.Container(
            content=ft.Text(texto, color=ft.Colors.WHITE, size=15, selectable=True),
            padding=ft.Padding.symmetric(horizontal=18, vertical=12),
            border_radius=ft.BorderRadius(top_left=20, top_right=20, bottom_left=20, bottom_right=4),
            gradient=ft.LinearGradient(
                colors=[COLOR_MORADO, COLOR_ROSA],
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
            ),
            shadow=ft.BoxShadow(blur_radius=18, color=ft.Colors.with_opacity(0.35, COLOR_ROSA)),
            expand_loose=True,
        )

        return ft.Row(
            [ft.Container(width=120), burbuja, crear_avatar(ft.Icons.PERSON_ROUNDED, [COLOR_ROSA, COLOR_MORADO])],
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.END,
            spacing=10,
        )


    def mensaje_asesor(texto=None):

        # Si no hay texto todavia, se muestra "Pensando..."
        if texto is None:
            contenido = ft.Row(
                [
                    ft.ProgressRing(width=16, height=16, stroke_width=2, color=COLOR_CIAN),
                    ft.Text("Pensando...", italic=True, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                tight=True,
                spacing=10,
            )
        else:
            contenido = crear_markdown(texto)

        burbuja = ft.Container(
            content=contenido,
            padding=ft.Padding.symmetric(horizontal=18, vertical=14),
            border_radius=ft.BorderRadius(top_left=20, top_right=20, bottom_left=4, bottom_right=20),
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.25, COLOR_CIAN)),
            expand=True,
        )

        fila = ft.Row(
            [crear_avatar(ft.Icons.SPORTS_ESPORTS, [COLOR_CIAN, COLOR_MORADO]), burbuja, ft.Container(width=120)],
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=10,
        )

        return fila, burbuja


    def mensaje_error(texto):

        burbuja = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.ERROR_OUTLINE, color=ft.Colors.ON_ERROR_CONTAINER, size=18),
                    ft.Text(texto, color=ft.Colors.ON_ERROR_CONTAINER),
                ],
                tight=True,
                spacing=8,
            ),
            padding=ft.Padding.symmetric(horizontal=16, vertical=10),
            border_radius=14,
            bgcolor=ft.Colors.ERROR_CONTAINER,
        )

        return ft.Row([burbuja], alignment=ft.MainAxisAlignment.CENTER)


    def mostrar_bienvenida():

        fila, _ = mensaje_asesor(
            "### ¡Hola, jugador!\n"
            "Soy tu **asesor de videojuegos**. Pídeme recomendaciones, "
            "explicaciones de géneros y mecánicas, o tips cuando te atores "
            "en algún juego.\n\n"
            "*Sin spoilers, lo prometo.*"
        )
        chat.controls.append(fila)


    # --------------------------------------------------------
    # 6.5 ESTADO DE LA INTERFAZ
    # --------------------------------------------------------

    def actualizar_estadisticas():

        valor_preguntas.value = str(contar_mensajes("user"))
        valor_respuestas.value = str(contar_mensajes("assistant"))

        if len(tiempos_respuesta) == 0:
            valor_tiempo.value = "—"
        else:
            valor_tiempo.value = f"{tiempos_respuesta[-1]:.1f}s"


    def bloquear_controles(bloquear):

        estado["esperando"] = bloquear

        campo_pregunta.disabled = bloquear
        boton_enviar.disabled = bloquear
        boton_resumen.disabled = bloquear
        boton_nueva.disabled = bloquear

        for tarjeta in tarjetas_sugerencia:
            tarjeta.disabled = bloquear

        barra_carga.visible = bloquear


    # --------------------------------------------------------
    # 6.6 ENVIAR PREGUNTA AL ASESOR
    # --------------------------------------------------------

    async def enviar_pregunta(e=None):

        if estado["esperando"]:
            return

        pregunta = (campo_pregunta.value or "").strip()

        if pregunta == "":
            campo_pregunta.error = "Escribe una pregunta antes de enviar"
            page.update()
            return

        campo_pregunta.error = None
        campo_pregunta.value = ""

        chat.controls.append(mensaje_jugador(pregunta))

        # Agregar pregunta al historial
        mensajes.append(
            {
                "role": "user",
                "content": pregunta
            }
        )

        actualizar_estadisticas()

        # Burbuja del asesor con indicador "Pensando..."
        fila_asesor, burbuja_asesor = mensaje_asesor()
        chat.controls.append(fila_asesor)

        bloquear_controles(True)
        cambiar_estado("El asesor está escribiendo...", COLOR_CIAN)
        page.update()

        # ----------------------------------------------------
        # ENVIAR INFORMACION AL LLM (streaming)
        # ----------------------------------------------------
        #
        # Con stream=True el LLM entrega la respuesta en
        # pedazos, y se van mostrando conforme llegan.
        #
        # ----------------------------------------------------

        inicio = time.perf_counter()
        contenido = ""
        texto_markdown = crear_markdown("")

        try:

            flujo = await cliente.chat(

                model=MODELO,

                messages=mensajes,

                stream=True,

                options={"num_ctx": NUM_CTX}

            )

            async for parte in flujo:

                contenido = contenido + parte["message"]["content"]

                burbuja_asesor.content = texto_markdown
                texto_markdown.value = contenido
                page.update()

        # ----------------------------------------------------
        # MANEJO DE ERRORES
        # ----------------------------------------------------

        except Exception as error:

            # Eliminamos la pregunta del historial porque
            # no pudo ser procesada.

            mensajes.pop()
            chat.controls.remove(fila_asesor)
            chat.controls.append(mensaje_error("No se pudo obtener respuesta. La pregunta no se guardó."))

            actualizar_estadisticas()
            bloquear_controles(False)
            cambiar_estado("Error de conexión con Ollama", COLOR_ROJO)
            mostrar_aviso(f"Error al conectarse con el LLM: {error}", COLOR_ROJO)
            page.update()

            return

        duracion = time.perf_counter() - inicio

        # Guardar respuesta en el historial
        mensajes.append(
            {
                "role": "assistant",
                "content": contenido
            }
        )

        tiempos_respuesta.append(duracion)

        actualizar_estadisticas()
        bloquear_controles(False)
        cambiar_estado(f"Respuesta recibida en {duracion:.1f} s", COLOR_VERDE)
        page.update()

        await campo_pregunta.focus()


    async def usar_sugerencia(texto):

        if estado["esperando"]:
            return

        campo_pregunta.value = texto
        await enviar_pregunta()


    # --------------------------------------------------------
    # 6.7 RESUMEN DEL HISTORIAL
    # --------------------------------------------------------

    def construir_transcripcion():

        # Convierte el historial en texto plano, sin el
        # mensaje "system".

        lineas = []

        for mensaje in mensajes:

            if mensaje["role"] == "user":
                lineas.append("Jugador: " + mensaje["content"])

            elif mensaje["role"] == "assistant":
                lineas.append("Asesor: " + mensaje["content"])

        return "\n\n".join(lineas)


    def tarjeta_dato(valor, titulo, color):

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(valor, size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    ft.Text(titulo, size=11, color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE)),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
                tight=True,
            ),
            padding=ft.Padding.symmetric(vertical=12),
            border_radius=14,
            gradient=ft.LinearGradient(
                colors=[color, ft.Colors.with_opacity(0.6, color)],
                begin=ft.Alignment.TOP_LEFT,
                end=ft.Alignment.BOTTOM_RIGHT,
            ),
            expand=True,
        )


    async def pedir_resumen(e=None):

        if estado["esperando"]:
            return

        if contar_mensajes("user") == 0:
            mostrar_aviso("Todavía no hay conversación para resumir.", COLOR_MORADO)
            page.update()
            return

        preguntas = contar_mensajes("user")
        promedio = tiempo_promedio()

        # --- Area donde aparecera el resumen ---

        area_resumen = ft.Container(
            content=ft.Row(
                [
                    ft.ProgressRing(width=20, height=20, stroke_width=2, color=COLOR_CIAN),
                    ft.Text("Generando resumen con " + MODELO + "...", italic=True),
                ],
                spacing=12,
            ),
            padding=16,
            border_radius=14,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        )

        texto_completo = {"valor": ""}

        async def copiar_resumen(e):
            await copiar_texto(texto_completo["valor"])

        async def guardar_resumen(e):

            ruta = await ft.FilePicker().save_file(
                dialog_title="Guardar resumen",
                file_name="resumen_videojuegos.txt",
                src_bytes=texto_completo["valor"].encode("utf-8"),
            )

            if ruta:
                mostrar_aviso("Resumen guardado", COLOR_VERDE)

        def cerrar_resumen(e):
            page.pop_dialog()

        boton_copiar = ft.TextButton("Copiar", icon=ft.Icons.CONTENT_COPY, on_click=copiar_resumen, disabled=True)
        boton_guardar = ft.TextButton("Guardar .txt", icon=ft.Icons.DOWNLOAD, on_click=guardar_resumen, disabled=True)

        dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.AUTO_AWESOME, color=COLOR_CIAN),
                    ft.Text("Resumen de tu sesión", weight=ft.FontWeight.BOLD),
                ],
                spacing=10,
            ),
            content=ft.Container(
                width=560,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                tarjeta_dato(str(preguntas), "Preguntas", COLOR_MORADO),
                                tarjeta_dato(str(contar_mensajes("assistant")), "Respuestas", COLOR_ROSA),
                                tarjeta_dato(f"{promedio:.1f}s", "Tiempo promedio", "#00B8D4"),
                            ],
                            spacing=10,
                        ),
                        area_resumen,
                    ],
                    tight=True,
                    spacing=16,
                ),
            ),
            scrollable=True,
            actions=[
                boton_copiar,
                boton_guardar,
                ft.FilledButton("Cerrar", on_click=cerrar_resumen),
            ],
        )

        page.show_dialog(dialogo)
        bloquear_controles(True)
        cambiar_estado("Generando resumen...", COLOR_CIAN)
        page.update()

        try:

            respuesta = await cliente.chat(

                model=MODELO,

                messages=[
                    {"role": "system", "content": mensaje_resumen},
                    {"role": "user", "content": construir_transcripcion()}
                ],

                options={"num_ctx": NUM_CTX}

            )

            resumen = respuesta["message"]["content"]

            texto_completo["valor"] = (
                "Resumen de la sesión - Asesor de videojuegos\n"
                + "Preguntas realizadas: " + str(preguntas) + "\n"
                + f"Tiempo promedio de respuesta: {promedio:.1f} s\n"
                + "-" * 40 + "\n\n"
                + resumen
            )

            area_resumen.content = crear_markdown(resumen)
            boton_copiar.disabled = False
            boton_guardar.disabled = False
            cambiar_estado("Resumen generado", COLOR_VERDE)

        except Exception as error:

            area_resumen.content = ft.Text("No se pudo generar el resumen: " + str(error), color=COLOR_ROJO)
            cambiar_estado("Error de conexión con Ollama", COLOR_ROJO)

        bloquear_controles(False)
        page.update()


    # --------------------------------------------------------
    # 6.8 NUEVA CONVERSACION
    # --------------------------------------------------------

    def reiniciar_conversacion():

        # Se deja solo el mensaje "system"
        del mensajes[1:]
        tiempos_respuesta.clear()

        chat.controls.clear()
        mostrar_bienvenida()
        actualizar_estadisticas()

        cambiar_estado("Nueva conversación iniciada", COLOR_CIAN)


    def nueva_conversacion(e=None):

        if estado["esperando"]:
            return

        if contar_mensajes("user") == 0:
            reiniciar_conversacion()
            page.update()
            return

        def confirmar(e):
            page.pop_dialog()
            reiniciar_conversacion()
            page.update()

        def cancelar(e):
            page.pop_dialog()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                icon=ft.Icon(ft.Icons.RESTART_ALT, color=COLOR_ROSA),
                title=ft.Text("¿Nueva conversación?"),
                content=ft.Text("Se borrará el historial actual."),
                actions=[
                    ft.TextButton("Cancelar", on_click=cancelar),
                    ft.FilledButton("Sí, borrar", on_click=confirmar, bgcolor=COLOR_ROJO, color=ft.Colors.WHITE),
                ],
            )
        )


    # --------------------------------------------------------
    # 6.9 TEMA CLARO / OSCURO
    # --------------------------------------------------------

    def cambiar_tema(e):

        if interruptor_tema.value:
            page.theme_mode = ft.ThemeMode.DARK
        else:
            page.theme_mode = ft.ThemeMode.LIGHT

        page.update()


    # --------------------------------------------------------
    # 6.10 VERIFICAR CONEXION CON OLLAMA
    # --------------------------------------------------------

    async def verificar_conexion():

        try:
            await cliente.list()
            punto_conexion.color = COLOR_VERDE
            texto_conexion.value = "Conectado"
            cambiar_estado("Listo. Escribe tu pregunta.", ft.Colors.ON_SURFACE_VARIANT)

        except Exception:
            punto_conexion.color = COLOR_ROJO
            texto_conexion.value = "Sin conexión"
            cambiar_estado("Ollama no responde en " + HOST_OLLAMA, COLOR_ROJO)

        page.update()


    # ========================================================
    # 7. CONSTRUCCION DE LA INTERFAZ
    # ========================================================

    # --------------------------------------------------------
    # 7.1 PANEL LATERAL
    # --------------------------------------------------------

    logo = ft.Row(
        [
            ft.Container(
                content=ft.Icon(ft.Icons.SPORTS_ESPORTS, color=ft.Colors.WHITE, size=28),
                padding=10,
                border_radius=14,
                gradient=ft.LinearGradient(
                    colors=[COLOR_MORADO, COLOR_ROSA],
                    begin=ft.Alignment.TOP_LEFT,
                    end=ft.Alignment.BOTTOM_RIGHT,
                ),
                shadow=ft.BoxShadow(blur_radius=20, color=ft.Colors.with_opacity(0.45, COLOR_MORADO)),
            ),
            ft.Column(
                [
                    ft.Text("GameBot", size=20, weight=ft.FontWeight.BOLD),
                    ft.Text("Asesor de videojuegos", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=0,
            ),
        ],
        spacing=12,
    )

    valor_preguntas = ft.Text("0", size=20, weight=ft.FontWeight.BOLD, color=COLOR_MORADO)
    valor_respuestas = ft.Text("0", size=20, weight=ft.FontWeight.BOLD, color=COLOR_ROSA)
    valor_tiempo = ft.Text("—", size=20, weight=ft.FontWeight.BOLD, color=COLOR_CIAN)

    def tarjeta_estadistica(valor, titulo):

        return ft.Container(
            content=ft.Column(
                [valor, ft.Text(titulo, size=11, color=ft.Colors.ON_SURFACE_VARIANT)],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=0,
            ),
            padding=ft.Padding.symmetric(vertical=10),
            border_radius=12,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            expand=True,
        )

    estadisticas = ft.Row(
        [
            tarjeta_estadistica(valor_preguntas, "Preguntas"),
            tarjeta_estadistica(valor_respuestas, "Respuestas"),
            tarjeta_estadistica(valor_tiempo, "Última"),
        ],
        spacing=8,
    )

    boton_resumen = ft.FilledButton(
        "Resumen del historial",
        icon=ft.Icons.SUMMARIZE_ROUNDED,
        on_click=pedir_resumen,
        height=46,
        bgcolor=COLOR_MORADO,
        color=ft.Colors.WHITE,
        expand=True,
    )

    boton_nueva = ft.OutlinedButton(
        "Nueva conversación",
        icon=ft.Icons.RESTART_ALT,
        on_click=nueva_conversacion,
        height=46,
        expand=True,
    )

    def tarjeta_sugerencia(texto, icono):

        async def al_hacer_clic(e):
            await usar_sugerencia(texto)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icono, size=18, color=COLOR_CIAN),
                    ft.Text(texto, size=13, expand=True),
                ],
                spacing=10,
            ),
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            border_radius=12,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            ink=True,
            on_click=al_hacer_clic,
        )

    tarjetas_sugerencia = []

    for texto, icono in SUGERENCIAS:
        tarjetas_sugerencia.append(tarjeta_sugerencia(texto, icono))

    interruptor_tema = ft.Switch(
        label="Modo oscuro",
        value=True,
        active_color=COLOR_MORADO,
        on_change=cambiar_tema,
    )

    def titulo_seccion(texto):
        return ft.Text(texto, size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT)

    panel_lateral = ft.Container(
        width=300,
        padding=24,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        content=ft.Column(
            [
                logo,
                ft.Container(height=12),
                titulo_seccion("TU SESIÓN"),
                estadisticas,
                ft.Row([boton_resumen]),
                ft.Row([boton_nueva]),
                ft.Container(height=8),
                titulo_seccion("PRUEBA PREGUNTANDO"),
                *tarjetas_sugerencia,
                ft.Container(expand=True),
                ft.Divider(color=ft.Colors.OUTLINE_VARIANT),
                interruptor_tema,
            ],
            spacing=12,
            expand=True,
        ),
    )


    # --------------------------------------------------------
    # 7.2 ENCABEZADO
    # --------------------------------------------------------

    punto_conexion = ft.Icon(ft.Icons.CIRCLE, size=10, color=ft.Colors.AMBER)
    texto_conexion = ft.Text("Verificando...", size=12, weight=ft.FontWeight.BOLD)

    insignia_conexion = ft.Container(
        content=ft.Row([punto_conexion, texto_conexion], spacing=6, tight=True),
        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
        border_radius=20,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
    )

    encabezado = ft.Container(
        padding=ft.Padding.symmetric(horizontal=28, vertical=18),
        border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.OUTLINE_VARIANT)),
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Text("Asesor de Videojuegos", size=22, weight=ft.FontWeight.BOLD),
                        ft.Text("Modelo " + MODELO + " ejecutado localmente con Ollama",
                                size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=2,
                ),
                insignia_conexion,
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
    )


    # --------------------------------------------------------
    # 7.3 AREA DEL CHAT
    # --------------------------------------------------------

    chat = ft.ListView(
        expand=True,
        spacing=16,
        padding=ft.Padding.symmetric(horizontal=28, vertical=20),
        auto_scroll=True,
    )


    # --------------------------------------------------------
    # 7.4 ENTRADA DE TEXTO
    # --------------------------------------------------------

    # Borde invisible normalmente y morado cuando se escribe
    borde_normal = ft.OutlineInputBorder(
        side=ft.BorderSide(1, ft.Colors.TRANSPARENT),
        border_radius=28,
    )
    borde_enfocado = ft.OutlineInputBorder(
        side=ft.BorderSide(2, COLOR_MORADO),
        border_radius=28,
    )

    campo_pregunta = ft.TextField(
        hint_text="Pregunta lo que quieras sobre videojuegos...",
        filled=True,
        border={
            ft.ControlState.DEFAULT: borde_normal,
            ft.ControlState.FOCUSED: borde_enfocado,
        },
        content_padding=ft.Padding.symmetric(horizontal=22, vertical=16),
        prefix_icon=ft.Icons.VIDEOGAME_ASSET,
        expand=True,
        autofocus=True,
        on_submit=enviar_pregunta,
    )

    boton_enviar = ft.IconButton(
        icon=ft.Icons.SEND_ROUNDED,
        icon_color=ft.Colors.WHITE,
        icon_size=22,
        bgcolor=COLOR_MORADO,
        width=54,
        height=54,
        tooltip="Enviar",
        on_click=enviar_pregunta,
    )

    barra_carga = ft.ProgressBar(color=COLOR_CIAN, bgcolor=ft.Colors.TRANSPARENT, visible=False)

    texto_estado = ft.Text("Verificando conexión...", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

    zona_entrada = ft.Container(
        padding=ft.Padding.only(left=28, right=28, bottom=14, top=6),
        content=ft.Column(
            [
                barra_carga,
                ft.Row([campo_pregunta, boton_enviar], spacing=12),
                texto_estado,
            ],
            spacing=8,
        ),
    )


    # --------------------------------------------------------
    # 7.5 ARMAR LA PAGINA
    # --------------------------------------------------------

    zona_principal = ft.Column(
        [encabezado, chat, zona_entrada],
        spacing=0,
        expand=True,
    )

    page.add(
        ft.Row(
            [panel_lateral, zona_principal],
            spacing=0,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
    )


    # ========================================================
    # 8. INICIO DEL PROGRAMA
    # ========================================================

    mostrar_bienvenida()
    page.update()

    await verificar_conexion()


if __name__ == "__main__":

    if MODO_WEB:
        print("=" * 50)
        print("  ASESOR DE VIDEOJUEGOS CON LLM")
        print("=" * 50)
        print("Abre en tu navegador: http://localhost:" + str(PUERTO))
        print("Presiona Ctrl+C para terminar.")
        # no_cdn=True: los archivos de Flet se sirven desde tu
        # computadora, asi funciona aunque no haya internet.
        ft.run(main, view=ft.AppView.WEB_BROWSER, port=PUERTO, no_cdn=True)
    else:
        ft.run(main)


# python -m py_compile p02primertutor_llm.py (comprueba que la sintaxis de python es correcta)

        #       SYSTEM
        #         │
        #         ▼
        #    Comportamiento
        #         │
        #         ▼
# USER ────────► LLM
        #         │
        #         ▼
        #      ASSISTANT
