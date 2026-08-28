# Enterprise Snowflake Data Project Framework

Versioned golden path for Snowflake data-project repositories.

## Purpose

Provide reusable technical behaviour once so Health, Transport and future projects do not copy/paste or independently reimplement the same engineering mechanics.

## This repository owns

- versioned dbt package and reusable macros
- generic tests
- approved load-strategy implementations
- SCD2 mechanics
- reconciliation and freshness framework
- audit and operational metadata contracts
- project/dataset metadata schemas and validation
- reusable GitHub Actions workflows
- rollback, recovery and backfill workflow templates
- project bootstrap/template capability
- framework pattern and operations documentation

## This repository does not own

- Health or Transport business rules
- project-specific RAW contracts
- source-system simulation
- central Snowflake account/RBAC/warehouse infrastructure
- environment-specific project business configuration

## Design rule

If fixing a shared technical behaviour would otherwise require manual edits in every data project, that behaviour probably belongs here.

Use metadata for stable technical behaviour and explicit SQL/code for genuine domain logic. Support `implementation: custom` without exempting custom implementations from standard testing, observability, reconciliation, audit and recovery.

## Consumption model

Projects consume released framework versions as dependencies and upgrade deliberately; they do not permanently copy the framework into each repository.

The canonical platform architecture is maintained in `enterprise-snowflake-platform-infra/docs/PROJECT_BLUEPRINT.md`.