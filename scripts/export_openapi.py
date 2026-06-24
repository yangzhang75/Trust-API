"""Export the FastAPI OpenAPI schema to docs/openapi.json.

Run via `make openapi`. Keeps the committed schema in sync with the code
so reviewers can diff the API contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from trust_api.config import Settings
from trust_api.main import create_app

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "openapi.json"


def main() -> None:
    app = create_app(Settings(api_keys="export-placeholder"))
    schema = app.openapi()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
