from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from marketimmune.scenarios.config import ScenarioConfig
from marketimmune.scenarios.generator import AGENT_REGISTRY, generate_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic phase-5 scenarios.")
    parser.add_argument("--output-dir", default="reports/phase5/scenarios")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--count", type=int, default=600)
    parser.add_argument("--events-per-scenario", type=int, default=30)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for pattern in ("*_events.json", "*_labels.json", "*_manifest.json", "scenario_index.json"):
            for path in output_dir.glob(pattern):
                path.unlink()
    families = list(AGENT_REGISTRY)
    manifests: list[dict[str, object]] = []
    for index in range(args.count):
        family = families[index % len(families)]
        unsafe = (index // len(families)) % 2 == 1
        variant = "unsafe" if unsafe else "benign"
        config = ScenarioConfig(
            scenario_id=f"scenario-{index:03d}-{family}-{variant}",
            family=family,
            seed=args.seed + index,
            start=datetime(2024, 5, 1, tzinfo=UTC),
            mid_price=65000 + index,
            event_count=args.events_per_scenario,
            unsafe=unsafe,
        )
        scenario = generate_scenario(config)
        scenario.write(output_dir)
        manifests.append(scenario.manifest())
    (output_dir / "scenario_index.json").write_text(
        json.dumps(manifests, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"scenario_count": len(manifests), "output_dir": str(output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
