# Resultados del experimento de clasificación

- Fecha: 2026-10-03T03:40:24
- Modelo LLM: `llama3.2`
- Correos etiquetados a mano: 36 (6 con ortografía informal)
- JSON válidos del LLM: 100.0 %
- Correos marcados para revisión humana (híbrido): 55.6 %

## Comparación

| Clasificador | Exactitud categoría | Exactitud prioridad | Exactitud formal | Exactitud informal | Latencia promedio | Latencia mediana |
|---|---|---|---|---|---|---|
| reglas | 61.1 % | 52.8 % | 70.0 % | 16.7 % | 0.04 ms | 0.04 ms |
| llm | 97.2 % | 83.3 % | 100.0 % | 83.3 % | 1956.42 ms | 1786.19 ms |
| hibrido | 94.4 % | 77.8 % | 96.7 % | 83.3 % | 1956.45 ms | 1786.23 ms |

## Exhaustividad (recall) por categoría

| Categoría | reglas | llm | hibrido |
|---|---|---|---|
| materiales_peligrosos | 50 % | 100 % | 100 % |
| sobrepeso | 60 % | 100 % | 100 % |
| acceso_no_autorizado | 40 % | 100 % | 80 % |
| falla_hardware | 60 % | 100 % | 100 % |
| falla_software | 100 % | 100 % | 100 % |
| somnolencia_conductor | 40 % | 80 % | 80 % |
| otro | 80 % | 100 % | 100 % |

## Matrices de confusión

![Matriz de confusión reglas](img/confusion_reglas.png)

![Matriz de confusión llm](img/confusion_llm.png)

![Matriz de confusión hibrido](img/confusion_hibrido.png)

## Detalle por correo

| # | Real | Informal | Reglas | LLM | Híbrido | Revisión |
|---|---|---|---|---|---|---|
| 1 | materiales_peligrosos |  | materiales_peligrosos | materiales_peligrosos | materiales_peligrosos |  |
| 2 | materiales_peligrosos |  | otro | materiales_peligrosos | materiales_peligrosos | sí |
| 3 | materiales_peligrosos |  | otro | materiales_peligrosos | materiales_peligrosos | sí |
| 4 | materiales_peligrosos | sí | otro | materiales_peligrosos | materiales_peligrosos | sí |
| 5 | materiales_peligrosos |  | materiales_peligrosos | materiales_peligrosos | materiales_peligrosos | sí |
| 6 | materiales_peligrosos |  | materiales_peligrosos | materiales_peligrosos | materiales_peligrosos | sí |
| 7 | sobrepeso |  | sobrepeso | sobrepeso | sobrepeso |  |
| 8 | sobrepeso |  | otro | sobrepeso | sobrepeso | sí |
| 9 | sobrepeso | sí | otro | sobrepeso | sobrepeso | sí |
| 10 | sobrepeso |  | sobrepeso | sobrepeso | sobrepeso |  |
| 11 | sobrepeso |  | sobrepeso | sobrepeso | sobrepeso |  |
| 12 | acceso_no_autorizado |  | acceso_no_autorizado | acceso_no_autorizado | acceso_no_autorizado |  |
| 13 | acceso_no_autorizado |  | otro | acceso_no_autorizado | acceso_no_autorizado | sí |
| 14 | acceso_no_autorizado |  | materiales_peligrosos | acceso_no_autorizado | materiales_peligrosos | sí |
| 15 | acceso_no_autorizado | sí | otro | acceso_no_autorizado | acceso_no_autorizado | sí |
| 16 | acceso_no_autorizado |  | acceso_no_autorizado | acceso_no_autorizado | acceso_no_autorizado |  |
| 17 | falla_hardware |  | falla_hardware | falla_hardware | falla_hardware | sí |
| 18 | falla_hardware |  | falla_hardware | falla_hardware | falla_hardware |  |
| 19 | falla_hardware | sí | otro | falla_hardware | falla_hardware | sí |
| 20 | falla_hardware |  | sobrepeso | falla_hardware | falla_hardware | sí |
| 21 | falla_hardware |  | falla_hardware | falla_hardware | falla_hardware |  |
| 22 | falla_software |  | falla_software | falla_software | falla_software | sí |
| 23 | falla_software |  | falla_software | falla_software | falla_software | sí |
| 24 | falla_software |  | falla_software | falla_software | falla_software | sí |
| 25 | falla_software | sí | falla_software | falla_software | falla_software |  |
| 26 | falla_software |  | falla_software | falla_software | falla_software |  |
| 27 | somnolencia_conductor |  | somnolencia_conductor | somnolencia_conductor | somnolencia_conductor |  |
| 28 | somnolencia_conductor |  | somnolencia_conductor | somnolencia_conductor | somnolencia_conductor |  |
| 29 | somnolencia_conductor | sí | otro | sobrepeso | sobrepeso | sí |
| 30 | somnolencia_conductor |  | falla_hardware | somnolencia_conductor | somnolencia_conductor | sí |
| 31 | somnolencia_conductor |  | otro | somnolencia_conductor | somnolencia_conductor | sí |
| 32 | otro |  | otro | otro | otro |  |
| 33 | otro |  | otro | otro | otro |  |
| 34 | otro |  | otro | otro | otro |  |
| 35 | otro |  | otro | otro | otro |  |
| 36 | otro |  | falla_software | otro | otro | sí |
