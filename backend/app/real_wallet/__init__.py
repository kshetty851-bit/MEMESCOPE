"""Dedicated execution-wallet boundary.

This package has no transaction builder, Jupiter executor, Celery task, or
wallet funding capability.  It exists solely to keep future signing material
out of every product subsystem until a separately approved live-execution
release.
"""
