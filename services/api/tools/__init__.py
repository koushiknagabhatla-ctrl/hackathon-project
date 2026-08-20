"""Auralis tool layer: signed manifests (registry) + sandbox twins (sandbox).

Nothing in here reaches the outside world. Every implementation mutates the
SQLite twin only; the gateway is the sole caller.
"""
