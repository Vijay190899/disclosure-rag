"""Run the M0 probe.

    uv run python -m spikes.esef_probe                  # all stages
    uv run python -m spikes.esef_probe --stage facts    # one stage

Stages share state through work/, so they can be rerun individually while
iterating. Geometry needs facts (it renders the stamped report), and narrative
needs geometry (it excludes tagged regions).
"""

from __future__ import annotations

import argparse

STAGES = ("fetch", "facts", "geometry", "narrative", "report")


def main() -> int:
    parser = argparse.ArgumentParser(prog="spikes.esef_probe", description=__doc__)
    parser.add_argument("--stage", choices=STAGES, help="run a single stage")
    args = parser.parse_args()

    stages = (args.stage,) if args.stage else STAGES

    for stage in stages:
        print(f"\n=== {stage} ===")
        if stage == "fetch":
            from . import fetch

            fetch.run()
        elif stage == "facts":
            from . import facts

            facts.run()
        elif stage == "geometry":
            from . import geometry

            geometry.run()
        elif stage == "narrative":
            from . import narrative

            narrative.run()
        elif stage == "report":
            from . import report

            report.run()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
