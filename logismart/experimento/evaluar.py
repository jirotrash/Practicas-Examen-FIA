"""
EXPERIMENTO: comparación de clasificadores (reglas vs LLM vs híbrido).

Uso (desde la carpeta del proyecto):
    python -m experimento.evaluar                 -> experimento completo (necesita Ollama)
    python -m experimento.evaluar --solo-reglas   -> rápido, sin LLM
    python -m experimento.evaluar --sin-mongo     -> no guarda en evaluaciones_llm

Métricas por clasificador:
    - exactitud de categoría y de prioridad
    - matriz de confusión de categorías
    - latencia promedio y mediana (ms)
    - exactitud en correos con ortografía informal (evidencia de sesgo)
    - % de JSON válidos del LLM y % marcados para revisión humana

Resultados:
    experimento/resultados.json
    docs/resultados_experimento.md
    docs/img/confusion_*.png
"""

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import config  # noqa: E402
from clasificador import reglas  # noqa: E402
from clasificador.hibrido import fusionar  # noqa: E402
from clasificador.llm import clasificar_con_llm  # noqa: E402
from clasificador.reglas import CATEGORIAS_VALIDAS  # noqa: E402
from reportes import graficas  # noqa: E402

DATASET = RAIZ / "experimento" / "correos_etiquetados.json"
SALIDA_JSON = RAIZ / "experimento" / "resultados.json"
SALIDA_MD = RAIZ / "docs" / "resultados_experimento.md"
CARPETA_IMG = RAIZ / "docs" / "img"


def matriz_confusion(reales, predichas, etiquetas):
    indice = {e: i for i, e in enumerate(etiquetas)}
    matriz = [[0] * len(etiquetas) for _ in etiquetas]
    for real, pred in zip(reales, predichas):
        matriz[indice[real]][indice[pred]] += 1
    return matriz


def exactitud(reales, predichas):
    if not reales:
        return 0.0
    return sum(1 for r, p in zip(reales, predichas) if r == p) / len(reales)


def metricas(nombre, correos, predicciones, latencias):
    reales_cat = [c["categoria"] for c in correos]
    reales_pri = [c["prioridad"] for c in correos]
    pred_cat = [p["categoria"] for p in predicciones]
    pred_pri = [p["prioridad"] for p in predicciones]
    informales = [i for i, c in enumerate(correos) if c["informal"]]
    formales = [i for i, c in enumerate(correos) if not c["informal"]]

    por_clase = {}
    for etiqueta in CATEGORIAS_VALIDAS:
        indices = [i for i, r in enumerate(reales_cat) if r == etiqueta]
        if indices:
            por_clase[etiqueta] = round(exactitud([reales_cat[i] for i in indices],
                                                  [pred_cat[i] for i in indices]), 3)

    return {
        "clasificador": nombre,
        "exactitud_categoria": round(exactitud(reales_cat, pred_cat), 3),
        "exactitud_prioridad": round(exactitud(reales_pri, pred_pri), 3),
        "exactitud_informal": round(exactitud([reales_cat[i] for i in informales],
                                              [pred_cat[i] for i in informales]), 3),
        "exactitud_formal": round(exactitud([reales_cat[i] for i in formales],
                                            [pred_cat[i] for i in formales]), 3),
        "exhaustividad_por_clase": por_clase,
        "latencia_promedio_ms": round(statistics.mean(latencias), 2) if latencias else 0,
        "latencia_mediana_ms": round(statistics.median(latencias), 2) if latencias else 0,
        "matriz_confusion": matriz_confusion(reales_cat, pred_cat, CATEGORIAS_VALIDAS),
    }


