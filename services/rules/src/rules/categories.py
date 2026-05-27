import json
from enum import Enum
from pathlib import Path

_SHARED = Path(__file__).resolve().parent.parent.parent.parent.parent / "shared" / "categories.json"
_names = json.loads(_SHARED.read_text())

TransactionCategory = Enum("TransactionCategory", {c: c for c in _names}, type=str)
