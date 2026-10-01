"""Inicialización idempotente: python -m src.m05.table_setup.

No altera ni borra una tabla existente incompatible. Los GSIs proyectan ALL
para devolver documentos completos; sus lecturas son eventualmente consistentes.
"""

import json
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from .dynamodb_client import (
    DynamoDBConfigurationError, get_dynamodb_client, get_table_name,
)

INDEX_KEYS = {
    "type-timestamp-index": "type",
    "source-timestamp-index": "source",
}


class TableSchemaError(RuntimeError):
    """La infraestructura existente no corresponde al contrato M05."""


def _key_map(schema):
    return {key["KeyType"]: key["AttributeName"] for key in schema}


def _check_schema(table):
    if _key_map(table.get("KeySchema", [])) != {"HASH": "eventId"}:
        raise TableSchemaError("La tabla requiere únicamente eventId como partition key.")
    attributes = {a["AttributeName"]: a["AttributeType"] for a in table.get("AttributeDefinitions", [])}
    if attributes != {"eventId": "S", "type": "S", "source": "S", "timestamp": "S"}:
        raise TableSchemaError("Los cuatro atributos de claves deben ser String.")
    if table.get("LocalSecondaryIndexes"):
        raise TableSchemaError("El contrato M05 no incluye índices locales.")
    indexes = {i["IndexName"]: i for i in table.get("GlobalSecondaryIndexes", [])}
    if set(indexes) != set(INDEX_KEYS):
        raise TableSchemaError("Se requieren exactamente type-timestamp-index y source-timestamp-index.")
    for name, partition in INDEX_KEYS.items():
        index = indexes[name]
        if _key_map(index.get("KeySchema", [])) != {"HASH": partition, "RANGE": "timestamp"}:
            raise TableSchemaError(f"Claves incorrectas para {name}.")
        if index.get("Projection", {}).get("ProjectionType") != "ALL":
            raise TableSchemaError(f"{name} requiere proyección ALL.")


def ensure_table(client=None, table_name=None, *, attempts=60, poll_seconds=1):
    """Crea si falta, espera tabla/GSIs ACTIVE y devuelve su descripción.

    client/table_name inyectables permiten verificar sin afectar tablas ajenas.
    Los errores de autorización/conexión se propagan; no equivalen a ausencia.
    """
    if type(attempts) is not int or attempts < 1 or poll_seconds < 0:
        raise ValueError("attempts debe ser positivo y poll_seconds no negativo.")
    client = client if client is not None else get_dynamodb_client()
    name = table_name if table_name is not None else get_table_name()
    try:
        client.describe_table(TableName=name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        try:
            client.create_table(
                TableName=name,
                BillingMode="PAY_PER_REQUEST",
                AttributeDefinitions=[
                    {"AttributeName": field, "AttributeType": "S"}
                    for field in ("eventId", "type", "source", "timestamp")
                ],
                KeySchema=[{"AttributeName": "eventId", "KeyType": "HASH"}],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": index,
                        "KeySchema": [
                            {"AttributeName": partition, "KeyType": "HASH"},
                            {"AttributeName": "timestamp", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                    for index, partition in INDEX_KEYS.items()
                ],
            )
        except ClientError as exc:
            # Otro proceso pudo crear la tabla entre describe y create.
            if exc.response["Error"]["Code"] != "ResourceInUseException":
                raise
    for attempt in range(attempts):
        try:
            table = client.describe_table(TableName=name)["Table"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
        else:
            _check_schema(table)
            if table.get("TableStatus") == "ACTIVE" and all(
                i.get("IndexStatus") == "ACTIVE"
                for i in table["GlobalSecondaryIndexes"]
            ):
                return table
            if table.get("TableStatus") not in ("CREATING", "UPDATING", "ACTIVE"):
                raise TableSchemaError("La tabla no está disponible para M05.")
        if attempt + 1 < attempts:
            time.sleep(poll_seconds)
    raise TimeoutError(f"La tabla {name} y sus índices no alcanzaron ACTIVE.")


def main():
    try:
        table = ensure_table()
    except (BotoCoreError, ClientError, DynamoDBConfigurationError, TableSchemaError, TimeoutError) as exc:
        print(f"No se pudo preparar DynamoDB M05: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "table": table["TableName"], "status": table["TableStatus"],
        "indexes": sorted(i["IndexName"] for i in table["GlobalSecondaryIndexes"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
