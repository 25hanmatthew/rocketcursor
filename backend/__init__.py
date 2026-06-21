"""Backend pipeline layers that turn a validated P&ID into a flight vehicle.

Layers (each its own subpackage):
  propulsion_package -- physicalize + package the validated fluid system
  vehicle_synthesis  -- generate the full airframe around the package
  flight             -- 6DOF flight via RocketPy adapter

The existing fluid-network solver stays at `simulator/` and is the source of
truth for thermofluids; these layers consume its outputs, never recompute them.
"""
