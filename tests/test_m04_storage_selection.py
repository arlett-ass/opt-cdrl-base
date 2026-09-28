import copy
import json
from pathlib import Path

import pytest

from src.m04.storage_decision import (
    MatrixValidationError,
    calculate_results,
    evaluate_matrix,
    validate_matrix,
)


MATRIX_PATH = Path("src/m04/storage_matrix.json")


def load_test_matrix():
    with MATRIX_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def test_real_matrix_is_valid_and_produces_decision():
    """
    Caso normal:
    la matriz real es valida, esta completa y produce una decision.
    """
    matrix = load_test_matrix()

    assert validate_matrix(matrix) is True

    result = evaluate_matrix(matrix)

    assert result["weights_total"] == 100
    assert result["alternatives_evaluated"] == 4
    assert result["decision_status"] == "complete"
    assert result["pending_scores"] == []

    assert result["winners"] == ["document"]
    assert result["tie"] is False

    scores = {
        item["id"]: item["weighted_score"]
        for item in result["results"]
    }

    assert scores == {
        "document": 3.95,
        "graph": 2.9,
        "column": 3.8,
        "object": 2.9,
    }


def test_score_boundaries_one_and_five_are_valid():
    """
    Limite:
    la escala permite exactamente los valores 1 y 5.
    """
    matrix = load_test_matrix()
    boundary_matrix = copy.deepcopy(matrix)

    for index, alternative in enumerate(
        boundary_matrix["alternatives"]
    ):
        boundary_value = 1 if index % 2 == 0 else 5

        for score_data in alternative["scores"].values():
            score_data["value"] = boundary_value
            score_data["status"] = "scored"

    assert validate_matrix(boundary_matrix) is True

    result = calculate_results(boundary_matrix)

    scores = {
        item["id"]: item["weighted_score"]
        for item in result["results"]
    }

    assert scores["document"] == 1.0
    assert scores["graph"] == 5.0
    assert scores["column"] == 1.0
    assert scores["object"] == 5.0

    assert result["winners"] == [
        "graph",
        "object",
    ]

    assert result["tie"] is True


def test_tie_is_preserved_without_invented_tiebreak():
    """
    Limite:
    un empate real en primer lugar debe conservarse.
    """
    matrix = load_test_matrix()
    tie_matrix = copy.deepcopy(matrix)

    values_by_alternative = {
        "document": 4,
        "graph": 2,
        "column": 4,
        "object": 2,
    }

    for alternative in tie_matrix["alternatives"]:
        value = values_by_alternative[alternative["id"]]

        for score_data in alternative["scores"].values():
            score_data["value"] = value
            score_data["status"] = "scored"

    assert validate_matrix(tie_matrix) is True

    result = calculate_results(tie_matrix)

    assert result["decision_status"] == "complete"

    assert result["winners"] == [
        "document",
        "column",
    ]

    assert result["tie"] is True
    assert "tiebreaker" not in result

    document = next(
        item
        for item in result["results"]
        if item["id"] == "document"
    )

    column = next(
        item
        for item in result["results"]
        if item["id"] == "column"
    )

    assert (
        document["weighted_score"]
        == column["weighted_score"]
        == 4.0
    )


def test_invalid_weights_are_rejected():
    """
    Fallo declarado:
    pesos que no suman 100 deben rechazarse.
    """
    matrix = load_test_matrix()
    invalid_matrix = copy.deepcopy(matrix)

    invalid_matrix["criteria"][0]["weight"] = 29

    with pytest.raises(
        MatrixValidationError,
        match="Los pesos deben sumar 100",
    ):
        validate_matrix(invalid_matrix)