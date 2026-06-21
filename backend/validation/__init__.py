"""Phase 6 -- independent validation of a synthesized vehicle + its flight.

Two complementary checks, both independent of the single nominal flight:
  design_rules -- deterministic engineering rules (stability, T/W, rail-exit
                  velocity, mission-constraint fit, apogee-vs-target)
  monte_carlo  -- RocketPy dispersion over wind / mass / thrust to report apogee
                  and landing scatter, i.e. uncertainty rather than a point value

The OpenRocket exporter (a second, external opinion on geometry/stability) lives
at backend/flight/adapters/openrocket_exporter.py.

Entry point: `run_validation.validate_run`.
"""

from backend.validation.design_rules import check_design_rules

__all__ = ["check_design_rules"]
