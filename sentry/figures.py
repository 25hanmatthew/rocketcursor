"""Render reference figures for sentry/README.md from the actual instrumentation.

These are code-derived *illustrations* of what RocketCursor's Sentry events look
like — the component tags, the captured context keys, and the capture sites are
read straight from loop/monitoring.py and ui/backend/app.py. They are NOT live
dashboard captures; the running org is the source of truth (use _sentry_smoke.py
with a real SENTRY_DSN to populate it, then screenshot).

    python sentry/figures.py    ->  sentry/sentry-issues.png, sentry/sentry-event.png
"""

from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = os.path.dirname(os.path.abspath(__file__))

BG = "#16121f"
CARD = "#221b30"
CARD2 = "#1c1628"
LINE = "#352b48"
TXT = "#e9e4f5"
SUB = "#9a8fb3"
ACCENT = "#a684ff"
ERR = "#f06a6a"

# component tag -> chip color (the five init_sentry() entry points)
COMPONENTS = {
    "ui-backend": "#5b8def",
    "loop": "#a684ff",
    "designer-agent": "#39c0a8",
    "simulator-agent": "#e0a13a",
    "multiagent": "#d56bb3",
}


def _chip(ax, x, y, label, color, w=None):
    w = w if w is not None else 0.0088 * len(label) + 0.013
    ax.add_patch(FancyBboxPatch((x, y - 0.018), w, 0.036, boxstyle="round,pad=0.004,rounding_size=0.02",
                                facecolor=color + "33", edgecolor=color, linewidth=1.0, transform=ax.transAxes))
    ax.text(x + w / 2, y, label, color=color, fontsize=8.5, ha="center", va="center",
            family="monospace", transform=ax.transAxes)
    return w


def _panel(title, subtitle):
    fig = plt.figure(figsize=(11, 6.4), dpi=130)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    # header bar
    ax.add_patch(FancyBboxPatch((0.03, 0.9), 0.94, 0.07, boxstyle="round,pad=0.002,rounding_size=0.01",
                                facecolor=CARD, edgecolor=LINE, transform=ax.transAxes))
    ax.text(0.05, 0.935, title, color=TXT, fontsize=15, fontweight="bold", va="center", transform=ax.transAxes)
    ax.text(0.95, 0.935, subtitle, color=SUB, fontsize=10, va="center", ha="right",
            family="monospace", transform=ax.transAxes)
    return fig, ax