def ejecutar(solo_reglas=False, guardar_mongo=True, limite=None):
    correos = json.loads(DATASET.read_text(encoding="utf-8"))
    if limite:
        correos = correos[:limite]

    ajustes = config.cargar_config()
    print(f"Correos etiquetados: {len(correos)} | modelo: {ajustes['modelo_ollama']}")

    registrar = None
    if guardar_mongo and not solo_reglas:
        try:
            from db import repositorios
            from db.conexion import obtener_db
            obtener_db()
            registrar = repositorios.registrar_evaluacion
        except Exception as error:  # noqa: BLE001
            print(f"[aviso] Sin MongoDB, no se guardará en evaluaciones_llm: {error}")

    pred_reglas, lat_reglas = [], []
    pred_llm, lat_llm = [], []
    pred_hibrido, lat_hibrido = [], []
    detalle = []
    json_validos = 0
    revisiones = 0

    for numero, correo in enumerate(correos, start=1):
        # --- Reglas ---------------------------------------------------------
        inicio = time.perf_counter()
        r = reglas.clasificar(correo["asunto"], correo["cuerpo"])
        t_reglas = (time.perf_counter() - inicio) * 1000
        pred_reglas.append(r)
        lat_reglas.append(t_reglas)

        fila = {"id": correo["id"], "real": correo["categoria"], "informal": correo["informal"],
                "reglas": r["categoria"]}

        if not solo_reglas:
            # --- LLM --------------------------------------------------------
            res = clasificar_con_llm(correo["asunto"], correo["cuerpo"], ajustes)
            if res["ok"]:
                json_validos += 1
                l = res["clasificacion"]
            else:
                # El LLM "solo" no tiene respaldo: si falla cuenta como 'otro'
                l = {"categoria": "otro", "prioridad": "baja"}
            pred_llm.append(l)
            lat_llm.append(res["latencia_ms"])

            # --- Híbrido (fusión de los dos resultados anteriores) -----------
            if res["ok"]:
                categoria, prioridad, revision, _ = fusionar(r, l)
            else:
                categoria, prioridad, revision = r["categoria"], r["prioridad"], r["categoria"] == "otro"
            revisiones += int(revision)
            pred_hibrido.append({"categoria": categoria, "prioridad": prioridad})
            lat_hibrido.append(t_reglas + res["latencia_ms"])

            fila.update({"llm": l["categoria"], "hibrido": categoria, "revision_humana": revision,
                         "json_valido": res["ok"], "latencia_llm_ms": round(res["latencia_ms"], 1)})

            if registrar:
                try:
                    registrar({
                        "tipo": "experimento",
                        "prompt": res["prompt"],
                        "respuesta": res["respuesta"],
                        "modelo": res["modelo"],
                        "latencia_ms": round(res["latencia_ms"], 1),
                        "json_valido": res["ok"],
                        "intentos": res["intentos"],
                        "categoria_real": correo["categoria"],
                        "categoria_llm": l["categoria"],
                        "categoria_reglas": r["categoria"],
                        "coincidio_con_reglas": l["categoria"] == r["categoria"],
                        "acierto_llm": l["categoria"] == correo["categoria"],
                    })
                except Exception:  # noqa: BLE001
                    pass

            estado = "OK " if categoria == correo["categoria"] else "MAL"
            print(f"  [{numero:02d}/{len(correos)}] {estado} real={correo['categoria']:<22} "
                  f"reglas={r['categoria']:<22} llm={l['categoria']:<22} "
                  f"({res['latencia_ms'] / 1000:.1f} s)")
        detalle.append(fila)

    resultados = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "modelo": ajustes["modelo_ollama"],
        "total_correos": len(correos),
        "correos_informales": sum(1 for c in correos if c["informal"]),
        "clasificadores": [metricas("reglas", correos, pred_reglas, lat_reglas)],
        "detalle": detalle,
    }
    if not solo_reglas:
        resultados["clasificadores"].append(metricas("llm", correos, pred_llm, lat_llm))
        resultados["clasificadores"].append(metricas("hibrido", correos, pred_hibrido, lat_hibrido))
        resultados["json_validos_pct"] = round(100 * json_validos / len(correos), 1)
        resultados["revision_humana_pct"] = round(100 * revisiones / len(correos), 1)

    guardar(resultados)
    return resultados


def guardar(resultados):
    SALIDA_JSON.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    CARPETA_IMG.mkdir(parents=True, exist_ok=True)

    lineas = [
        "# Resultados del experimento de clasificación",
        "",
        f"- Fecha: {resultados['fecha']}",
        f"- Modelo LLM: `{resultados['modelo']}`",
        f"- Correos etiquetados a mano: {resultados['total_correos']} "
        f"({resultados['correos_informales']} con ortografía informal)",
    ]
    if "json_validos_pct" in resultados:
        lineas.append(f"- JSON válidos del LLM: {resultados['json_validos_pct']} %")
        lineas.append(f"- Correos marcados para revisión humana (híbrido): {resultados['revision_humana_pct']} %")

    lineas += ["", "## Comparación", "",
               "| Clasificador | Exactitud categoría | Exactitud prioridad | Exactitud formal | "
               "Exactitud informal | Latencia promedio | Latencia mediana |",
               "|---|---|---|---|---|---|---|"]
    for m in resultados["clasificadores"]:
        lineas.append(
            f"| {m['clasificador']} | {m['exactitud_categoria'] * 100:.1f} % | {m['exactitud_prioridad'] * 100:.1f} % | "
            f"{m['exactitud_formal'] * 100:.1f} % | {m['exactitud_informal'] * 100:.1f} % | "
            f"{m['latencia_promedio_ms']:.2f} ms | {m['latencia_mediana_ms']:.2f} ms |")

    lineas += ["", "## Exhaustividad (recall) por categoría", "",
               "| Categoría | " + " | ".join(m["clasificador"] for m in resultados["clasificadores"]) + " |",
               "|---|" + "---|" * len(resultados["clasificadores"])]
    for etiqueta in CATEGORIAS_VALIDAS:
        valores = [f"{m['exhaustividad_por_clase'].get(etiqueta, 0) * 100:.0f} %" for m in resultados["clasificadores"]]
        lineas.append(f"| {etiqueta} | " + " | ".join(valores) + " |")

    lineas += ["", "## Matrices de confusión", ""]
    for m in resultados["clasificadores"]:
        png = graficas.matriz_confusion(m["matriz_confusion"], CATEGORIAS_VALIDAS,
                                        f"Matriz de confusión · {m['clasificador']}", oscuro=False)
        nombre = f"confusion_{m['clasificador']}.png"
        (CARPETA_IMG / nombre).write_bytes(png)
        lineas.append(f"![Matriz de confusión {m['clasificador']}](img/{nombre})")
        lineas.append("")

    lineas += ["## Detalle por correo", "",
               "| # | Real | Informal | Reglas | LLM | Híbrido | Revisión |", "|---|---|---|---|---|---|---|"]
    for f in resultados["detalle"]:
        lineas.append(f"| {f['id']} | {f['real']} | {'sí' if f['informal'] else ''} | {f['reglas']} | "
                      f"{f.get('llm', '-')} | {f.get('hibrido', '-')} | "
                      f"{'sí' if f.get('revision_humana') else ''} |")

    SALIDA_MD.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    actualizar_informe(resultados)
    print(f"\nResultados guardados en:\n  {SALIDA_JSON}\n  {SALIDA_MD}\n  {CARPETA_IMG}")


