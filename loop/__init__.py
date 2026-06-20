"""Design -> simulate -> evaluate -> revise loop for fluid-network designs.

The loop is the spine of the product:

    requirements.json
          |
          v
    Claude designs design.json        (agent.py)
          |
          v
    simulator_adapter.run(design)      (simulator_adapter.py)
          |
          v
    simulation_result                  (validate / run / export / classify)
          |
          v
    evaluator.evaluate(spec, result)   (evaluator.py -- PURE PYTHON, no LLM)
          |
          v
    verdict  --> Claude revises --> repeat

Design principle: the *verdict* is produced by deterministic Python, never by
Claude. Claude designs and revises; Python decides pass/fail. That keeps the
loop reproducible and auditable.
"""
