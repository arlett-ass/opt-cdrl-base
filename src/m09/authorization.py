"""Contextos de identidad emitidos por el servidor y decisión RBAC pura.

IdentityRegistry se construye con asignaciones de un administrador. Solo el
adaptador de autenticación del servidor puede llamar a
identity_for_verified_subject(), después de verificar el sujeto. En pruebas
ese sujeto es sintético. Nunca conectar este método a un actorId/rol recibido
del cliente: aquí no se implementan contraseñas, sesiones ni autenticación AWS.

La interfaz CRUD acepta únicamente el objeto opaco emitido por SU registro.
Un dict, nombre de rol, objeto fabricado o contexto de otro registro no concede
permisos. El proceso Python y sus dependencias se consideran confiables; esta
capa no aísla código hostil con acceso a memoria, credenciales o módulos M05.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType

from .policy import ACTIONS, AUDIT, EVENTS, ROLES, is_allowed


class IdentityContext:
    """Referencia opaca. Construir una por cuenta propia no la hace confiable."""

    __slots__ = ()


@dataclass(frozen=True)
class _Principal:
    subject: str
    role: str


class IdentityRegistry:
    """Registro inmutable de configuración confiable; no recibe roles por petición."""

    def __init__(self, assignments):
        if not isinstance(assignments, Mapping):
            raise TypeError("assignments requiere un mapping configurado por el servidor.")
        by_subject, principals = {}, {}
        for subject, role in assignments.items():
            if type(subject) is not str or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}", subject,
            ):
                raise ValueError("El sujeto requiere un identificador técnico válido.")
            if type(role) is not str or role not in ROLES:
                raise ValueError("Rol no declarado en la política M09.")
            identity = IdentityContext()
            by_subject[subject] = identity
            principals[identity] = _Principal(subject, role)
        self._by_subject = MappingProxyType(by_subject)
        self._principals = MappingProxyType(principals)

    def identity_for_verified_subject(self, subject):
        """Solo servidor: resuelve un sujeto YA autenticado; desconocido -> None."""
        if type(subject) is not str:
            return None
        return self._by_subject.get(subject)

    def _principal(self, identity):
        if type(identity) is not IdentityContext:
            return None
        return self._principals.get(identity)


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    actor_id: str
    role: str
    action: str
    resource: str
    reason: str


def authorize(registry, identity, action, resource):
    """Calcula una decisión sin I/O. SecureOperations la audita antes del CRUD."""
    if type(registry) is not IdentityRegistry:
        raise TypeError("Se requiere el registro de identidades del servidor.")
    principal = registry._principal(identity)
    safe_action = action if type(action) is str and action in ACTIONS else "unknown"
    safe_resource = resource if type(resource) is str and resource in (EVENTS, AUDIT) else "unknown"
    allowed = principal is not None and is_allowed(principal.role, action, resource)
    return AuthorizationDecision(
        allowed=allowed,
        actor_id=principal.subject if principal is not None else "unknown",
        role=principal.role if principal is not None else "unknown",
        action=safe_action,
        resource=safe_resource,
        reason="allowed" if allowed else (
            "untrusted_identity" if principal is None else "permission_denied"
        ),
    )
