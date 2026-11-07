"""Write shared/protocol/schema.json from the Pydantic models."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.protocol import Protocol  # noqa: E402

SCHEMA_PATH = ROOT / "shared" / "protocol" / "schema.json"


def render_schema() -> str:
    # Serialization mode marks defaulted fields as required, so the `type` discriminators
    # stay non-optional in the generated TypeScript and unions narrow correctly.
    schema = Protocol.model_json_schema(mode="serialization")
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    with SCHEMA_PATH.open("w", encoding="utf-8", newline="\n") as file:
        file.write(render_schema())
