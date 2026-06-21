"""Propulsion physicalization + packaging.

Turns a validated P&ID (NetworkConfig) and its thermofluid solution into a
physically sized, positioned propulsion package with mass/CG/inertia over time.

Entry point: `physicalizer.build_package`.
"""

from backend.propulsion_package.physicalizer import build_package

__all__ = ["build_package"]
