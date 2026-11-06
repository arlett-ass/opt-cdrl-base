"""M09 de Víctor: autorización local, CRUD protegido y contrato de auditoría.

El sink durable de Angélica y el verificador/ADR de David se integran aparte.
"""

from .authorization import (
    AuthorizationDecision, IdentityContext, IdentityRegistry, authorize,
)
from .policy import ACTIONS, AUDIT, EVENTS, ROLES, is_allowed
from .secure_operations import AccessDeniedError, AuditUnavailableError, SecureOperations

__all__ = [
    "ACTIONS", "AUDIT", "EVENTS", "ROLES", "AccessDeniedError",
    "AuditUnavailableError", "AuthorizationDecision", "IdentityContext",
    "IdentityRegistry", "SecureOperations", "authorize", "is_allowed",
]