def actualizar_informe(resultados):
    """Reemplaza la tabla de resultados dentro de docs/INFORME_TECNICO.md."""
    informe = RAIZ / "docs" / "INFORME_TECNICO.md"
    if not informe.exists():
        return
    texto = informe.read_text(encoding="utf-8")
    inicio = texto.find("<!-- RESULTADOS_INICIO")
    fin = texto.find("<!-- RESULTADOS_FIN -->")
    if inicio == -1 or fin == -1:
        return

    nombres = {"reglas": "Reglas", "llm": f"LLM ({resultados['modelo']})", "hibrido": "Híbrido"}
    informales = resultados["correos_informales"]
    formales = resultados["total_correos"] - informales
    tabla = ["<!-- RESULTADOS_INICIO (esta tabla la actualiza automáticamente experimento/evaluar.py) -->",
             f"| Clasificador | Exactitud categoría | Exactitud prioridad | Formal ({formales}) | "
             f"Informal ({informales}) | Latencia promedio |",
             "|---|---|---|---|---|---|"]
    for m in resultados["clasificadores"]:
        tabla.append(f"| {nombres[m['clasificador']]} | {m['exactitud_categoria'] * 100:.1f} % | "
                     f"{m['exactitud_prioridad'] * 100:.1f} % | {m['exactitud_formal'] * 100:.1f} % | "
                     f"{m['exactitud_informal'] * 100:.1f} % | {m['latencia_promedio_ms']:.2f} ms |")
    if len(resultados["clasificadores"]) == 1:
        tabla.append("| LLM | *pendiente: ejecutar `python3 -m experimento.evaluar` con Ollama encendido* | | | | |")
        tabla.append("| Híbrido | *pendiente* | | | | |")
    else:
        tabla.append("")
        tabla.append(f"JSON válidos del LLM: {resultados['json_validos_pct']} % · correos marcados para revisión "
                     f"humana (híbrido): {resultados['revision_humana_pct']} % · fecha: {resultados['fecha']}")
        tabla.append("")
        tabla.append("![Matriz de confusión del LLM](img/confusion_llm.png)")
        tabla.append("![Matriz de confusión del híbrido](img/confusion_hibrido.png)")
    texto = texto[:inicio] + "\n".join(tabla) + "\n" + texto[fin:]
    informe.write_text(texto, encoding="utf-8")


def imprimir_resumen(resultados):
    print("\n" + "=" * 78)
    print(f"{'Clasificador':<12}{'Categoría':>12}{'Prioridad':>12}{'Informal':>12}{'Latencia prom.':>18}")
    print("-" * 78)
    for m in resultados["clasificadores"]:
        print(f"{m['clasificador']:<12}{m['exactitud_categoria'] * 100:>11.1f}%{m['exactitud_prioridad'] * 100:>11.1f}%"
              f"{m['exactitud_informal'] * 100:>11.1f}%{m['latencia_promedio_ms']:>15.1f} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experimento de clasificación de incidentes")
    parser.add_argument("--solo-reglas", action="store_true", help="no usa el LLM")
    parser.add_argument("--sin-mongo", action="store_true", help="no guarda en evaluaciones_llm")
    parser.add_argument("--limite", type=int, default=None, help="usar solo los primeros N correos")
    args = parser.parse_args()
    imprimir_resumen(ejecutar(args.solo_reglas, not args.sin_mongo, args.limite))
