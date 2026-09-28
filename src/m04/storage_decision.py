import argparse
import json
from pathlib import Path


REQUIRED_ALTERNATIVES = {
    "document",
    "graph",
    "column",
    "object",
}

VALID_SCORE_STATUSES = {
    "scored",
    "pending",
}


class MatrixValidationError(ValueError):
    """Error de validacion estructural de la matriz M04."""


class MatrixIncompleteError(ValueError):
    """La matriz es valida, pero todavia contiene valores pendientes."""


def load_matrix(path):
    """Carga una matriz JSON desde disco."""
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def _is_number(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
    )


def validate_matrix(matrix):
    """Valida estructura, pesos, alternativas, scores y trazabilidad."""
    criteria = matrix.get("criteria")
    alternatives = matrix.get("alternatives")

    if not isinstance(criteria, list) or not criteria:
        raise MatrixValidationError(
            "La matriz debe definir criterios."
        )

    if not isinstance(alternatives, list) or not alternatives:
        raise MatrixValidationError(
            "La matriz debe definir alternativas."
        )

    criterion_ids = []
    total_weight = 0

    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise MatrixValidationError(
                "Cada criterio debe ser un objeto."
            )

        criterion_id = criterion.get("id")
        weight = criterion.get("weight")

        if (
            not isinstance(criterion_id, str)
            or not criterion_id.strip()
        ):
            raise MatrixValidationError(
                "Cada criterio debe tener un id."
            )

        if criterion_id in criterion_ids:
            raise MatrixValidationError(
                f"Criterio duplicado: {criterion_id}"
            )

        if not _is_number(weight):
            raise MatrixValidationError(
                f"Peso invalido para {criterion_id}."
            )

        if weight <= 0:
            raise MatrixValidationError(
                f"El peso de {criterion_id} debe ser mayor que cero."
            )

        criterion_ids.append(criterion_id)
        total_weight += weight

    if total_weight != 100:
        raise MatrixValidationError(
            "Los pesos deben sumar 100; "
            f"actualmente suman {total_weight}."
        )

    alternative_ids = [
        alternative.get("id")
        for alternative in alternatives
        if isinstance(alternative, dict)
    ]

    if len(alternative_ids) != len(set(alternative_ids)):
        raise MatrixValidationError(
            "No se permiten alternativas duplicadas."
        )

    if set(alternative_ids) != REQUIRED_ALTERNATIVES:
        raise MatrixValidationError(
            "La matriz debe contener exactamente Document, Graph, "
            "Column/Wide-column y Object."
        )

    criterion_id_set = set(criterion_ids)

    for alternative in alternatives:
        alternative_id = alternative["id"]

        if not alternative.get("name"):
            raise MatrixValidationError(
                f"{alternative_id} debe tener name."
            )

        if not alternative.get("representative"):
            raise MatrixValidationError(
                f"{alternative_id} debe tener representative."
            )

        scores = alternative.get("scores")

        if not isinstance(scores, dict):
            raise MatrixValidationError(
                f"{alternative_id} debe definir scores."
            )

        if set(scores) != criterion_id_set:
            raise MatrixValidationError(
                f"{alternative_id} debe puntuar todos los criterios "
                "exactamente una vez."
            )

        for criterion_id in criterion_ids:
            score_data = scores[criterion_id]

            if not isinstance(score_data, dict):
                raise MatrixValidationError(
                    f"Puntuacion invalida en "
                    f"{alternative_id}/{criterion_id}."
                )

            status = score_data.get("status")
            value = score_data.get("value")
            trace = score_data.get("trace")

            if status not in VALID_SCORE_STATUSES:
                raise MatrixValidationError(
                    f"Estado invalido en "
                    f"{alternative_id}/{criterion_id}: {status}"
                )

            if status == "scored":
                if (
                    not _is_number(value)
                    or value < 1
                    or value > 5
                ):
                    raise MatrixValidationError(
                        f"La puntuacion de "
                        f"{alternative_id}/{criterion_id} "
                        "debe estar entre 1 y 5."
                    )

            if status == "pending":
                if value is not None:
                    raise MatrixValidationError(
                        f"{alternative_id}/{criterion_id} "
                        "esta pendiente y debe usar value=null."
                    )

            if (
                not isinstance(trace, list)
                or not trace
                or not all(
                    isinstance(reference, str)
                    and reference.strip()
                    for reference in trace
                )
            ):
                raise MatrixValidationError(
                    f"{alternative_id}/{criterion_id} "
                    "debe incluir evidencia o hipotesis en trace."
                )

    return True


