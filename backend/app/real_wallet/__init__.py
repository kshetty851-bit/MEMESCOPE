"""Dedicated execution-wallet boundary.

This package has no production transaction builder, Celery task, wallet
funding capability, or network-capable execution path. Test-only lifecycle
adapters are injected by regression tests and reject all external Jupiter
endpoints. It exists to keep future signing material out of every product
subsystem until a separately approved live-execution release.
"""
