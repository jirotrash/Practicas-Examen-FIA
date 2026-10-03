# Practicas-Examen-FIA

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Flet](https://img.shields.io/badge/Flet-1.0-7C4DFF)
![Ollama](https://img.shields.io/badge/Ollama-llama3.2-000000)
![MongoDB](https://img.shields.io/badge/MongoDB-8.0-47A248?logo=mongodb&logoColor=white)
![Pruebas](https://img.shields.io/badge/pruebas-46%20OK-2ea44f)

Prácticas de **Fundamentos de Inteligencia Artificial · Unidad 2**. Son dos aplicaciones de escritorio hechas en
Python con [Flet](https://flet.dev) y un modelo de lenguaje que corre **localmente** con
[Ollama](https://ollama.com). No usan servicios en la nube ni llaves de API.

| Ejercicio | Carpeta | Qué es |
|---|---|---|
| 1 | [`tutor-llm/`](tutor-llm/) | **Asesor de videojuegos**: chat con un LLM, respuestas en tiempo real y resumen del historial |
| 2 | [`logismart/`](logismart/) | **LogiSmart**: centro de control inteligente para un patio logístico, todo en **un solo archivo** (`logismart.py`) |
| — | [`docs/`](docs/) | Informe técnico, manual de instalación y manual técnico (Word) |

## Contenido

- [Ejercicio 1 · Asesor de videojuegos](#ejercicio-1--asesor-de-videojuegos)
- [Ejercicio 2 · LogiSmart](#ejercicio-2--logismart)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Uso](#uso)
- [Cómo funciona LogiSmart](#cómo-funciona-logismart)
- [Resultados del experimento](#resultados-del-experimento)
- [Pruebas](#pruebas)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Solución de problemas](#solución-de-problemas)
- [Seguridad y ética](#seguridad-y-ética)

---

## Ejercicio 1 · Asesor de videojuegos

Evolución de la práctica `p02primertutor_llm.py`. Los tres cambios pedidos:

1. **Nuevo rol del sistema:** el asistente pasó de tutor general a *GameBot*, un asesor de videojuegos con siete
   reglas: recomienda según gustos, plataforma y presupuesto, menciona la clasificación ESRB/PEGI, no cuenta
   spoilers si no se lo piden y admite cuando no conoce un juego en lugar de inventarlo.
2. **Interfaz gráfica de escritorio** con Flet: burbujas de chat, respuestas que aparecen palabra por palabra
   (streaming), preguntas sugeridas, contador de mensajes y modo claro / oscuro.
3. **Resumen del historial:** un botón pide al modelo un resumen de la conversación, que se puede copiar o
   guardar como `.txt`.

![Asesor de videojuegos](docs/img/tutor.png)

---

## Ejercicio 2 · LogiSmart

LogiSmart transforma el script de consola `logiuncodigo.py` (que se conserva sin cambios en la misma carpeta)
en una aplicación completa:

- **MongoDB** guarda camiones, accesos, incidentes, riesgos éticos y cada llamada al LLM.
- **Motor de reglas lógicas** que conserva las reglas originales A y E, agrega dos nuevas (B y V) y explica cada
  decisión paso a paso.
- **Clasificador híbrido** de correos de incidentes: reglas + LLM con salida JSON validada con pydantic,
  reintento, respaldo y revisión humana cuando no coinciden.
- **Asistente explicativo (RAG)** que responde solo con datos de MongoDB y cita el registro de origen.
- **Matriz de riesgos éticos** con riesgo inherente y residual, gráficas e histórico de cambios.
- **9 pantallas**, filtros por fecha y exportación a **PDF, CSV y JSON**.
- **Experimento** con 36 correos etiquetados a mano: reglas vs LLM vs híbrido.

| Panel de control | Control de acceso |
|---|---|
| ![Panel](docs/img/panel.png) | ![Acceso](docs/img/acceso.png) |
| **Bandeja de incidentes** | **Asistente explicativo** |
| ![Incidentes](docs/img/incidentes.png) | ![Asistente](docs/img/asistente.png) |
| **Simulador de tablas de verdad** | **Matriz de riesgos éticos** |
| ![Simulador](docs/img/simulador.png) | ![Riesgos](docs/img/riesgos.png) |

---

## Requisitos

| Componente | Versión | Para qué |
|---|---|---|
| Python | 3.10 o superior (probado en 3.12) | Las dos aplicaciones |
| [Ollama](https://ollama.com/download) | Reciente, con `llama3.2` | El LLM local (las dos aplicaciones) |
| MongoDB | 8.0 local, o un clúster de Atlas | Solo LogiSmart |
| GPU (opcional) | 4 GB de VRAM o más | Respuestas en unos 2 s; sin GPU funciona, pero más lento |

Se desarrolló en **Windows 11 + WSL2 (Ubuntu 24.04)**: Ollama corre en Windows y el resto en Ubuntu. También
funciona en Windows sin WSL y en Linux.

## Instalación

### 1. Ollama y el modelo

Instala Ollama desde [ollama.com/download](https://ollama.com/download) y descarga el modelo:

```bash
ollama pull llama3.2
```

<details>
<summary><b>Si usas WSL y Ollama está en Windows</b> (Ubuntu no lo encuentra)</summary>

WSL tiene su propio `localhost`. En **PowerShell** abre `notepad $env:USERPROFILE\.wslconfig`, escribe:

```ini
[wsl2]
networkingMode=mirrored
```

Guarda y reinicia WSL **desde PowerShell** con `wsl --shutdown` (dentro de Ubuntu usa `wsl.exe --shutdown`).
Comprueba desde Ubuntu:

```bash
curl http://localhost:11434     # debe responder: Ollama is running
```
</details>

### 2. MongoDB (solo LogiSmart)

<details>
<summary><b>MongoDB local en Ubuntu</b></summary>

```bash
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
  sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] \
https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" | \
  sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update && sudo apt-get install -y mongodb-org
sudo systemctl enable --now mongod
```
</details>

Con **MongoDB Atlas** solo necesitas la cadena de conexión (paso 4).

### 3. Proyecto y dependencias

```bash
git clone https://github.com/jirotrash/Practicas-Examen-FIA.git
cd Practicas-Examen-FIA
python3 -m venv venv
source venv/bin/activate                        # Windows: venv\Scripts\activate
python3 -m pip install -r logismart/requirements.txt
```

`logismart/requirements.txt` incluye también lo que necesita el tutor (ollama y flet).

En **WSL**, instala además las librerías gráficas para que se abran las ventanas:

```bash
sudo apt install -y libsecret-1-0 libgtk-3-0 libepoxy0 libxkbcommon0 libgles2 libegl1 libgl1-mesa-dri
```

### 4. Configuración de LogiSmart

```bash
cd logismart
cp .env.example .env
```

| Variable | Por defecto | Descripción |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | Para Atlas: `mongodb+srv://USUARIO:CONTRASEÑA@CLUSTER.mongodb.net/` |
| `MONGO_DB` | `logismart` | Nombre de la base |
| `OLLAMA_HOST` | `http://localhost:11434` | Servidor de Ollama |

El modelo, la temperatura, los umbrales de las reglas y el correo de soporte se cambian desde la pantalla
**Ajustes** (se guardan en `config.json`).

## Uso

### Asesor de videojuegos

```bash
python3 tutor-llm/p02primertutor_llm.py
```

### LogiSmart

```bash
cd logismart
python3 logismart.py --demo        # carga los datos de demostración (solo la primera vez)
python3 logismart.py               # abre la aplicación
```

| Comando | Qué hace |
|---|---|
| `python3 logismart.py` | Abre la aplicación de escritorio |
| `python3 logismart.py --demo` | Carga los datos demo (solo si la base está vacía) |
| `python3 logismart.py --demo --reiniciar` | Borra todo y vuelve a cargar los datos demo |
| `python3 logismart.py --experimento` | Experimento reglas vs LLM vs híbrido (unos 2 min) |
| `python3 logismart.py --experimento --solo-reglas` | Experimento rápido, sin LLM |
| `python3 logismart.py --experimento --sin-mongo` | Experimento sin guardar en MongoDB |
| `python3 logismart.py --tests` | 46 pruebas unitarias (no necesitan MongoDB ni Ollama) |
| `python3 logismart.py --tablas` | Imprime el PEAS, las tablas de verdad y el análisis de reglas |
| `python3 logismart.py --web` | Plan B: abre la interfaz en el navegador |

**Recorrido rápido para comprobar que todo funciona:**

1. **Acceso:** busca `CAM-102`, hora `10:30`, activa *materiales peligrosos* → semáforo **amarillo** (regla E).
2. Repite con hora `23:15` → semáforo **rojo** (regla nueva B).
3. **Incidentes:** *Cargar ejemplo* → *Clasificar* → resultado con la fuente "híbrido".
4. **Asistente:** "¿Por qué CAM-102 fue enviado a inspección?" → respuesta que cita `[accesos#...]`.
5. **Asistente:** la pregunta de la placa `ZZZ-000-Z` → "No tengo información" (no inventa).
6. **Reportes:** *Generar PDF* → archivo en `logismart/exportaciones/`.

---

## Cómo funciona LogiSmart

### Arquitectura

Todo el sistema está en `logismart/logismart.py`: unas 5 300 líneas divididas en **29 secciones numeradas**.
Cada sección usa solo funciones de secciones anteriores, así que el archivo se lee de arriba hacia abajo. Para
ir a una sección, busca `# SECCIÓN 5` (por ejemplo) en el editor.

![Arquitectura](docs/img/arquitectura.png)

| Capa | Secciones |
|---|---|
| **Datos** | §1 Configuración · §2 Conexión a MongoDB · §3 Repositorios (CRUD y agregaciones) · §14 Correos etiquetados · §15 Datos demo |
| **Dominio** | §4 PEAS · §5 Motor de reglas · §6 Clasificador por reglas · §8 Clasificador con LLM · §11 Matriz de riesgos |
| **Servicios** | §7 Cliente de Ollama · §9 Clasificador híbrido · §10 Asistente RAG · §12 Gráficas · §13 Exportación · §16 Experimento |
| **Presentación** | §17 Componentes comunes · §18 a §26 las 9 pantallas · §27 Ventana principal |
| **Pruebas y entrada** | §28 Pruebas unitarias · §29 Opciones de línea de comandos |

El LLM **nunca decide el acceso**: el semáforo depende solo de reglas lógicas auditables. El LLM clasifica
texto y redacta explicaciones a partir de datos guardados.

### Motor de reglas

Premisas que se calculan con los datos del camión y de la llegada:

| Premisa | Significado | De dónde sale |
|---|---|---|
| P | Autorización previa | Catálogo de camiones |
| Q | El peso excede el límite | Báscula vs límite (40 000 kg, configurable) |
| R | Materiales peligrosos | Declaración del operador |
| S | Certificación del conductor vigente | Fecha de vencimiento |
| H | Horario restringido *(nueva)* | Hora de llegada, de 22:00 a 06:00 |
| T | Certificación por vencer *(nueva)* | Vence en 30 días o menos |

| Regla | Fórmula | Efecto | Prioridad |
|---|---|---|---|
| — | ¬P | 🔴 Acceso denegado: sin autorización | 1 |
| **B** *(nueva)* | R ∧ H | 🔴 Carga peligrosa en horario restringido: reprogramar | 2 |
| **E** (original) | P ∧ (R ∨ Q) | 🟡 Inspección especial | 3 |
| **A** (original) | P ∧ S ∧ ¬Q | 🟢 Acceso estándar | 4 |
| — | P ∧ ¬S | 🔴 Acceso denegado: certificación vencida | 5 |
| **V** *(nueva)* | S ∧ T | Aviso de renovación (no cambia el semáforo) | — |

Cuando varias reglas son verdaderas gana la de menor número de prioridad. Por ejemplo, si A y E se cumplen,
gana E: ante la duda, se inspecciona. Cada decisión se guarda en la colección `accesos` con sus premisas, las
reglas activadas y la explicación paso a paso.

### Clasificador híbrido de incidentes

1. El **clasificador por reglas** (palabras clave del script original) propone categoría y prioridad.
2. El **LLM** recibe el correo y debe responder un JSON con un esquema fijo. Pydantic lo valida y rechaza
   categorías inventadas o campos extra. Si el JSON es inválido, se reintenta; si Ollama no responde, se usan las
   reglas como respaldo.
3. **Fusión:** si coinciden, se acepta. Si no, gana la **prioridad más alta** y el caso se marca con
   `requiere_revision_humana`.

Categorías: materiales peligrosos, sobrepeso, acceso no autorizado, falla de hardware, falla de software,
somnolencia del conductor y otro.

### Asistente explicativo (RAG)

Primero busca en MongoDB los registros relacionados con la pregunta (por ID de camión, placa o tema) y
después le pasa **solo esos registros** al LLM, que debe citar la fuente con etiquetas como
`[accesos#b392a7]`. Si no encuentra datos, responde "No tengo información" **sin llamar al LLM**, para no
inventar.

### Colecciones de MongoDB

| Colección | Contenido | Datos demo |
|---|---|---|
| `camiones` | Catálogo, autorización y certificación del conductor (índices únicos en placa e ID) | 12 |
| `accesos` | Bitácora de decisiones del motor de reglas con su explicación | 104 |
| `incidentes` | Correos clasificados, estado e historial de cambios | 24 |
| `riesgos_eticos` | Matriz de riesgos con probabilidad, impacto, mitigación y riesgo residual | 8 |
| `evaluaciones_llm` | Prompt, respuesta, latencia y validación de cada llamada al LLM | Se llena al usar la app |

Todos los datos de demostración son **ficticios**. Se generan con una semilla fija, así que siempre son los
mismos.

### Matriz de riesgos éticos

Puntaje = probabilidad × impacto (1 a 25). Niveles: bajo (1-4), medio (5-9), alto (10-16) y crítico (17-25).
Cada riesgo tiene un puntaje **inherente** y uno **residual** (después de la mitigación), y cada cambio se
guarda en su histórico.

---

## Resultados del experimento

36 correos etiquetados a mano, 6 de ellos con ortografía informal (por ejemplo, *"ai un derame en el anden
1!!"*). Ejecución con llama3.2, temperatura 0.1, en una laptop con RTX 3050 de 4 GB:

| Clasificador | Categoría | Prioridad | Correos formales (30) | Correos informales (6) | Latencia promedio |
|---|---|---|---|---|---|
| Reglas | 61.1 % | 52.8 % | 70.0 % | 16.7 % | 0.02 ms |
| LLM | **97.2 %** | **83.3 %** | 100.0 % | 83.3 % | 1 956 ms |
| Híbrido | 94.4 % | 77.8 % | 96.7 % | 83.3 % | 1 956 ms |

![Exactitud por clasificador](docs/img/exactitud.png)

- El LLM supera a las reglas por **36 puntos**, y por **67 puntos** en correos informales.
- El híbrido queda 2.8 puntos debajo del LLM solo, pero **sus dos errores quedaron marcados para revisión
  humana**: ninguno pasó sin que una persona lo viera.
- Las reglas solas acertaron 1 de 6 correos informales: un sesgo contra quien escribe con faltas que no se veía
  en la exactitud general.

Al ejecutar `--experimento`, los resultados se guardan en `logismart/resultados_experimento/` (JSON, Markdown
y matrices de confusión). El análisis completo está en el informe técnico.

## Pruebas

```bash
cd logismart
python3 logismart.py --tests
```

```
Ran 46 tests in 0.2s
OK
```

Usan MongoDB simulado (mongomock) y un LLM simulado (`unittest.mock`), así que no necesitan ningún servicio.
Incluyen las **18 pruebas del script original sin cambiar sus valores esperados**, además de pruebas de las
reglas nuevas, el reintento con JSON inválido, la fusión del híbrido, el CRUD y el asistente sin datos.

## Estructura del repositorio

```
Practicas-Examen-FIA/
├── README.md
├── .gitignore                    Excluye .env, config.json y archivos generados
├── tutor-llm/
│   ├── p02primertutor_llm.py     Ejercicio 1
│   └── requirements.txt
├── logismart/
│   ├── logismart.py              Ejercicio 2: toda la aplicación (29 secciones)
│   ├── logiuncodigo.py           Script original, sin cambios
│   ├── requirements.txt
│   ├── .env.example              Plantilla de conexión
│   └── resultados_experimento/   Se crea con --experimento
└── docs/
    ├── Informe_tecnico_LogiSmart.docx
    ├── Manual_de_instalacion.docx
    ├── Manual_tecnico.docx
    └── img/                      Capturas de este README
```

## Documentación

| Documento | Contenido |
|---|---|
| [Informe técnico](docs/Informe_tecnico_LogiSmart.docx) | Marco PEAS, arquitectura, esquema de colecciones, prompts, experimento y análisis ético |
| [Manual de instalación](docs/Manual_de_instalacion.docx) | Instalación paso a paso en WSL2 y Windows, verificación y solución de problemas |
| [Manual técnico](docs/Manual_tecnico.docx) | Secciones del código, funciones, cómo agregar reglas, categorías o pantallas |

## Solución de problemas

| Síntoma | Solución |
|---|---|
| `curl: (7) Failed to connect to localhost port 11434` en WSL | Configura `networkingMode=mirrored` ([paso 1](#1-ollama-y-el-modelo)) y reinicia WSL |
| `wsl --shutdown` responde "Unknown command" | Ejecútalo en PowerShell, o usa `wsl.exe --shutdown` desde Ubuntu |
| `ModuleNotFoundError: No module named 'flet'` | Activa el venv e instala con `python3 -m pip install -r logismart/requirements.txt` |
| `libsecret-1.so.0` o `libGLESv2.so.2` no encontrados | Instala las librerías gráficas del [paso 3](#3-proyecto-y-dependencias) |
| Avisos `libEGL warning` o `MESA` | Son inofensivos si la ventana abre. Si sale negra: `LIBGL_ALWAYS_SOFTWARE=1 python3 logismart.py` |
| Insignia "Sin conexión a MongoDB" | `sudo systemctl start mongod`, o revisa `MONGO_URI` en `.env` |
| `model 'llama3.2' not found` | `ollama pull llama3.2` |
| Respuestas de más de 30 s | `ollama ps` debe decir *100% GPU*; cierra otros modelos o baja el *Contexto* en Ajustes |
| La primera respuesta tarda 10-15 s | Normal: el modelo se carga en memoria. Las siguientes tardan unos 2 s |

## Seguridad y ética

- El archivo `.env` (que puede tener la contraseña de Atlas) **no se sube a Git**: está en `.gitignore`.
- El LLM corre en la computadora local y solo recibe los registros necesarios para cada pregunta.
- El envío de correos está en **modo simulación** por defecto.
- Las decisiones de acceso son reglas lógicas auditables; el LLM no puede abrir ni cerrar la barrera.
- Las discrepancias entre reglas y LLM pasan por **revisión humana**.
- Toda llamada al LLM queda registrada en `evaluaciones_llm` para auditoría.

---

Fundamentos de IA · Unidad 2 · Autor: **[@jirotrash](https://github.com/jirotrash)**
