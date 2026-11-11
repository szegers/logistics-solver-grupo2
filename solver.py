"""Solver de logística inversa textil - Grupo 2.

Primera etapa de implementación:
- Lee los 15 archivos CSV de una instancia.
- Valida archivos y columnas esenciales.
- Resume la instancia antes de construir el modelo PuLP.

El modelo de optimización se incorporará sobre esta base.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List


CSV_FILES = [
    "valor_destino.csv",
    "caminos.csv",
    "camiones.csv",
    "centros.csv",
    "compatibilidad.csv",
    "costos_fijos.csv",
    "costos_transporte.csv",
    "destinos.csv",
    "distancias.csv",
    "fracciones.csv",
    "fracciones_contrato.csv",
    "oferta.csv",
    "origenes.csv",
    "parametros.csv",
    "rendimiento.csv",
]


REQUIRED_COLUMNS = {
    "valor_destino.csv": {"FraccionID", "DestinoID", "Valor"},
    "caminos.csv": {
        "Origen",
        "Centro",
        "Destino",
        "CamionTramo1",
        "CamionTramo2",
    },
    "camiones.csv": {"CamionID", "FactorEmision", "Urbano"},
    "centros.csv": {"CentroID", "Certificado", "CostoManejo"},
    "compatibilidad.csv": {"FraccionID", "DestinoID", "Permitido"},
    "costos_transporte.csv": {
        "Desde",
        "Hasta",
        "CamionID",
        "CostoPorTonelada",
    },
    "destinos.csv": {
        "DestinoID",
        "CapacidadRecepcion",
        "CuotaMinima",
        "Contrato",
    },
    "distancias.csv": {"Desde", "Hasta", "Distancia"},
    "fracciones.csv": {"FraccionID", "BonoREP"},
    "fracciones_contrato.csv": {"DestinoID", "FraccionID"},
    "oferta.csv": {"OrigenID", "FraccionID", "Toneladas"},
    "origenes.csv": {
        "OrigenID",
        "RetiroObligatorio",
        "PreClasificado",
        "AccesoRestringido",
    },
    "parametros.csv": {"Parametro", "Valor"},
    "rendimiento.csv": {"FraccionID", "CentroID", "Rendimiento"},
}


def read_csv(path: Path) -> List[Dict[str, str]]:
    """Lee un archivo CSV separado por punto y coma."""
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file, delimiter=";")
        return list(reader)


def validate_files(folder: Path) -> None:
    """Verifica que existan los 15 archivos requeridos."""
    missing = [name for name in CSV_FILES if not (folder / name).is_file()]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"Faltan archivos requeridos en la instancia: {joined}"
        )


def validate_columns(
    file_name: str,
    rows: List[Dict[str, str]],
    folder: Path,
) -> None:
    """Verifica las columnas esenciales de un archivo."""
    required = REQUIRED_COLUMNS.get(file_name)
    if not required:
        return

    if not rows:
        raise ValueError(f"{file_name} está vacío.")

    actual = set(rows[0].keys())
    missing = required - actual

    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(
            f"{file_name} no contiene las columnas requeridas: {joined}. "
            f"Archivo: {folder / file_name}"
        )


def load_instance(folder: Path) -> Dict[str, List[Dict[str, str]]]:
    """Carga todos los CSV de una instancia y valida su estructura básica."""
    validate_files(folder)

    data: Dict[str, List[Dict[str, str]]] = {}

    for file_name in CSV_FILES:
        rows = read_csv(folder / file_name)
        validate_columns(file_name, rows, folder)
        data[file_name] = rows

    return data


def validate_parameters(data: Dict[str, List[Dict[str, str]]]) -> None:
    """Comprueba los parámetros globales imprescindibles."""
    parameters = {
        row["Parametro"]: row["Valor"]
        for row in data["parametros.csv"]
    }

    required = {"MetaREP", "PresupuestoCarbono"}
    missing = required - set(parameters)

    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(
            f"parametros.csv no contiene los parámetros requeridos: {joined}"
        )

    meta_rep = float(parameters["MetaREP"])
    carbon_budget = float(parameters["PresupuestoCarbono"])

    if not 0 <= meta_rep <= 1:
        raise ValueError("MetaREP debe estar entre 0 y 1.")

    if carbon_budget < 0:
        raise ValueError("PresupuestoCarbono no puede ser negativo.")


def print_summary(
    folder: Path,
    data: Dict[str, List[Dict[str, str]]],
) -> None:
    """Muestra un resumen simple de la instancia cargada."""
    origins = data["origenes.csv"]
    centers = data["centros.csv"]
    destinations = data["destinos.csv"]
    fractions = data["fracciones.csv"]
    trucks = data["camiones.csv"]
    offers = data["oferta.csv"]

    total_offer = sum(float(row["Toneladas"]) for row in offers)

    mandatory_origins = sum(
        row["RetiroObligatorio"] == "1" for row in origins
    )
    certified_centers = sum(
        row["Certificado"] == "1" for row in centers
    )
    contracted_destinations = sum(
        row["Contrato"] == "1" for row in destinations
    )

    print("\nInstancia cargada correctamente")
    print(f"Carpeta: {folder}")
    print(f"Puntos de recolección: {len(origins)}")
    print(f"Centros de clasificación: {len(centers)}")
    print(f"Destinos de valorización: {len(destinations)}")
    print(f"Fracciones: {len(fractions)}")
    print(f"Tipos de camión: {len(trucks)}")
    print(f"Oferta total: {total_offer:.3f} t")
    print(f"Puntos con retiro obligatorio: {mandatory_origins}")
    print(f"Centros certificados: {certified_centers}")
    print(f"Destinos con contrato: {contracted_destinations}")


def parse_args() -> argparse.Namespace:
    """Lee los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description=(
            "Solver de optimización para logística inversa textil."
        )
    )
    parser.add_argument(
        "instance",
        type=Path,
        help="Carpeta que contiene los 15 CSV de la instancia.",
    )
    return parser.parse_args()


def main() -> None:
    """Punto de entrada del programa."""
    args = parse_args()
    folder = args.instance.expanduser().resolve()

    data = load_instance(folder)
    validate_parameters(data)
    print_summary(folder, data)

    print(
        "\nValidación inicial completada. "
        "La construcción del modelo PuLP se añadirá en la siguiente etapa."
    )


if __name__ == "__main__":
    main()
