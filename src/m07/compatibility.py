"""Adaptación de documentos versionados para consumidores existentes en M07.

El adaptador permite que un consumidor v1 continúe leyendo durante la
coexistencia temporal de documentos v1 y v2.

La adaptación ocurre únicamente en memoria:
- no escribe en DynamoDB;
- no migra implícitamente el documento persistido;
- no modifica el documento recibido.
"""

from copy import deepcopy

from .versioning import validate_document


SUPPORTED_CONSUMER_VERSIONS = (1,)


class UnsupportedConsumerVersionError(ValueError):
    """El consumidor solicitado no está soportado por este adaptador."""


def adapt_for_consumer(document, consumer_version):
    """Entrega una representación compatible con el consumidor solicitado.

    Actualmente solo se soporta consumidor v1.

    Un documento persistido v1 se devuelve como una copia normalizada v1.
    Un documento persistido v2 se transforma en memoria a la representación
    v1, conservando identidad, datos y metadatos necesarios para que el
    consumidor antiguo pueda interpretarlo.

    El documento original nunca se modifica y no se realiza ninguna escritura
    ni migración implícita en DynamoDB.
    """
    if (
        type(consumer_version) is not int
        or consumer_version not in SUPPORTED_CONSUMER_VERSIONS
    ):
        raise UnsupportedConsumerVersionError(
            f"Versión de consumidor no soportada: {consumer_version!r}."
        )

    normalized = validate_document(document)
    stored_version = normalized["metadata"]["schemaVersion"]

    if stored_version == 1:
        return deepcopy(normalized)

    adapted = deepcopy(normalized)

    measurements = adapted["payload"].pop("measurements")

    adapted["payload"].update(measurements)

    adapted["metadata"]["schemaVersion"] = 1

    return adapted