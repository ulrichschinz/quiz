"""Reusable kernel: config, db, security, errors, logging.

Domain-agnostic by contract (import-linter: app.core must not import
app.domains / app.interfaces / app.contracts).
"""
