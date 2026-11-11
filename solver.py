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


def build_transport_set(
    data: Data,
    origins: Dict[str, Row],
    centers: Dict[str, Row],
    destinations: Dict[str, Row],
    trucks: Dict[str, Row],
) -> Set[TransportKey]:
    """Construye transport_set=(i,j,v) desde caminos.csv.

    Una fila con Centro genera dos tramos:
    Origen->Centro y Centro->Destino.
    Una fila sin Centro genera un tramo directo Origen->Destino.
    """
    transport: Set[TransportKey] = set()

    for row_number, row in enumerate(data["caminos.csv"], start=2):
        p = row["Origen"].strip()
        s = row["Centro"].strip()
        d = row["Destino"].strip()
        v1 = row["CamionTramo1"].strip()
        v2 = row["CamionTramo2"].strip()

        if p not in origins:
            raise ValueError(
                f"caminos.csv fila {row_number}: origen desconocido {p}."
            )
        if d not in destinations:
            raise ValueError(
                f"caminos.csv fila {row_number}: destino desconocido {d}."
            )
        if v1 not in trucks:
            raise ValueError(
                f"caminos.csv fila {row_number}: camión desconocido {v1}."
            )

        if s:
            if s not in centers:
                raise ValueError(
                    f"caminos.csv fila {row_number}: centro desconocido {s}."
                )
            if v2 not in trucks:
                raise ValueError(
                    f"caminos.csv fila {row_number}: "
                    f"camión desconocido {v2}."
                )
            transport.add((p, s, v1))
            transport.add((s, d, v2))
        else:
            if not is_one(origins[p]["PreClasificado"]):
                raise ValueError(
                    f"{p} tiene camino directo pero PreClasificado != 1."
                )
            transport.add((p, d, v1))

    # En puntos restringidos solo se admite el tipo marcado como Urbano.
    filtered: Set[TransportKey] = set()
    for i, j, v in transport:
        if (
            i in origins
            and is_one(origins[i]["AccesoRestringido"])
            and not is_one(trucks[v]["Urbano"])
        ):
            continue
        filtered.add((i, j, v))

    return filtered


