"""Solver de logística inversa textil - Grupo 2.

Implementación del modelo LP definido en el Technical Report.

Uso:
    python solver.py test_cases/case_1
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

import pulp


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
        "Origen", "Centro", "Destino", "CamionTramo1", "CamionTramo2"
    },
    "camiones.csv": {"CamionID", "FactorEmision", "Urbano"},
    "centros.csv": {"CentroID", "Certificado", "CostoManejo"},
    "compatibilidad.csv": {"FraccionID", "DestinoID", "Permitido"},
    "costos_transporte.csv": {
        "Desde", "Hasta", "CamionID", "CostoPorTonelada"
    },
    "destinos.csv": {
        "DestinoID", "CapacidadRecepcion", "CuotaMinima", "Contrato"
    },
    "distancias.csv": {"Desde", "Hasta", "Distancia"},
    "fracciones.csv": {"FraccionID", "BonoREP"},
    "fracciones_contrato.csv": {"DestinoID", "FraccionID"},
    "oferta.csv": {"OrigenID", "FraccionID", "Toneladas"},
    "origenes.csv": {
        "OrigenID", "RetiroObligatorio", "PreClasificado",
        "AccesoRestringido"
    },
    "parametros.csv": {"Parametro", "Valor"},
    "rendimiento.csv": {"FraccionID", "CentroID", "Rendimiento"},
}

Row = Dict[str, str]
Data = Dict[str, List[Row]]
FlowKey = Tuple[str, str, str, str]
TransportKey = Tuple[str, str, str]


def read_csv(path: Path) -> List[Row]:
    """Lee un CSV separado por punto y coma."""
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file, delimiter=";"))


def as_float(value: str, label: str) -> float:
    """Convierte un dato a float con un error entendible."""
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"No se pudo convertir '{value}' a número en {label}."
        ) from error


def is_one(value: str) -> bool:
    """Interpreta los indicadores binarios de los CSV."""
    return str(value).strip() in {
        "1", "1.0", "True", "true", "SI", "Si", "sí"
    }


def validate_files(folder: Path) -> None:
    """Verifica que estén los 15 archivos de la instancia."""
    missing = [name for name in CSV_FILES if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "Faltan archivos requeridos: " + ", ".join(missing)
        )


def validate_columns(name: str, rows: List[Row], folder: Path) -> None:
    """Comprueba las columnas esenciales de cada archivo."""
    required = REQUIRED_COLUMNS.get(name)
    if not required:
        return
    if not rows:
        raise ValueError(f"{name} está vacío.")

    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(
            f"{name} no contiene: {', '.join(sorted(missing))}. "
            f"Archivo: {folder / name}"
        )


def load_instance(folder: Path) -> Data:
    """Carga y valida la estructura básica de los CSV."""
    validate_files(folder)
    data: Data = {}
    for name in CSV_FILES:
        rows = read_csv(folder / name)
        validate_columns(name, rows, folder)
        data[name] = rows
    return data


def validate_parameters(data: Data) -> None:
    """Valida los parámetros globales del modelo."""
    parameters = {
        row["Parametro"]: row["Valor"]
        for row in data["parametros.csv"]
    }
    required = {"MetaREP", "PresupuestoCarbono"}
    missing = required - set(parameters)
    if missing:
        raise ValueError(
            "Faltan parámetros: " + ", ".join(sorted(missing))
        )

    theta = as_float(parameters["MetaREP"], "MetaREP")
    carbon = as_float(
        parameters["PresupuestoCarbono"], "PresupuestoCarbono"
    )
    if not 0 <= theta <= 1:
        raise ValueError("MetaREP debe estar entre 0 y 1.")
    if carbon < 0:
        raise ValueError("PresupuestoCarbono no puede ser negativo.")


def parse_transport_row(
    row: Row,
    row_number: int,
    origins: Dict[str, Row],
    centers: Dict[str, Row],
    destinations: Dict[str, Row],
    trucks: Dict[str, Row],
) -> Tuple[str, str, str, str, str]:
    """Lee y valida una fila de caminos.csv."""
    point = row["Origen"].strip()
    center = row["Centro"].strip()
    destination = row["Destino"].strip()
    truck_first = row["CamionTramo1"].strip()
    truck_second = row["CamionTramo2"].strip()

    if point not in origins:
        raise ValueError(
            f"caminos.csv fila {row_number}: "
            f"origen desconocido {point}."
        )
    if destination not in destinations:
        raise ValueError(
            f"caminos.csv fila {row_number}: "
            f"destino desconocido {destination}."
        )
    if truck_first not in trucks:
        raise ValueError(
            f"caminos.csv fila {row_number}: "
            f"camión desconocido {truck_first}."
        )

    if center:
        if center not in centers:
            raise ValueError(
                f"caminos.csv fila {row_number}: "
                f"centro desconocido {center}."
            )
        if truck_second not in trucks:
            raise ValueError(
                f"caminos.csv fila {row_number}: "
                f"camión desconocido {truck_second}."
            )
    elif not is_one(origins[point]["PreClasificado"]):
        raise ValueError(
            f"{point} tiene camino directo pero PreClasificado != 1."
        )

    return point, center, destination, truck_first, truck_second


def build_transport_set(
    data: Data,
    origins: Dict[str, Row],
    centers: Dict[str, Row],
    destinations: Dict[str, Row],
    trucks: Dict[str, Row],
) -> Set[TransportKey]:
    """Construye las ternas de transporte permitidas (i, j, v)."""
    transport: Set[TransportKey] = set()

    for row_number, row in enumerate(data["caminos.csv"], start=2):
        point, center, destination, truck_first, truck_second = (
            parse_transport_row(
                row,
                row_number,
                origins,
                centers,
                destinations,
                trucks,
            )
        )

        if center:
            transport.add((point, center, truck_first))
            transport.add((center, destination, truck_second))
        else:
            transport.add((point, destination, truck_first))

    filtered: Set[TransportKey] = set()
    for origin, destination, truck in transport:
        restricted = (
            origin in origins
            and is_one(origins[origin]["AccesoRestringido"])
        )
        if restricted and not is_one(trucks[truck]["Urbano"]):
            continue
        filtered.add((origin, destination, truck))

    return filtered


def build_contract_fractions(
    data: Data,
    destinations: Dict[str, Row],
    fractions: Dict[str, Row],
    compatibility,
):
    """Construye y valida las fracciones que cuentan para contratos."""
    contract_fractions = {d: set() for d in destinations}

    for row in data["fracciones_contrato.csv"]:
        destination = row["DestinoID"]
        fraction = row["FraccionID"]

        if destination not in destinations or fraction not in fractions:
            raise ValueError(
                "Par contractual desconocido: "
                f"{destination}/{fraction}."
            )
        if compatibility.get((fraction, destination), 0) != 1:
            raise ValueError(
                f"{fraction} cuenta para contrato de {destination}, "
                "pero no es compatible."
            )
        contract_fractions[destination].add(fraction)

    return contract_fractions


def validate_transport_data(
    transport_set: Set[TransportKey],
    transport_cost,
    distance,
) -> None:
    """Valida costos y distancias para cada terna de transporte."""
    for origin, destination, truck in transport_set:
        if (origin, destination, truck) not in transport_cost:
            raise ValueError(
                "Falta costo de transporte para "
                f"({origin}, {destination}, {truck})."
            )
        if (origin, destination) not in distance:
            raise ValueError(
                f"Falta distancia para ({origin}, {destination})."
            )


def build_origin_fraction_sets(
    offer,
    origins: Dict[str, Row],
    fractions: Dict[str, Row],
):
    """Agrupa las fracciones con oferta disponible en cada origen."""
    offered_by_origin = {point: set() for point in origins}

    for (point, fraction), amount in offer.items():
        if point not in origins or fraction not in fractions:
            raise ValueError(
                f"Oferta con clave desconocida: {point}/{fraction}."
            )
        if amount < 0:
            raise ValueError(
                f"Oferta negativa para {point}/{fraction}."
            )
        offered_by_origin[point].add(fraction)

    return offered_by_origin


def build_center_fraction_sets(
    transport_set: Set[TransportKey],
    origins: Dict[str, Row],
    centers: Dict[str, Row],
    offered_by_origin,
):
    """Determina qué fracciones pueden ingresar a cada centro."""
    fractions_at_center = {center: set() for center in centers}

    for origin, destination, _truck in transport_set:
        if origin in origins and destination in centers:
            fractions_at_center[destination].update(
                offered_by_origin[origin]
            )

    return fractions_at_center


def validate_performance(active_sf, performance) -> None:
    """Valida que todo rendimiento requerido exista y esté entre 0 y 1."""
    for center, fraction in active_sf:
        if (fraction, center) not in performance:
            raise ValueError(
                f"Falta rendimiento para {fraction} en {center}."
            )
        if not 0 <= performance[fraction, center] <= 1:
            raise ValueError(
                "Rendimiento fuera de [0,1] para "
                f"{fraction}/{center}."
            )


def create_flow_variables(
    transport_set: Set[TransportKey],
    origins: Dict[str, Row],
    centers: Dict[str, Row],
    destinations: Dict[str, Row],
    offered_by_origin,
    fractions_at_center,
    compatibility,
):
    """Crea variables continuas solo para flujos factibles."""
    flow_variables: Dict[FlowKey, pulp.LpVariable] = {}

    for origin, destination, truck in sorted(transport_set):
        if origin in origins:
            candidate_fractions: Iterable[str] = (
                offered_by_origin[origin]
            )
        elif origin in centers:
            candidate_fractions = fractions_at_center[origin]
        else:
            continue

        for fraction in candidate_fractions:
            incompatible = (
                destination in destinations
                and compatibility.get(
                    (fraction, destination),
                    0,
                ) != 1
            )
            if incompatible:
                continue

            flow_variables[
                origin,
                destination,
                fraction,
                truck,
            ] = pulp.LpVariable(
                f"x_{origin}_{destination}_{fraction}_{truck}",
                lowBound=0,
                cat="Continuous",
            )

    return flow_variables


def flow_sum(
    flow_variables,
    origin=None,
    destination=None,
    fraction=None,
):
    """Suma variables de flujo que cumplen los filtros indicados."""
    return pulp.lpSum(
        variable
        for (i, j, f, _truck), variable in flow_variables.items()
        if all((
            origin is None or i == origin,
            destination is None or j == destination,
            fraction is None or f == fraction,
        ))
    )


def build_flow_expressions(
    flow_variables,
    offer,
    active_sf,
    destination_ids,
    fraction_ids,
):
    """Construye expresiones auxiliares de retiro, ingreso y entrega."""
    collected_expr = {
        (point, fraction): flow_sum(
            flow_variables,
            origin=point,
            fraction=fraction,
        )
        for point, fraction in offer
    }
    center_in_expr = {
        (center, fraction): flow_sum(
            flow_variables,
            destination=center,
            fraction=fraction,
        )
        for center, fraction in active_sf
    }
    center_out_expr = {
        (center, fraction): flow_sum(
            flow_variables,
            origin=center,
            fraction=fraction,
        )
        for center, fraction in active_sf
    }
    destination_in_expr = {
        (destination, fraction): flow_sum(
            flow_variables,
            destination=destination,
            fraction=fraction,
        )
        for destination in destination_ids
        for fraction in fraction_ids
    }

    return (
        collected_expr,
        center_in_expr,
        center_out_expr,
        destination_in_expr,
    )


def add_collection_constraints(
    problem,
    offer,
    collected_expr,
    mandatory_origins,
    theta,
) -> float:
    """Agrega disponibilidad, retiro obligatorio y Meta REP."""
    for (point, fraction), available in offer.items():
        problem += (
            collected_expr[point, fraction] <= available,
            f"R1_Disponibilidad_{point}_{fraction}",
        )

        if point in mandatory_origins:
            problem += (
                collected_expr[point, fraction] == available,
                f"R2_Retiro_Obligatorio_{point}_{fraction}",
            )

    total_offer = sum(offer.values())
    problem += (
        pulp.lpSum(collected_expr.values()) >= theta * total_offer,
        "R3_Meta_REP",
    )
    return total_offer


def add_center_constraints(
    problem,
    active_sf,
    center_out_expr,
    center_in_expr,
    discard_variables,
    performance,
) -> None:
    """Agrega conservación de flujo en centros."""
    for center, fraction in sorted(active_sf):
        problem += (
            center_out_expr[center, fraction]
            + discard_variables[center, fraction]
            == performance[fraction, center]
            * center_in_expr[center, fraction],
            f"R4_Flujo_Centro_{center}_{fraction}",
        )


def add_destination_constraints(
    problem,
    destination_ids,
    fraction_ids,
    destination_in_expr,
    compatibility,
    capacity,
    contract_destinations,
    minimum,
    contract_fractions,
) -> None:
    """Agrega compatibilidad, capacidad y mínimos contractuales."""
    for destination in destination_ids:
        for fraction in fraction_ids:
            allowed = compatibility.get((fraction, destination), 0)
            problem += (
                destination_in_expr[destination, fraction]
                <= allowed * capacity[destination],
                f"R5_Compatibilidad_{destination}_{fraction}",
            )

        problem += (
            pulp.lpSum(
                destination_in_expr[destination, fraction]
                for fraction in fraction_ids
            ) <= capacity[destination],
            f"R6_Capacidad_{destination}",
        )

    for destination in contract_destinations:
        if minimum[destination] <= 0:
            continue
        if not contract_fractions[destination]:
            raise ValueError(
                f"{destination} tiene cuota mínima, "
                "pero no fracciones contractuales."
            )

        problem += (
            pulp.lpSum(
                destination_in_expr[destination, fraction]
                for fraction in contract_fractions[destination]
            ) >= minimum[destination],
            f"R7_Cuota_Minima_{destination}",
        )


def build_model(data: Data):
    """Construye el problema LP, sus variables y expresiones auxiliares."""
    origins = {row["OrigenID"]: row for row in data["origenes.csv"]}
    centers = {row["CentroID"]: row for row in data["centros.csv"]}
    destinations = {
        row["DestinoID"]: row
        for row in data["destinos.csv"]
    }
    fractions = {
        row["FraccionID"]: row
        for row in data["fracciones.csv"]
    }
    trucks = {row["CamionID"]: row for row in data["camiones.csv"]}

    point_ids = list(origins)
    center_ids = list(centers)
    destination_ids = list(destinations)
    fraction_ids = list(fractions)

    offer = {
        (row["OrigenID"], row["FraccionID"]): as_float(
            row["Toneladas"],
            (
                "oferta.csv "
                f"{row['OrigenID']}/{row['FraccionID']}"
            ),
        )
        for row in data["oferta.csv"]
    }
    compatibility = {
        (row["FraccionID"], row["DestinoID"]): int(
            as_float(
                row["Permitido"],
                "compatibilidad.csv Permitido",
            )
        )
        for row in data["compatibilidad.csv"]
    }
    destination_value = {
        (row["FraccionID"], row["DestinoID"]): as_float(
            row["Valor"],
            "valor_destino.csv Valor",
        )
        for row in data["valor_destino.csv"]
    }
    performance = {
        (row["FraccionID"], row["CentroID"]): as_float(
            row["Rendimiento"],
            "rendimiento.csv Rendimiento",
        )
        for row in data["rendimiento.csv"]
    }
    transport_cost = {
        (row["Desde"], row["Hasta"], row["CamionID"]): as_float(
            row["CostoPorTonelada"],
            "costos_transporte.csv CostoPorTonelada",
        )
        for row in data["costos_transporte.csv"]
    }
    distance = {
        (row["Desde"], row["Hasta"]): as_float(
            row["Distancia"],
            "distancias.csv Distancia",
        )
        for row in data["distancias.csv"]
    }
    parameters = {
        row["Parametro"]: as_float(
            row["Valor"],
            f"parametros.csv {row['Parametro']}",
        )
        for row in data["parametros.csv"]
    }

    theta = parameters["MetaREP"]
    emission_budget = parameters["PresupuestoCarbono"]

    beta = {
        fraction: as_float(
            fractions[fraction]["BonoREP"],
            f"BonoREP {fraction}",
        )
        for fraction in fraction_ids
    }
    center_cost = {
        center: as_float(
            centers[center]["CostoManejo"],
            f"CostoManejo {center}",
        )
        for center in center_ids
    }
    emission_factor = {
        truck: as_float(
            trucks[truck]["FactorEmision"],
            f"FactorEmision {truck}",
        )
        for truck in trucks
    }
    capacity = {
        destination: as_float(
            destinations[destination]["CapacidadRecepcion"],
            f"CapacidadRecepcion {destination}",
        )
        for destination in destination_ids
    }
    minimum = {
        destination: as_float(
            destinations[destination]["CuotaMinima"],
            f"CuotaMinima {destination}",
        )
        for destination in destination_ids
    }

    mandatory_origins = {
        point
        for point in point_ids
        if is_one(origins[point]["RetiroObligatorio"])
    }
    certified_centers = {
        center
        for center in center_ids
        if is_one(centers[center]["Certificado"])
    }
    contract_destinations = {
        destination
        for destination in destination_ids
        if (
            is_one(destinations[destination]["Contrato"])
            or minimum[destination] > 0
        )
    }

    contract_fractions = build_contract_fractions(
        data,
        destinations,
        fractions,
        compatibility,
    )
    transport_set = build_transport_set(
        data,
        origins,
        centers,
        destinations,
        trucks,
    )
    validate_transport_data(
        transport_set,
        transport_cost,
        distance,
    )

    offered_by_origin = build_origin_fraction_sets(
        offer,
        origins,
        fractions,
    )
    fractions_at_center = build_center_fraction_sets(
        transport_set,
        origins,
        centers,
        offered_by_origin,
    )
    active_sf = {
        (center, fraction)
        for center in center_ids
        for fraction in fractions_at_center[center]
    }
    validate_performance(active_sf, performance)

    problem = pulp.LpProblem(
        "Reverse_Logistics_Textile",
        pulp.LpMaximize,
    )
    flow_variables = create_flow_variables(
        transport_set,
        origins,
        centers,
        destinations,
        offered_by_origin,
        fractions_at_center,
        compatibility,
    )
    discard_variables = {
        (center, fraction): pulp.LpVariable(
            f"u_{center}_{fraction}",
            lowBound=0,
            cat="Continuous",
        )
        for center, fraction in sorted(active_sf)
    }

    (
        collected_expr,
        center_in_expr,
        center_out_expr,
        destination_in_expr,
    ) = build_flow_expressions(
        flow_variables,
        offer,
        active_sf,
        destination_ids,
        fraction_ids,
    )

    value_term = pulp.lpSum(
        destination_value.get((fraction, destination), 0.0)
        * destination_in_expr[destination, fraction]
        for destination in destination_ids
        for fraction in fraction_ids
    )
    rep_term = pulp.lpSum(
        beta[fraction] * center_out_expr[center, fraction]
        for center in certified_centers
        for fraction in fractions_at_center[center]
        if (center, fraction) in center_out_expr
    )
    classification_term = pulp.lpSum(
        center_cost[center] * center_in_expr[center, fraction]
        for center, fraction in active_sf
    )
    transport_term = pulp.lpSum(
        transport_cost[origin, destination, truck] * variable
        for (
            origin,
            destination,
            _fraction,
            truck,
        ), variable in flow_variables.items()
    )

    problem += (
        value_term
        + rep_term
        - classification_term
        - transport_term,
        "Utilidad_Total",
    )

    total_offer = add_collection_constraints(
        problem,
        offer,
        collected_expr,
        mandatory_origins,
        theta,
    )
    add_center_constraints(
        problem,
        active_sf,
        center_out_expr,
        center_in_expr,
        discard_variables,
        performance,
    )
    add_destination_constraints(
        problem,
        destination_ids,
        fraction_ids,
        destination_in_expr,
        compatibility,
        capacity,
        contract_destinations,
        minimum,
        contract_fractions,
    )

    total_emissions = pulp.lpSum(
        variable
        * emission_factor[truck]
        * distance[origin, destination]
        for (
            origin,
            destination,
            _fraction,
            truck,
        ), variable in flow_variables.items()
    )
    problem += (
        total_emissions <= emission_budget,
        "R9_Presupuesto_CO2",
    )

    expressions = {
        "collected_expr": collected_expr,
        "center_in_expr": center_in_expr,
        "center_out_expr": center_out_expr,
        "destination_in_expr": destination_in_expr,
        "total_emissions": total_emissions,
        "total_offer": total_offer,
        "theta": theta,
        "emission_budget": emission_budget,
    }
    return (
        problem,
        flow_variables,
        discard_variables,
        expressions,
    )


def solve_model(problem: pulp.LpProblem, verbose: bool) -> str:
    """Resuelve el LP con CBC."""
    solver = pulp.PULP_CBC_CMD(msg=verbose)
    problem.solve(solver)
    return pulp.LpStatus[problem.status]


def safe_value(expression) -> float:
    """Convierte el valor de una expresión PuLP a float."""
    value = pulp.value(expression)
    return 0.0 if value is None else float(value)


def print_solution(problem, x, u, expressions, status: str) -> None:
    """Imprime el resultado principal del Solver."""
    print("\n" + "=" * 60)
    print("RESULTADO DEL SOLVER")
    print("=" * 60)
    print(f"Estado: {status}")

    if status != "Optimal":
        print(
            "No se presenta un plan de flujos porque no existe "
            "una solución óptima válida."
        )
        return

    objective = safe_value(problem.objective)
    emissions = safe_value(expressions["total_emissions"])
    collected = sum(
        safe_value(value) for value in expressions["collected_expr"].values()
    )
    total_offer = expressions["total_offer"]
    theta = expressions["theta"]

    print(f"Utilidad óptima: $ {objective:,.2f}")
    print(f"Oferta total: {total_offer:.3f} t")
    print(f"Retiro total: {collected:.3f} t")
    print(
        f"Meta REP mínima: {theta * total_offer:.3f} t "
        f"({theta:.1%})"
    )
    print(
        f"Emisiones: {emissions:.3f} kg CO2 / "
        f"{expressions['emission_budget']:.3f} kg CO2"
    )

    print("\nFlujos positivos:")
    shown = 0
    for (i, j, f, v), variable in sorted(x.items()):
        amount = safe_value(variable)
        if amount > 1e-7:
            shown += 1
            print(f"  {i} -> {j} | {f} | {v}: {amount:.3f} t")
    if shown == 0:
        print("  Sin flujos positivos.")

    print("\nDescarte en centros:")
    shown = 0
    for (s, f), variable in sorted(u.items()):
        amount = safe_value(variable)
        if amount > 1e-7:
            shown += 1
            print(f"  {s} | {f}: {amount:.3f} t")
    if shown == 0:
        print("  Sin descarte.")


def save_solution(
    folder: Path,
    output_dir: Path,
    problem,
    x,
    u,
    expressions,
    status: str,
) -> Path:
    """Guarda un resumen de la solución en un archivo de texto."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{folder.name}_solution.txt"

    lines = [
        "RESULTADO DEL SOLVER",
        f"Instancia: {folder.name}",
        f"Estado: {status}",
    ]

    if status == "Optimal":
        objective = safe_value(problem.objective)
        emissions = safe_value(expressions["total_emissions"])
        collected = sum(
            safe_value(value)
            for value in expressions["collected_expr"].values()
        )
        total_offer = expressions["total_offer"]
        theta = expressions["theta"]

        lines.extend([
            f"Utilidad óptima: $ {objective:,.2f}",
            f"Oferta total: {total_offer:.3f} t",
            f"Retiro total: {collected:.3f} t",
            (
                f"Meta REP mínima: {theta * total_offer:.3f} t "
                f"({theta:.1%})"
            ),
            (
                f"Emisiones: {emissions:.3f} kg CO2 / "
                f"{expressions['emission_budget']:.3f} kg CO2"
            ),
            "",
            "Flujos positivos:",
        ])

        positive_flows = 0
        for (i, j, f, v), variable in sorted(x.items()):
            amount = safe_value(variable)
            if amount > 1e-7:
                positive_flows += 1
                lines.append(
                    f"{i} -> {j} | {f} | {v}: {amount:.3f} t"
                )

        if positive_flows == 0:
            lines.append("Sin flujos positivos.")

        lines.extend(["", "Descarte en centros:"])
        positive_discard = 0
        for (s, f), variable in sorted(u.items()):
            amount = safe_value(variable)
            if amount > 1e-7:
                positive_discard += 1
                lines.append(f"{s} | {f}: {amount:.3f} t")

        if positive_discard == 0:
            lines.append("Sin descarte.")
    else:
        lines.append(
            "No existe una solución óptima válida para esta instancia."
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def print_summary(folder: Path, data: Data) -> None:
    """Imprime un resumen de la instancia."""
    origins = data["origenes.csv"]
    centers = data["centros.csv"]
    destinations = data["destinos.csv"]
    fractions = data["fracciones.csv"]
    trucks = data["camiones.csv"]
    offers = data["oferta.csv"]

    total_offer = sum(
        as_float(r["Toneladas"], "oferta.csv Toneladas")
        for r in offers
    )

    print("\nInstancia cargada correctamente")
    print(f"Carpeta: {folder}")
    print(f"Puntos de recolección: {len(origins)}")
    print(f"Centros de clasificación: {len(centers)}")
    print(f"Destinos de valorización: {len(destinations)}")
    print(f"Fracciones: {len(fractions)}")
    print(f"Tipos de camión: {len(trucks)}")
    print(f"Oferta total: {total_offer:.3f} t")
    print(
        "Puntos con retiro obligatorio: "
        f"{sum(is_one(r['RetiroObligatorio']) for r in origins)}"
    )
    print(
        "Centros certificados: "
        f"{sum(is_one(r['Certificado']) for r in centers)}"
    )
    print(
        "Destinos con contrato: "
        f"{sum(is_one(r['Contrato']) for r in destinations)}"
    )


def parse_args() -> argparse.Namespace:
    """Lee argumentos de terminal."""
    parser = argparse.ArgumentParser(
        description="Solver de logística inversa textil."
    )
    parser.add_argument(
        "instance",
        type=Path,
        help="Carpeta que contiene los 15 CSV.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Muestra el log de CBC.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Carpeta donde se guarda el resumen de la solución.",
    )
    return parser.parse_args()


def main() -> None:
    """Ejecuta carga, construcción, resolución y salida."""
    args = parse_args()
    folder = args.instance.expanduser().resolve()

    data = load_instance(folder)
    validate_parameters(data)
    print_summary(folder, data)

    problem, flow_variables, discard_variables, expressions = (
        build_model(data)
    )
    print(
        f"\nModelo construido: {len(flow_variables)} variables de flujo, "
        f"{len(discard_variables)} variables de descarte y "
        f"{len(problem.constraints)} restricciones."
    )

    status = solve_model(problem, args.verbose)
    print_solution(
        problem,
        flow_variables,
        discard_variables,
        expressions,
        status,
    )

    output_path = save_solution(
        folder,
        args.output_dir,
        problem,
        flow_variables,
        discard_variables,
        expressions,
        status,
    )
    print(f"\nResultado guardado en: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError) as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
