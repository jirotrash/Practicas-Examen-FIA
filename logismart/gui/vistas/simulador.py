"""Simulador de tablas de verdad: interruptores que cambian A, E, B y V en vivo."""

import flet as ft

from gui.comun import (AMARILLO, COLOR_RESULTADO, MORADO, NARANJA, ROJO, VERDE, chip, subtitulo, tarjeta,
                       titulo_vista)
from gui.vistas.acceso import crear_semaforo
from reglas import motor


def _vf(valor):
    return "V" if valor else "F"


class VistaSimulador:
    def __init__(self, app):
        self.app = app
        self.valores = {"P": True, "Q": False, "R": False, "S": True, "H": False, "T": False}

        interruptores = []
        for clave in motor.ORDEN_PREMISAS:
            nueva = clave in ("H", "T")
            interruptores.append(ft.Container(
                content=ft.Row([
                    ft.Text(clave, size=20, weight=ft.FontWeight.BOLD, width=28,
                            color=MORADO if not nueva else NARANJA),
                    ft.Column([ft.Text(motor.PREMISAS[clave], size=13),
                               ft.Text("premisa nueva" if nueva else "premisa original", size=10,
                                       color=ft.Colors.ON_SURFACE_VARIANT)], spacing=0, expand=True),
                    ft.Switch(value=self.valores[clave], active_color=MORADO,
                              on_change=lambda e, c=clave: self._cambio(c, e.control.value)),
                ], spacing=10),
                padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            ))

        self.semaforo, self.encender = crear_semaforo()
        self.t_decision = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
        self.t_avisos = ft.Column([], spacing=4)
        self.tarjetas_reglas = ft.ResponsiveRow([], spacing=10, run_spacing=10)

        self.tabla_ae = ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD)) for c in
                     ["P", "Q", "R", "S", "¬Q", "P∧S", "R∨Q", "A", "E"]],
            rows=[], column_spacing=14, heading_row_height=34, data_row_min_height=28, data_row_max_height=28,
        )
        self.tabla_b = self._tabla_pequena("B", ["R", "H"])
        self.tabla_v = self._tabla_pequena("V", ["S", "T"])

        analisis = motor.analizar_reglas()
        conflictos = [ft.Text(f"• {c['reglas']}: {c['descripcion']} en {c['casos']} de 64 combinaciones "
                              f"(ej. {c['ejemplo']}) → {c['resolucion']}", size=12) for c in analisis["conflictos"]]
        panel_analisis = tarjeta(ft.Column([
            subtitulo("Reto opcional: contradicciones y redundancias", ft.Icons.RULE),
            ft.Text("Conflictos entre reglas (se resuelven por prioridad):", weight=ft.FontWeight.BOLD, size=13),
            *conflictos,
            ft.Text("Implicaciones detectadas (X ⇒ Y):", weight=ft.FontWeight.BOLD, size=13),
            ft.Text(", ".join(analisis["implicaciones"]), size=12),
            ft.Text("Veces que cada regla decide el semáforo: " +
                    ", ".join(f"{k}={v}" for k, v in analisis["veces_que_decide"].items()), size=12),
            ft.Text(f"Combinaciones imposibles de premisas (T ∧ ¬S): {analisis['combinaciones_imposibles']} "
                    "de 64; el motor las marca con una advertencia.", size=12),
            ft.Text(analisis["nota_V"], size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ], spacing=8))

        self.control = ft.Column([
            titulo_vista("Simulador de tablas de verdad",
                         "Activa los interruptores y observa cómo cambian las reglas en vivo"),
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Premisas", ft.Icons.TOGGLE_ON), *interruptores], spacing=8),
                        col={"xs": 12, "lg": 5}),
                tarjeta(ft.Column([
                    subtitulo("Reglas y decisión", ft.Icons.FUNCTIONS),
                    self.tarjetas_reglas,
                    ft.Row([self.semaforo, ft.Column([self.t_decision, self.t_avisos], expand=True, spacing=6)],
                           spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
                ], spacing=14), col={"xs": 12, "lg": 7}),
            ], spacing=16, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.ResponsiveRow([
                tarjeta(ft.Column([subtitulo("Tabla de verdad original (16 filas): A = P ∧ S ∧ ¬Q,  E = P ∧ (R ∨ Q)",
                                             ft.Icons.TABLE_CHART),
                                   ft.Text("La fila resaltada es la combinación actual (H y T no afectan a A ni E).",
                                           size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                                   self.tabla_ae]), col={"xs": 12, "lg": 7}),
                tarjeta(ft.Column([subtitulo("Reglas nuevas", ft.Icons.NEW_RELEASES),
                                   ft.Text("B = R ∧ H  (bloqueo por horario restringido)", size=13),
                                   self.tabla_b,
                                   ft.Text("V = S ∧ T  (aviso de renovación de certificación)", size=13),
                                   self.tabla_v]), col={"xs": 12, "lg": 5}),
            ], spacing=16, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START),
            panel_analisis,
        ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True)

        self._actualizar(sin_dibujar=True)

    @staticmethod
    def _tabla_pequena(clave, variables):
        return ft.DataTable(
            columns=[ft.DataColumn(ft.Text(c, weight=ft.FontWeight.BOLD)) for c in variables + [clave]],
            rows=[], column_spacing=26, heading_row_height=32, data_row_min_height=28, data_row_max_height=28,
        )

    async def refrescar(self):
        self._actualizar()

    def _cambio(self, clave, valor):
        self.valores[clave] = valor
        self._actualizar()

    def _actualizar(self, sin_dibujar=False):
        v = self.valores
        resultado = motor.evaluar(**v)
        reglas = resultado["reglas"]

        tarjetas = []
        for clave, regla in motor.REGLAS.items():
            valor = reglas[clave]
            color = VERDE if valor else ft.Colors.ON_SURFACE_VARIANT
            tarjetas.append(ft.Container(
                content=ft.Column([
                    ft.Row([ft.Text(clave, size=22, weight=ft.FontWeight.BOLD),
                            ft.Text(_vf(valor), size=22, weight=ft.FontWeight.BOLD, color=color)],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(regla["formula"], size=12),
                    ft.Text(regla["nombre"], size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ], spacing=2),
                padding=12, border_radius=12, col={"xs": 6, "md": 3},
                bgcolor=ft.Colors.with_opacity(0.14, VERDE) if valor else ft.Colors.SURFACE_CONTAINER_HIGH,
                border=ft.Border.all(1, VERDE if valor else ft.Colors.OUTLINE_VARIANT),
            ))
        self.tarjetas_reglas.controls = tarjetas

        self.encender(resultado["resultado"])
        self.t_decision.value = resultado["decision"]
        self.t_decision.color = COLOR_RESULTADO[resultado["resultado"]]
        self.t_avisos.controls = [ft.Text("Causa: " + resultado["causa"], size=12,
                                          color=ft.Colors.ON_SURFACE_VARIANT)]
        for aviso in resultado["avisos"] + resultado["advertencias"]:
            color = ROJO if aviso.startswith("Advertencia") else AMARILLO
            self.t_avisos.controls.append(chip(aviso, color, ft.Icons.WARNING_AMBER))

        resaltado = ft.Colors.with_opacity(0.25, MORADO)
        filas = []
        for fila in motor.tabla_original():
            actual = all(fila[k] == v[k] for k in ("P", "Q", "R", "S"))
            filas.append(ft.DataRow(
                color=resaltado if actual else None,
                cells=[ft.DataCell(ft.Text(_vf(fila[k]), size=12,
                                           weight=ft.FontWeight.BOLD if k in ("A", "E") else None,
                                           color=(VERDE if fila[k] else None) if k in ("A", "E") else None))
                       for k in ["P", "Q", "R", "S", "no_Q", "P_y_S", "R_o_Q", "A", "E"]],
            ))
        self.tabla_ae.rows = filas

        for tabla_control, clave in [(self.tabla_b, "B"), (self.tabla_v, "V")]:
            variables = motor.REGLAS[clave]["variables"]
            tabla_control.rows = [
                ft.DataRow(
                    color=resaltado if all(f[x] == v[x] for x in variables) else None,
                    cells=[ft.DataCell(ft.Text(_vf(f[x]), size=12)) for x in variables] +
                          [ft.DataCell(ft.Text(_vf(f[clave]), size=12, weight=ft.FontWeight.BOLD,
                                               color=VERDE if f[clave] else None))],
                )
                for f in motor.tabla_verdad(clave)
            ]

        if not sin_dibujar:
            self.app.page.update()
