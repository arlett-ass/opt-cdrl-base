# ADR-007 — Migración versionada y compatibilidad documental

## Estado y alcance

Aceptado.

Este documento registra la decisión técnica del equipo para implementar M07:
versionado documental, migración compatible, coexistencia de consumidores,
rollback controlado e integración reproducible del flujo de verificación.

La solución se construye sobre M06 sin reemplazar ni reescribir su
implementación. Se reutilizan sus contratos existentes de coexistencia v1/v2,
validación, migración explícita, auditoría y recuperación.

El objetivo de M07 es demostrar una transición controlada donde:

- documentos v1 y v2 pueden coexistir durante la transición;
- consumidores antiguos pueden continuar leyendo datos;
- la migración v1→v2 conserva identidad y datos de negocio;
- repetir una migración no genera duplicados ni degradación;
- existe una estrategia de rollback probada con fixtures sintéticos;
- la verificación completa M01–M07 es reproducible.

M07 mantiene el contrato común del repositorio:

```bash
make setup
make verify
make run