def build_model(data: Data):
    """Construye el problema LP, sus variables y expresiones auxiliares."""
    origins = {r["OrigenID"]: r for r in data["origenes.csv"]}
    centers = {r["CentroID"]: r for r in data["centros.csv"]}
    destinations = {r["DestinoID"]: r for r in data["destinos.csv"]}
    fractions = {r["FraccionID"]: r for r in data["fracciones.csv"]}
    trucks = {r["CamionID"]: r for r in data["camiones.csv"]}

    point_ids = list(origins)
    center_ids = list(centers)
    destination_ids = list(destinations)
    fraction_ids = list(fractions)

    offer = {
        (r["OrigenID"], r["FraccionID"]): as_float(
            r["Toneladas"],
            f"oferta.csv {r['OrigenID']}/{r['FraccionID']}",
        )
        for r in data["oferta.csv"]
    }
    compatibility = {
        (r["FraccionID"], r["DestinoID"]): int(
            as_float(r["Permitido"], "compatibilidad.csv Permitido")
        )
        for r in data["compatibilidad.csv"]
    }
    destination_value = {
        (r["FraccionID"], r["DestinoID"]): as_float(
            r["Valor"], "valor_destino.csv Valor"
        )
        for r in data["valor_destino.csv"]
    }
    performance = {
        (r["FraccionID"], r["CentroID"]): as_float(
            r["Rendimiento"], "rendimiento.csv Rendimiento"
        )
        for r in data["rendimiento.csv"]
    }
    transport_cost = {
        (r["Desde"], r["Hasta"], r["CamionID"]): as_float(
            r["CostoPorTonelada"],
            "costos_transporte.csv CostoPorTonelada",
        )
        for r in data["costos_transporte.csv"]
    }
    distance = {
        (r["Desde"], r["Hasta"]): as_float(
            r["Distancia"], "distancias.csv Distancia"
        )
        for r in data["distancias.csv"]
    }
    parameters = {
        r["Parametro"]: as_float(
            r["Valor"], f"parametros.csv {r['Parametro']}"
        )
        for r in data["parametros.csv"]
    }

    theta = parameters["MetaREP"]
    emission_budget = parameters["PresupuestoCarbono"]

    beta = {
        f: as_float(fractions[f]["BonoREP"], f"BonoREP {f}")
        for f in fraction_ids
    }
    center_cost = {
        s: as_float(centers[s]["CostoManejo"], f"CostoManejo {s}")
        for s in center_ids
    }
    emission_factor = {
        v: as_float(trucks[v]["FactorEmision"], f"FactorEmision {v}")
        for v in trucks
    }
    capacity = {
        d: as_float(
            destinations[d]["CapacidadRecepcion"],
            f"CapacidadRecepcion {d}",
        )
        for d in destination_ids
    }
    minimum = {
        d: as_float(destinations[d]["CuotaMinima"], f"CuotaMinima {d}")
        for d in destination_ids
    }

    mandatory_origins = {
        p for p in point_ids if is_one(origins[p]["RetiroObligatorio"])
    }
    certified_centers = {
        s for s in center_ids if is_one(centers[s]["Certificado"])
    }
    contract_destinations = {
        d for d in destination_ids
        if is_one(destinations[d]["Contrato"]) or minimum[d] > 0
    }

    contract_fractions = {d: set() for d in destination_ids}
    for r in data["fracciones_contrato.csv"]:
        d = r["DestinoID"]
        f = r["FraccionID"]
        if d not in destinations or f not in fractions:
            raise ValueError(
                f"Par contractual desconocido: {d}/{f}."
            )
        if compatibility.get((f, d), 0) != 1:
            raise ValueError(
                f"{f} cuenta para contrato de {d}, pero no es compatible."
            )
        contract_fractions[d].add(f)

    transport_set = build_transport_set(
        data, origins, centers, destinations, trucks
    )

    for i, j, v in transport_set:
        if (i, j, v) not in transport_cost:
            raise ValueError(
                f"Falta costo de transporte para ({i}, {j}, {v})."
            )
        if (i, j) not in distance:
            raise ValueError(
                f"Falta distancia para ({i}, {j})."
            )

    offered_by_origin = {p: set() for p in point_ids}
    for (p, f), amount in offer.items():
        if p not in origins or f not in fractions:
            raise ValueError(f"Oferta con clave desconocida: {p}/{f}.")
        if amount < 0:
            raise ValueError(f"Oferta negativa para {p}/{f}.")
        offered_by_origin[p].add(f)

    fractions_at_center = {s: set() for s in center_ids}
    for p, s, _v in transport_set:
        if p in origins and s in centers:
            fractions_at_center[s].update(offered_by_origin[p])

    active_sf = {
        (s, f)
        for s in center_ids
        for f in fractions_at_center[s]
    }
    for s, f in active_sf:
        if (f, s) not in performance:
            raise ValueError(
                f"Falta rendimiento para {f} en {s}."
            )
        if not 0 <= performance[f, s] <= 1:
            raise ValueError(
                f"Rendimiento fuera de [0,1] para {f}/{s}."
            )

    problem = pulp.LpProblem(
        "Reverse_Logistics_Textile", pulp.LpMaximize
    )

    x: Dict[FlowKey, pulp.LpVariable] = {}
    for i, j, v in sorted(transport_set):
        if i in origins:
            candidate_fractions: Iterable[str] = offered_by_origin[i]
        elif i in centers:
            candidate_fractions = fractions_at_center[i]
        else:
            continue

        for f in candidate_fractions:
            if j in destinations and compatibility.get((f, j), 0) != 1:
                continue
            x[i, j, f, v] = pulp.LpVariable(
                f"x_{i}_{j}_{f}_{v}",
                lowBound=0,
                cat="Continuous",
            )

    u = {
        (s, f): pulp.LpVariable(
            f"u_{s}_{f}", lowBound=0, cat="Continuous"
        )
        for s, f in sorted(active_sf)
    }

    def flow_sum(origin=None, destination=None, fraction=None):
        return pulp.lpSum(
            variable
            for (i, j, f, _v), variable in x.items()
            if all((
                origin is None or i == origin,
                destination is None or j == destination,
                fraction is None or f == fraction,
            ))
        )

    collected_expr = {
        (p, f): flow_sum(origin=p, fraction=f)
        for p, f in offer
    }
    center_in_expr = {
        (s, f): flow_sum(destination=s, fraction=f)
        for s, f in active_sf
    }
    center_out_expr = {
        (s, f): flow_sum(origin=s, fraction=f)
        for s, f in active_sf
    }
    destination_in_expr = {
        (d, f): flow_sum(destination=d, fraction=f)
        for d in destination_ids for f in fraction_ids
    }

    value_term = pulp.lpSum(
        destination_value.get((f, d), 0.0) * destination_in_expr[d, f]
        for d in destination_ids for f in fraction_ids
    )
    rep_term = pulp.lpSum(
        beta[f] * center_out_expr[s, f]
        for s in certified_centers
        for f in fractions_at_center[s]
        if (s, f) in center_out_expr
    )
    classification_term = pulp.lpSum(
        center_cost[s] * center_in_expr[s, f]
        for s, f in active_sf
    )
    transport_term = pulp.lpSum(
        transport_cost[i, j, v] * variable
        for (i, j, _f, v), variable in x.items()
    )

    problem += (
        value_term + rep_term - classification_term - transport_term
    ), "Utilidad_Total"

    # R1: disponibilidad.
    for (p, f), available in offer.items():
        problem += (
            collected_expr[p, f] <= available,
            f"R1_Disponibilidad_{p}_{f}",
        )

    # R2: retiro total obligatorio.
    for (p, f), available in offer.items():
        if p in mandatory_origins:
            problem += (
                collected_expr[p, f] == available,
                f"R2_Retiro_Obligatorio_{p}_{f}",
            )

    # R3: meta mínima REP.
    total_offer = sum(offer.values())
    problem += (
        pulp.lpSum(collected_expr.values()) >= theta * total_offer,
        "R3_Meta_REP",
    )

    # R4: conservación de flujo en centros.
    for s, f in sorted(active_sf):
        problem += (
            center_out_expr[s, f] + u[s, f] == (
                performance[f, s] * center_in_expr[s, f]
            ),
            f"R4_Flujo_Centro_{s}_{f}",
        )

    # R5: compatibilidad fracción-destino.
    for d in destination_ids:
        for f in fraction_ids:
            allowed = compatibility.get((f, d), 0)
            problem += (
                destination_in_expr[d, f] <= allowed * capacity[d],
                f"R5_Compatibilidad_{d}_{f}",
            )

    # R6: capacidad máxima de destinos.
    for d in destination_ids:
        problem += (
            pulp.lpSum(destination_in_expr[d, f] for f in fraction_ids) <= capacity[d],
            f"R6_Capacidad_{d}",
        )

    # R7: cuota mínima contractual.
    for d in contract_destinations:
        if minimum[d] <= 0:
            continue
        if not contract_fractions[d]:
            raise ValueError(
                f"{d} tiene cuota mínima, pero no fracciones contractuales."
            )
        problem += (
            pulp.lpSum(
                destination_in_expr[d, f] for f in contract_fractions[d]
            ) >= minimum[d],
            f"R7_Cuota_Minima_{d}",
        )

    # R8: se implementa creando variables solo para ternas permitidas transport_set.

    # R9: presupuesto global de emisiones.
    total_emissions = pulp.lpSum(
        variable * emission_factor[v] * distance[i, j]
        for (i, j, _f, v), variable in x.items()
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
    return problem, x, u, expressions


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
            safe_value(value) for value in expressions["collected_expr"].values()
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

    problem, x, u, expressions = build_model(data)
    print(
        f"\nModelo construido: {len(x)} variables de flujo, "
        f"{len(u)} variables de descarte y "
        f"{len(problem.constraints)} restricciones."
    )

    status = solve_model(problem, args.verbose)
    print_solution(problem, x, u, expressions, status)

    output_path = save_solution(
        folder,
        args.output_dir,
        problem,
        x,
        u,
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
