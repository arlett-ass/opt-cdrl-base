"""Matriz M09 cerrada; nombres conceptuales de M03, sin copiar sus GRANT.

Los recursos son nombres lógicos, no nombres de tabla enviados por el cliente.
Una tabla física se configura al construir el servicio en el servidor.
"""

from types import MappingProxyType


EVENTS = "cdrl_events"
AUDIT = "cdrl_audit_log"
ROLES = ("cdrl_reader", "cdrl_writer", "cdrl_operator", "cdrl_migrator")
ACTIONS = (
    "GetItem", "Query", "PutItem", "UpdateItem", "DeleteItem",
    "ReadOperationalSummary",
)

_PERMISSIONS = MappingProxyType({
    "cdrl_reader": frozenset({("GetItem", EVENTS), ("Query", EVENTS)}),
    "cdrl_writer": frozenset({("PutItem", EVENTS)}),
    "cdrl_operator": frozenset({("ReadOperationalSummary", EVENTS)}),
    "cdrl_migrator": frozenset(),
})


def is_allowed(role, action, resource):
    """Deniega toda combinación no declarada, incluso entradas mal formadas."""
    if any(type(value) is not str for value in (role, action, resource)):
        return False
    return (action, resource) in _PERMISSIONS.get(role, frozenset())
