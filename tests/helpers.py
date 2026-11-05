import copy
import json
from pathlib import Path

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "fixtures.json").read_text(encoding="utf-8"))
CORRECT_D = {"sum": "o2", "product": "o2"}
CORRECT_Y = {"s1": True, "s2": False, "s3": True}


def fx(name):
    return copy.deepcopy(FIXTURES[name])
