# Agent JSON Rules

Use these rules when creating or revising simulator JSON.

## Required

- Output valid simulator JSON with `settings`, `nodes`, `connections`, and optional
  `actions`.
- Name every node and connection with `params.name`.
- Use the exact component names requested by the requirements spec.
- Use SI units:
  - pressure: Pa
  - temperature: K
  - volume for `Node.V`: liters
  - `CdA`: m^2
- For `Node`, prefer `fluid`, `P`, `V`, and `T`.
- Set each connection direction from upstream source to downstream sink:
  `start_id` -> `end_id`.

## Node vs Tank

- Use `Node` by default for simple pressurized reservoirs, bottles, feed sources,
  and sinks.
- Use `Tank` only when modeling liquid plus ullage behavior.
- `Tank` does not accept simple `fluid`, `P`, `V`, `T` params.
- `Tank` requires `V_total_L`, `fluid_liq`, `m_liq`, `T_liq`, `fluid_ullage`,
  `P_ullage`, `T_ullage`, and `name`.
- For kerosene-like liquid fuel in simulator `Tank` nodes, use `n-Dodecane`.
  Use engine `fuel: "Kerosene"` only inside `Engine` params.

## Layout

- Always include explicit `x` and `y` coordinates for every node.
- The rendered P&ID should read **top-down**. This is a visual layout rule:
  arrange the coordinates so the main process path moves from top to bottom.
- Put upstream/source components at lower `y` values and downstream/sink
  components at higher `y` values.
- Downstream flow should generally increase `y`. Avoid primary flows that read
  left-to-right.
- Use `x` only to separate parallel branches.
- Keep components in the same flow path roughly aligned vertically.
- Keep parallel branches side-by-side, then merge them lower in the diagram when
  the physical network merges.

## Do Not

- Do not rely on the UI auto-layout. It lays out graphs left-to-right.
- Do not use exact equality for numeric simulation checks.
- Do not tune by renaming components. Keep names stable and tune numeric values.
- Do not make finite node volumes extremely small.

## Revision Hints

- If final pressure is too high, increase downstream flow area (`CdA`).
- If final pressure is too low, decrease downstream flow area (`CdA`).
- If flow is zero, check pressure difference, connection direction, `normal_state`,
  and `CdA`.
- If the solver crashes, reduce `dt`, reduce aggressive `CdA`, or increase finite
  node volume.
