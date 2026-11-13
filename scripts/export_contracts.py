"""Export the authoritative Pydantic wire schema for the frontend generator."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from road_safety.contracts import ContractBundle  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = ROOT / "contracts" / "schema.json"
    content = json.dumps(ContractBundle.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            raise SystemExit("Contract schema is stale. Run python scripts/export_contracts.py")
    else:
        target.write_text(content, encoding="utf-8")
