# Logistics Solver Grupo 2

Solver de optimización para planificación mensual de logística inversa textil, desarrollado en Python y PuLP para el Proyecto Logistics Grupo 2.

## Requisitos

- Python 3
- PuLP

Instalación:

```bash
pip install -r requirements.txt
```

## Estructura

```text
logistics-solver-grupo2/
├── solver.py
├── requirements.txt
├── README.md
├── test_cases/
└── outputs/
```

Cada instancia debe estar en una carpeta dentro de `test_cases/` y contener los 15 archivos CSV definidos por el curso.

## Ejecución

Ejemplo con el Caso 1:

```bash
python solver.py test_cases/case_1
```

Para mostrar el log interno de CBC:

```bash
python solver.py test_cases/case_1 --verbose
```

## Salida

El programa informa en terminal:

- estado del modelo;
- utilidad óptima;
- oferta y retiro total;
- Meta REP mínima;
- emisiones totales y presupuesto disponible;
- flujos positivos por arco, fracción y tipo de camión;
- descarte en Centros de Clasificación.

Además, guarda automáticamente un resumen en:

```text
outputs/case_1_solution.txt
```

Si la instancia es infactible, el programa lo informa y no presenta un plan de flujos como válido.

## Modelo implementado

El Solver implementa un modelo de Programación Lineal (LP) con, entre otras, las siguientes reglas:

- disponibilidad de material;
- retiro total obligatorio en puntos definidos;
- Meta REP mínima sobre la oferta total;
- conservación de flujo con rendimiento/merma y descarte;
- compatibilidad fracción-destino;
- capacidad máxima y cuotas contractuales de destinos;
- combinaciones de transporte permitidas;
- restricciones de acceso según tipo de camión;
- emisiones calculadas como flujo × factor de emisión × distancia;
- presupuesto global de CO2.

## Casos de prueba

Los cinco casos de prueba se utilizan para validar el comportamiento del Solver antes de aplicarlo a instancias reales.
