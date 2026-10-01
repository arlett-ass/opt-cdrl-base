"""Factories para resource/client. Lee el entorno del proceso, no archivos .env.

Por defecto usa localhost:8000. Cloud requiere DYNAMODB_LOCAL=false y
credenciales de AWS Academy mediante la cadena estándar de boto3.
Los valores sintéticos locales no son credenciales AWS y solo se envían a loopback.
"""

import os
import re

import boto3
from botocore.config import Config


class DynamoDBConfigurationError(ValueError):
    """Variable de entorno inválida."""


def get_table_name():
    name = os.environ.get("DYNAMODB_TABLE", "cdrl_events")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", name):
        raise DynamoDBConfigurationError("DYNAMODB_TABLE requiere 3–255 caracteres alfanuméricos, _, - o .")
    return name


def _options():
    mode = os.environ.get("DYNAMODB_LOCAL", "true").strip().lower()
    if mode not in ("true", "false"):
        raise DynamoDBConfigurationError("DYNAMODB_LOCAL debe ser true o false.")
    region = os.environ.get("AWS_REGION", "us-east-1").strip()
    if not region:
        raise DynamoDBConfigurationError("AWS_REGION no puede estar vacía.")
    options = {
        "region_name": region,
        "config": Config(
            connect_timeout=3, read_timeout=10,
            retries={"mode": "standard", "total_max_attempts": 3},
            ignore_configured_endpoint_urls=True,
        ),
    }
    if mode == "true":
        raw_port = os.environ.get("DYNAMODB_PORT", "8000")
        if not re.fullmatch(r"[0-9]{1,5}", raw_port) or not 1 <= int(raw_port) <= 65535:
            raise DynamoDBConfigurationError("DYNAMODB_PORT debe estar entre 1 y 65535.")
        options.update(
            endpoint_url=f"http://127.0.0.1:{int(raw_port)}",
            aws_access_key_id="DUMMYLOCAL",
            aws_secret_access_key="DUMMYLOCAL",
            aws_session_token="",
        )
    return options


def get_dynamodb_client():
    """Cliente de bajo nivel para create_table/describe_table."""
    return boto3.session.Session().client("dynamodb", **_options())


def get_dynamodb_resource():
    """Resource de alto nivel: acepta los Decimal de validate_event."""
    return boto3.session.Session().resource("dynamodb", **_options())


def get_table():
    """Devuelve Table sin crear infraestructura ni consultar AWS al importar."""
    return get_dynamodb_resource().Table(get_table_name())