def get_pending_scores(matrix):
    """Devuelve todos los criterios que todavia estan pendientes."""
    validate_matrix(matrix)

    pending = []

    for alternative in matrix["alternatives"]:
        for criterion_id, score_data in alternative["scores"].items():
            if score_data["status"] == "pending":
                pending.append(
                    {
                        "alternative_id": alternative["id"],
                        "alternative_name": alternative["name"],
                        "criterion_id": criterion_id,
                        "trace": score_data["trace"],
                    }
                )

    return pending


def calculate_results(matrix):
    """Calcula la matriz completa sin inventar valores pendientes."""
    validate_matrix(matrix)

    pending = get_pending_scores(matrix)

    if pending:
        pending_names = ", ".join(
            f"{item['alternative_id']}/{item['criterion_id']}"
            for item in pending
        )

        raise MatrixIncompleteError(
            "La matriz contiene puntuaciones pendientes: "
            + pending_names
        )

    weights = {
        criterion["id"]: criterion["weight"]
        for criterion in matrix["criteria"]
    }

    results = []

    for alternative in matrix["alternatives"]:
        weighted_points = sum(
            alternative["scores"][criterion_id]["value"]
            * weight
            for criterion_id, weight in weights.items()
        )

        results.append(
            {
                "id": alternative["id"],
                "name": alternative["name"],
                "representative": alternative["representative"],
                "weighted_points": weighted_points,
                "weighted_score": weighted_points / 100,
            }
        )

    best_points = max(
        result["weighted_points"]
        for result in results
    )

    winners = [
        result["id"]
        for result in results
        if result["weighted_points"] == best_points
    ]

    return {
        "weights_total": sum(weights.values()),
        "alternatives_evaluated": len(results),
        "decision_status": "complete",
        "results": results,
        "winners": winners,
        "tie": len(winners) > 1,
        "pending_scores": [],
    }


def evaluate_matrix(matrix):
    """
    Evalua la matriz.

    Si todavia existen scores pendientes, valida la matriz pero no
    fabrica un ganador ni renormaliza los pesos.
    """
    validate_matrix(matrix)

    pending = get_pending_scores(matrix)

    if pending:
        return {
            "weights_total": sum(
                criterion["weight"]
                for criterion in matrix["criteria"]
            ),
            "alternatives_evaluated": len(
                matrix["alternatives"]
            ),
            "decision_status": "pending",
            "results": [],
            "winners": [],
            "tie": False,
            "pending_scores": pending,
            "reason": (
                "No se calcula una decision final mientras existan "
                "criterios pendientes."
            ),
        }

    return calculate_results(matrix)


def write_results(result, output_path):
    """Escribe un resultado machine-readable en JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Valida y calcula la matriz de seleccion NoSQL M04."
        )
    )

    parser.add_argument(
        "--matrix",
        default="src/m04/storage_matrix.json",
        help="Ruta de la matriz JSON.",
    )

    parser.add_argument(
        "--output",
        help="Ruta opcional para guardar el resultado JSON.",
    )

    parser.add_argument(
        "--require-complete",
        action="store_true",
        help=(
            "Falla si la matriz contiene puntuaciones pendientes."
        ),
    )

    args = parser.parse_args()

    matrix = load_matrix(args.matrix)

    if args.require_complete:
        result = calculate_results(matrix)
    else:
        result = evaluate_matrix(matrix)

    if args.output:
        write_results(result, args.output)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()