# LogiSmart · Centro de control inteligente

Aplicación de escritorio en Python que transforma el script monolítico `logiuncodigo.py` en una
arquitectura por capas con:

- **MongoDB** (local o Atlas) para camiones, accesos, incidentes, riesgos éticos y evaluaciones del LLM.
- **Motor de reglas** en lógica proposicional (A, E originales + B y V nuevas) con explicación paso a paso.
- **Clasificador híbrido** de incidentes: reglas + LLM local (Ollama) con JSON validado por pydantic,
  reintento y respaldo.
- **Asistente RAG** que responde solo con datos de MongoDB y cita el registro de origen.
- **Matriz de riesgos éticos** con riesgo residual y gráficas.
- **Interfaz gráfica** en Flet con 9 pantallas.

> Fundamentos de IA · Unidad 2. El script original se conserva en `legado/logiuncodigo.py`.

## Requisitos

- Python 3.10 o superior
- MongoDB (local en WSL/Compass) o la cadena de conexión de Atlas
- [Ollama](https://ollama.com) con un modelo descargado (`ollama pull llama3.2`)

## Instalación

```bash
git clone <URL-del-repositorio>
cd logismart
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
python3 -m pip install -r requirements.txt
cp .env.example .env              # ajusta MONGO_URI si usas Atlas
```

En WSL, para la ventana de escritorio se necesitan estas librerías del sistema:

```bash
sudo apt install -y libsecret-1-0 libgtk-3-0 libepoxy0 libxkbcommon0 libgles2 libegl1 libgl1-mesa-dri
```

## Uso

```bash
python3 -m db.datos_demo          # carga datos de demostración (una vez)
python3 main.py                   # abre la aplicación de escritorio
python3 main.py --web             # alternativa: http://localhost:8550 en el navegador
```

Experimento de clasificación (reglas vs LLM vs híbrido, 36 correos etiquetados):

```bash
python3 -m experimento.evaluar                 # completo, necesita Ollama
python3 -m experimento.evaluar --solo-reglas   # rápido, sin LLM
```

Pruebas unitarias (46 pruebas, usan MongoDB simulado y LLM simulado):

```bash
python3 -m unittest discover -s tests -t . -v
```

## Estructura

```
logismart/
├── main.py                   Punto de entrada (escritorio o web)
├── config.py                 Configuración (.env + config.json)
├── db/                       CAPA DE DATOS
│   ├── conexion.py           Conexión a MongoDB con manejo de errores
│   ├── repositorios.py       CRUD de las 5 colecciones + agregaciones
│   └── datos_demo.py         Datos de demostración (ficticios)
├── reglas/                   CAPA DE DOMINIO
│   ├── motor.py              Lógica proposicional, tablas de verdad, conflictos
│   └── peas.py               Diseño PEAS del agente
├── clasificador/
│   ├── reglas.py             Clasificador por palabras clave + regex (original)
│   ├── llm.py                Clasificador LLM con esquema pydantic
│   └── hibrido.py            Fusión reglas + LLM
├── llm/cliente.py            CAPA DE SERVICIOS: cliente de Ollama
├── asistente/rag.py          Asistente RAG (consulta primero, contexto después)
├── riesgos/matriz.py         Puntajes inherente/residual
├── reportes/                 Gráficas (matplotlib) y exportación PDF/CSV/JSON
├── gui/                      CAPA DE PRESENTACIÓN (Flet)
│   ├── app.py                Ventana, navegación y estado de conexiones
│   └── vistas/               Panel, Camiones, Acceso, Simulador, Incidentes,
│                             Asistente, Riesgos, Reportes, Configuración
├── experimento/              Correos etiquetados y script de evaluación
├── tests/                    Pruebas unitarias
├── docs/                     Informe técnico y resultados del experimento
└── legado/logiuncodigo.py    Script original (antes de la refactorización)
```

## Documentación

- [Informe técnico](docs/INFORME_TECNICO.md): arquitectura, esquema de colecciones, prompts,
  experimento y análisis ético.
- [Resultados del experimento](docs/resultados_experimento.md) (se regenera al ejecutar el experimento).

Todos los datos de demostración (empresas, conductores, placas) son ficticios.
