#!/usr/bin/env python3
"""Overnight release-readiness backbone for midvatten 2.0.

Runs the NON-Docker work (the full unit suite on Qt5, then every GUI mode on the
Qt5 host) sequentially so nothing contends with the Qt6-Docker subagents running
in parallel. Each step is timeboxed and logged; an aggregate report is rewritten
after every step so partial results survive a crash. Read report.md in the
morning.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path("/home/hsai1/dev/midv/midvatten/.worktrees/gui-test-pass")
OUT = ROOT / "test/gui/.overnight"
OUT.mkdir(parents=True, exist_ok=True)
ENV = {**os.environ, "PYTHONNOUSERSITE": "1"}  # host QGIS needs system numpy 1.x
results: list[dict] = []

GUI_MODES = ["coverage", "controls", "outputs", "fill", "loggereditor", "dbutils", "generic_actions"]


def write_report() -> None:
    (OUT / "report.json").write_text(json.dumps(results, indent=2))
    lines = ["# midvatten 2.0 overnight backbone (non-Docker: unit suite + Qt5 host)",
             f"_updated {datetime.datetime.now():%Y-%m-%d %H:%M:%S}_", ""]
    for r in results:
        mark = "PASS" if r["ok"] else ("TIMEOUT" if r["rc"] == "TIMEOUT" else "FAIL")
        lines.append(f"- **{mark}** `{r['name']}` (rc={r['rc']}, {r['secs']}s) — {r.get('note', '')}")
    (OUT / "report.md").write_text("\n".join(lines) + "\n")


def run(name: str, cmd: list[str], timeout: int, ok_rc=(0,)) -> None:
    log = OUT / f"{name}.log"
    t0 = time.time()
    rc: object
    with open(log, "w") as f:
        f.write("+ " + " ".join(cmd) + "\n\n")
        f.flush()
        try:
            rc = subprocess.run(cmd, cwd=ROOT, env=ENV, stdout=f,
                                stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            rc = "TIMEOUT"
        except Exception as e:  # never let one step kill the battery
            f.write(f"\nrunner exception: {e}\n")
            rc = "ERROR"
    results.append({"name": name, "rc": rc, "ok": rc in ok_rc,
                    "secs": round(time.time() - t0), "log": str(log)})
    write_report()


def main() -> None:
    # 1. The comprehensive existing net: full unit suite (Qt5). Biggest single signal.
    run("unit_suite_qt5", ["python3", "-m", "pytest", "test/", "-q", "--no-header",
                           "-p", "no:cacheprovider"], timeout=4200)

    # 2. Every GUI mode on the Qt5 host (the Qt6 modes are covered by a subagent in Docker).
    for mode in GUI_MODES:
        run(f"qt5host_{mode}",
            ["python3", "test/gui/run_gui_tests.py", "--mode", mode, "--host",
             "--out", str(OUT / f"qt5host_{mode}"), "--timeout", "600"],
            timeout=800)

    write_report()
    print("overnight backbone done:", OUT / "report.md")


if __name__ == "__main__":
    main()
