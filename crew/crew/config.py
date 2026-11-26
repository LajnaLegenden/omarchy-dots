import re
import tomllib

from crew.errors import UsageError
from crew.paths import get_config_path

DEFAULT_SLOTS = {
    "build": {"max": 2, "min_free_mem": "6G"},
    "test": {"max": 2, "min_free_mem": "4G"},
    "heavy": {"max": 1, "min_free_mem": "0"},
}
UNKNOWN_SLOT = {"max": 1, "min_free_mem": "0"}
SIZE_UNITS = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def get_slot_config(name, max_override=None):
    path = get_config_path()
    configured = tomllib.loads(path.read_text()).get("slots", {}) if path.exists() else {}
    slot = {**UNKNOWN_SLOT, **DEFAULT_SLOTS.get(name, {}), **configured.get(name, {})}
    max_holders = max_override or int(slot["max"])
    if max_holders < 1:
        raise UsageError(f"slot {name}: max must be at least 1")
    return {"name": name, "max": max_holders, "min_free_mem": to_bytes(slot["min_free_mem"])}


def to_bytes(size):
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?)i?B?\s*", str(size).upper())
    if not match:
        raise UsageError(f"bad memory size {size!r} (use e.g. 6G)")
    number, unit = match.groups()
    return int(float(number) * SIZE_UNITS[unit])
