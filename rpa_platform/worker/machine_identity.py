import json
import uuid
from datetime import datetime
from pathlib import Path


def load_or_create_machine_id(path: Path) -> str:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        machine_id = data.get("machine_id", "")
        if machine_id:
            return machine_id
    path.parent.mkdir(parents=True, exist_ok=True)
    machine_id = "mch_%s" % str(uuid.uuid4())
    path.write_text(
        json.dumps(
            {
                "machine_id": machine_id,
                "created_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return machine_id