def render_issues():
    """Issue stream, grouped by the `component` tag every process sets."""
    fig, ax = _panel("Sentry  ·  Issues", "project: rocketcursor")
    # filter row
    ax.text(0.05, 0.86, "is:unresolved    group-by:", color=SUB, fontsize=9.5, family="monospace",
            va="center", transform=ax.transAxes)
    _chip(ax, 0.235, 0.86, "component", ACCENT)

    rows = [
        ("ui-backend", "RuntimeError: rocketcea is required to instantiate Engine nodes",
         "simulator.general_fluid_network · stage=design-loop-background", "14"),
        ("ui-backend", "HTTPException(400): Flight pipeline failed",
         "POST /api/design-runs/{id}/flight", "6"),
        ("loop", "NetworkConfigError: connection references unknown node id",
         "simulator.network_io.load_network_config", "9"),
        ("simulator-agent", "TimeoutError: simulator step exceeded compute budget",
         "loop.simulator_service.handle_request", "3"),
        ("designer-agent", "APIStatusError: tool_use call timed out",
         "loop.service.designer", "5"),
        ("ui-backend", "RuntimeError: supplier portal RFQ parking failed",
         "tools.procurement · stage=procurement", "2"),
    ]
    y = 0.79
    for comp, title, culprit, count in rows:
        h = 0.105
        ax.add_patch(FancyBboxPatch((0.03, y - h + 0.012), 0.94, h - 0.016,
                                    boxstyle="round,pad=0.002,rounding_size=0.008",
                                    facecolor=CARD2, edgecolor=LINE, linewidth=1.0, transform=ax.transAxes))
        ax.text(0.055, y - 0.02, title, color=TXT, fontsize=11, fontweight="bold", va="center", transform=ax.transAxes)
        ax.text(0.055, y - 0.058, culprit, color=SUB, fontsize=9, family="monospace", va="center", transform=ax.transAxes)
        _chip(ax, 0.055, y - 0.092 + 0.004, comp, COMPONENTS[comp])
        ax.text(0.90, y - 0.02, "error", color=ERR, fontsize=9, ha="center", va="center",
                family="monospace", transform=ax.transAxes)
        ax.text(0.945, y - 0.02, f"{count} ev", color=SUB, fontsize=9, ha="center", va="center",
                family="monospace", transform=ax.transAxes)
        y -= h
    fig.savefig(os.path.join(OUT, "sentry-issues.png"), facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def render_event():
    """Anatomy of one captured event — the design-loop background-thread crash
    (ui/backend/app.py:408), the richest contextual capture in the code."""
    fig, ax = _panel("RuntimeError", "ui/backend/app.py:408")
    ax.text(0.05, 0.845, "rocketcea is required to instantiate Engine nodes",
            color=TXT, fontsize=12.5, va="center", transform=ax.transAxes)
    ax.text(0.05, 0.80, "captured via loop.monitoring.capture() in the background design-loop thread "
            "(FastAPI's hook can't see off-request crashes)", color=SUB, fontsize=9, va="center", transform=ax.transAxes)

    # TAGS
    ax.text(0.05, 0.73, "TAGS", color=ACCENT, fontsize=10, fontweight="bold", family="monospace",
            va="center", transform=ax.transAxes)
    x = 0.05
    for label, color in [("component=ui-backend", COMPONENTS["ui-backend"]),
                         ("project=rocketcursor", ACCENT),
                         ("environment=hackathon", "#7a8a9a"),
                         ("level=error", ERR)]:
        x += _chip(ax, x, 0.685, label, color) + 0.012

    # ADDITIONAL DATA (the **context kwargs passed to capture())
    ax.text(0.05, 0.61, "ADDITIONAL DATA", color=ACCENT, fontsize=10, fontweight="bold",
            family="monospace", va="center", transform=ax.transAxes)
    ax.add_patch(FancyBboxPatch((0.05, 0.40), 0.90, 0.18, boxstyle="round,pad=0.004,rounding_size=0.008",
                                facecolor=CARD2, edgecolor=LINE, transform=ax.transAxes))
    kv = [
        ("session_id", "7b0cd603eaf04f0caf82cb6a5db105c7"),
        ("request", '"Design a simple pressure fed fluid system ... kerosene and lox ..."'),
        ("stage", "design-loop-background"),
    ]
    yy = 0.545
    for k, v in kv:
        ax.text(0.07, yy, k, color=SUB, fontsize=10, family="monospace", va="center", transform=ax.transAxes)
        ax.text(0.25, yy, v, color=TXT, fontsize=10, family="monospace", va="center", transform=ax.transAxes)
        yy -= 0.052

    # TRACEBACK (representative)
    ax.text(0.05, 0.345, "TRACEBACK", color=ACCENT, fontsize=10, fontweight="bold",
            family="monospace", va="center", transform=ax.transAxes)
    ax.add_patch(FancyBboxPatch((0.05, 0.06), 0.90, 0.26, boxstyle="round,pad=0.004,rounding_size=0.008",
                                facecolor="#120e1a", edgecolor=LINE, transform=ax.transAxes))
    tb = [
        'loop/agent.py  run_loop()  -> result = run_design(design, iter_dir)',
        'loop/simulator_adapter.py  run_design()  -> loaded = load_network_config(path)',
        'simulator/network_io.py  _instantiate_loaded_network()',
        'simulator/general_fluid_network.py  Engine.__init__()  -> cea = _get_cea_obj()',
        'RuntimeError: rocketcea is required to instantiate Engine nodes.',
    ]
    yy = 0.29
    for i, line in enumerate(tb):
        c = ERR if line.startswith("RuntimeError") else "#c7bce0"
        ax.text(0.07, yy, line, color=c, fontsize=8.6, family="monospace", va="center", transform=ax.transAxes)
        yy -= 0.045
    fig.savefig(os.path.join(OUT, "sentry-event.png"), facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


if __name__ == "__main__":
    render_issues()
    render_event()
    print("wrote", os.path.join(OUT, "sentry-issues.png"))
    print("wrote", os.path.join(OUT, "sentry-event.png"))
