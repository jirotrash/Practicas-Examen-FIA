"""Configuración: modelo de Ollama, umbrales, modo simulación de correo y datos de demostración."""

import re

import flet as ft

import config
from db import datos_demo
from gui.comun import FALLO, MORADO, ROJO, confirmar, en_hilo, subtitulo, tarjeta, titulo_vista
from llm import cliente as cliente_llm


def _ocultar_contrasena(uri):
    return re.sub(r"//([^:/]+):([^@]+)@", r"//\1:****@", uri)


class VistaConfiguracion:
    def __init__(self, app):
        self.app = app
        a = app.ajustes

        self.f_modelo = ft.Dropdown(label="Modelo de Ollama", value=a["modelo_ollama"], editable=True,
                                    options=[ft.DropdownOption(key=a["modelo_ollama"], text=a["modelo_ollama"])],
                                    width=320)
        self.f_temperatura = ft.Slider(min=0, max=1, divisions=10, value=a["temperatura"], label="{value}",
                                       active_color=MORADO)
        self.f_ctx = ft.Dropdown(label="Contexto (num_ctx)", value=str(a["num_ctx"]), width=200,
                                 options=[ft.DropdownOption(key=v, text=v) for v in ["2048", "4096", "8192"]])
        self.f_reintentos = ft.Dropdown(label="Reintentos si el JSON es inválido", value=str(a["reintentos_llm"]),
                                        width=260, options=[ft.DropdownOption(key=v, text=v) for v in ["0", "1", "2"]])

        self.f_peso = ft.TextField(label="Peso límite (kg) → premisa Q", value=str(a["peso_limite_kg"]), width=260)
        self.f_inicio = ft.TextField(label="Horario restringido: inicio (0-23)", value=str(a["hora_restringida_inicio"]),
                                     width=260)
        self.f_fin = ft.TextField(label="Horario restringido: fin (0-23)", value=str(a["hora_restringida_fin"]),
                                  width=260)
        self.f_dias = ft.TextField(label="Días de aviso de certificación → T", value=str(a["dias_aviso_certificacion"]),
                                   width=260)

        self.f_simulacion = ft.Switch(label="Modo simulación de correo (no envía correos reales)",
                                      value=a["modo_simulacion_correo"], active_color=MORADO)
        self.f_correo = ft.TextField(label="Correo del equipo de soporte", value=a["correo_soporte"], width=360)
        self.f_operador = ft.TextField(label="Operador (se guarda en cada decisión)", value=a["operador"], width=360)

        self.estado_demo = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        self.control = ft.Column([
            titulo_vista("Configuración", "Los ajustes se guardan en config.json; la conexión se define en .env",
                         [ft.FilledButton("Guardar cambios", icon=ft.Icons.SAVE, on_click=self._guardar,
                                          bgcolor=MORADO, color=ft.Colors.WHITE)]),
            ft.ResponsiveRow([
                tarjeta(ft.Column([
                    subtitulo("LLM local (Ollama)", ft.Icons.SMART_TOY),
                    ft.Row([self.f_modelo, ft.IconButton(ft.Icons.REFRESH, tooltip="Cargar modelos instalados",
                                                         on_click=self._cargar_modelos)]),
                    ft.Text("Temperatura (0 = más consistente)", size=12), self.f_temperatura,
                    ft.Row([self.f_ctx, self.f_reintentos], spacing=12, wrap=True),
                    ft.Text(f"Servidor: {config.OLLAMA_HOST}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=12), col={"xs": 12, "lg": 6}),
                tarjeta(ft.Column([
                    subtitulo("Umbrales del motor de reglas", ft.Icons.RULE),
                    self.f_peso, ft.Row([self.f_inicio, self.f_fin], spacing=12, wrap=True), self.f_dias,
                ], spacing=12), col={"xs": 12, "lg": 6}),
                tarjeta(ft.Column([
                    subtitulo("Correo y operador", ft.Icons.MAIL_OUTLINE),
                    self.f_simulacion, self.f_correo, self.f_operador,
                    ft.Text("Para envío real define SMTP_HOST, SMTP_PORT, SMTP_USER y SMTP_PASSWORD en el entorno.",
                            size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=12), col={"xs": 12, "lg": 6}),
                tarjeta(ft.Column([
                    subtitulo("Base de datos", ft.Icons.STORAGE),
                    ft.Text(f"MONGO_URI: {_ocultar_contrasena(config.MONGO_URI)}", size=12, selectable=True),
                    ft.Text(f"Base: {config.MONGO_DB}", size=12),
                    ft.Text("Para usar el clúster Atlas del profesor cambia MONGO_URI en el archivo .env y "
                            "reinicia la aplicación.", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row([
                        ft.OutlinedButton("Cargar datos demo", icon=ft.Icons.DATASET,
                                          on_click=lambda e: self._demo(False)),
                        ft.OutlinedButton("Reiniciar con datos demo", icon=ft.Icons.RESTART_ALT,
                                          on_click=lambda e: self._demo(True), style=ft.ButtonStyle(color=ROJO)),
                    ], spacing=10, wrap=True),
                    self.estado_demo,
                ], spacing=12), col={"xs": 12, "lg": 6}),
            ], spacing=16, run_spacing=16),
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

    async def refrescar(self):
        await self._cargar_modelos()

    async def _cargar_modelos(self, e=None):
        modelos = await en_hilo(cliente_llm.listar_modelos)
        actual = self.f_modelo.value
        nombres = sorted(set(modelos + ([actual] if actual else [])))
        self.f_modelo.options = [ft.DropdownOption(key=m, text=m) for m in nombres]
        if e is not None:
            self.app.aviso(f"{len(modelos)} modelo(s) instalados en Ollama" if modelos else
                           "No se pudo consultar Ollama", "info" if modelos else "aviso")
        self.app.page.update()

    async def _guardar(self, e):
        campos_enteros = [(self.f_peso, 1, 200000), (self.f_inicio, 0, 23), (self.f_fin, 0, 23), (self.f_dias, 0, 365)]
        hay_error = False
        for campo, minimo, maximo in campos_enteros:
            campo.error = None
            try:
                valor = int(float(campo.value))
                if not minimo <= valor <= maximo:
                    raise ValueError
            except (TypeError, ValueError):
                campo.error = f"Número entero entre {minimo} y {maximo}"
                hay_error = True
        if not (self.f_modelo.value or "").strip():
            self.f_modelo.error_text = "Elige un modelo"
            hay_error = True
        if hay_error:
            self.app.page.update()
            return

        ajustes = config.cargar_config()
        ajustes.update({
            "modelo_ollama": self.f_modelo.value.strip(),
            "temperatura": round(float(self.f_temperatura.value), 2),
            "num_ctx": int(self.f_ctx.value),
            "reintentos_llm": int(self.f_reintentos.value),
            "peso_limite_kg": int(float(self.f_peso.value)),
            "hora_restringida_inicio": int(self.f_inicio.value),
            "hora_restringida_fin": int(self.f_fin.value),
            "dias_aviso_certificacion": int(self.f_dias.value),
            "modo_simulacion_correo": self.f_simulacion.value,
            "correo_soporte": self.f_correo.value.strip(),
            "operador": self.f_operador.value.strip() or "operador",
        })
        await en_hilo(config.guardar_config, ajustes)
        self.app.recargar_ajustes()
        self.app.texto_operador.value = f"Operador: {ajustes['operador']}"
        await self.app.verificar_conexiones()
        self.app.aviso("Configuración guardada", "ok")

    def _demo(self, reiniciar):
        async def cargar():
            self.estado_demo.value = "Cargando datos de demostración..."
            self.app.page.update()
            resultado = await self.app.bd(datos_demo.cargar, reiniciar)
            if resultado is not FALLO:
                self.estado_demo.value = resultado
                self.app.aviso(resultado, "ok")
                if self.app.vista_actual is not self:
                    await self.app.vista_actual.refrescar()
            self.app.page.update()

        if reiniciar:
            confirmar(self.app.page, "Reiniciar base de datos",
                      "Se BORRARÁN todas las colecciones y se cargarán los datos de demostración. ¿Continuar?",
                      cargar, "Borrar y cargar")
        else:
            self.app.page.run_task(cargar)
