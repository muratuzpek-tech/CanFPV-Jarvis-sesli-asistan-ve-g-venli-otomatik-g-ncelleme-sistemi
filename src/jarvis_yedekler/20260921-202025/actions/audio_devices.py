"""Shared audio-device discovery and preference resolution.

PortAudio device numbers are session-local identifiers. Preferences therefore
store a human-readable name plus host API and direction, and are resolved
against the *current* device list before a stream is opened. A legacy
name-only preference is accepted only when it identifies exactly one current
candidate; duplicate names are deliberately not guessed.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

from jarvis.paths import config_dir

logger = logging.getLogger(__name__)

EXCLUDE: tuple[str, ...] = (
    "cable",
    "ses eşleştiricisi",
    "sound mapper",
    "mapper",
    "vb-audio",
)
_UNSUPPORTED_HOSTAPIS: tuple[str, ...] = ("wdm-ks",)
_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "input": ("mikrofon", "microphone"),
    "output": ("hoparlör", "speaker", "kulaklık", "headphone", "realtek"),
}
_CHANNEL_KEY: dict[str, str] = {
    "input": "max_input_channels",
    "output": "max_output_channels",
}


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR: Path = _get_base_dir()
# Kept as an override hook for old callers/tests; default reads/writes never
# use this package path. _prefs_path() resolves JARVIS_HOME dynamically.
PREFS_PATH: Path | None = None


def _prefs_path() -> Path:
    return Path(PREFS_PATH) if PREFS_PATH is not None else config_dir() / "audio_prefs.json"


def _as_int(value: Any) -> int | None:
    """Convert numeric PortAudio fields without turning valid 0 into -1."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _channel_count(device: dict[str, Any], kind: str) -> int:
    number = _as_int(device.get(_CHANNEL_KEY[kind], 0))
    return max(number or 0, 0)


def _hostapi_name(hostapi_index: int | None, hostapi_cache: dict[int, str]) -> str:
    """Read a host API name without turning valid index 0 into -1."""
    key = hostapi_index if hostapi_index is not None else -1
    if key in hostapi_cache:
        return hostapi_cache[key]
    try:
        import sounddevice as sd

        name = str(sd.query_hostapis(key).get("name", "")).strip().lower()
    except Exception:
        name = ""
    hostapi_cache[key] = name
    return name


def get_audio_prefs() -> dict[str, Any]:
    """Load preferences safely; malformed values fall back to auto-selection."""
    path = _prefs_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        logger.debug("[AudioDevices] preference file unreadable (%s): %s", path, type(exc).__name__)
        return {}
    return data if isinstance(data, dict) else {}


def _remove_pref_fields(prefs: dict[str, Any], kind: str) -> None:
    for key in (
        f"{kind}_device_name",
        f"{kind}_device_hostapi",
        f"{kind}_device_direction",
        f"{kind}_device_id",
        f"{kind}_device",
        f"{kind}_device_identity",
    ):
        prefs.pop(key, None)


def set_audio_prefs(
    input_device_name: str | None = None,
    output_device_name: str | None = None,
    *,
    input_device_hostapi: int | str | None = None,
    output_device_hostapi: int | str | None = None,
    input_device_id: int | None = None,
    output_device_id: int | None = None,
) -> None:
    """Update audio preferences atomically while preserving old call shapes.

    ``None`` for a name means leave that direction unchanged; an empty string
    clears it. Optional host API and numeric ID fields let enumerating callers
    persist a composite identity. Numeric IDs are never used alone to resolve
    a device. Invalid name values are ignored rather than reaching ``lower``.
    """
    prefs = get_audio_prefs()
    for kind, name, hostapi, device_id in (
        ("input", input_device_name, input_device_hostapi, input_device_id),
        ("output", output_device_name, output_device_hostapi, output_device_id),
    ):
        if name is None:
            continue
        if name == "":
            _remove_pref_fields(prefs, kind)
            continue
        if not isinstance(name, str) or not name.strip():
            logger.warning("[AudioDevices] ignored malformed %s preference", kind)
            continue
        prefs[f"{kind}_device_name"] = name.strip()
        if hostapi is None:
            prefs.pop(f"{kind}_device_hostapi", None)
        else:
            prefs[f"{kind}_device_hostapi"] = hostapi
        prefs[f"{kind}_device_direction"] = kind
        numeric_id = _as_int(device_id)
        if numeric_id is not None:
            prefs[f"{kind}_device_id"] = numeric_id
        else:
            prefs.pop(f"{kind}_device_id", None)

    path = _prefs_path()
    temp_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8", suffix=".tmp"
        ) as tmp:
            json.dump(prefs, tmp, ensure_ascii=False, indent=2)
            temp_name = tmp.name
        Path(temp_name).replace(path)
    except (OSError, TypeError, ValueError) as exc:
        logger.error("[AudioDevices] preferences could not be saved (%s): %s", path, type(exc).__name__)
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def set_audio_device_pref(
    kind: Literal["input", "output"] | str,
    *,
    name: str,
    hostapi: int | str | None = None,
    device_id: int | None = None,
) -> None:
    """Persist a composite preference for a current enumerated device."""
    if kind not in _CHANNEL_KEY:
        raise ValueError(f"Invalid audio direction: {kind!r}")
    kwargs: dict[str, Any] = {
        f"{kind}_device_name": name,
        f"{kind}_device_hostapi": hostapi,
        f"{kind}_device_id": device_id,
    }
    set_audio_prefs(**kwargs)


def list_devices() -> list[dict[str, Any]]:
    """Return the current PortAudio device list, or [] if unavailable."""
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        return list(devices) if devices is not None else []
    except Exception as exc:
        logger.warning("[AudioDevices] device list unavailable: %s", type(exc).__name__)
        return []


def _device_info(kind: str, index: int, devices: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(devices):
        return None
    device = devices[index]
    if not isinstance(device, dict) or _channel_count(device, kind) <= 0:
        return None
    hostapi = _as_int(device.get("hostapi"))
    name = str(device.get("name", "")).strip()
    return {
        "index": index,
        "name": name,
        "name_lower": name.casefold(),
        "hostapi": hostapi,
        "direction": kind,
    }


def device_identity(kind: Literal["input", "output"] | str, index: int) -> dict[str, Any] | None:
    """Capture the current name/host API/direction identity for numeric ID."""
    if kind not in _CHANNEL_KEY:
        raise ValueError(f"Invalid kind: {kind!r}")
    return _device_info(kind, index, list_devices())


def resolve_device_index(
    kind: Literal["input", "output"] | str,
    identity: dict[str, Any] | None,
) -> int | None:
    """Resolve a captured identity against the latest PortAudio enumeration.

    The result is a numeric PortAudio ID suitable for ``InputStream`` or
    ``RawOutputStream``. Bare names and stale numeric IDs are never returned.
    An ambiguous current identity is rejected rather than choosing the first.
    """
    if kind not in _CHANNEL_KEY or not isinstance(identity, dict):
        return None
    name = identity.get("name")
    hostapi = _as_int(identity.get("hostapi"))
    direction = identity.get("direction")
    if not isinstance(name, str) or not isinstance(direction, str) or direction != kind:
        return None
    matches: list[int] = []
    for index, device in enumerate(list_devices()):
        if not isinstance(device, dict) or _channel_count(device, kind) <= 0:
            continue
        current_hostapi = _as_int(device.get("hostapi"))
        current_name = str(device.get("name", "")).strip()
        if current_name.casefold() == name.strip().casefold() and current_hostapi == hostapi:
            matches.append(index)
    return matches[0] if len(matches) == 1 else None


def device_name(index: int | None) -> str:
    """Return a display name for a current numeric ID."""
    if index is None:
        return "Sistem varsayılanı"
    if not isinstance(index, int) or isinstance(index, bool):
        return f"#{index}"
    devices = list_devices()
    if 0 <= index < len(devices):
        try:
            return str(devices[index].get("name", f"#{index}"))
        except Exception:
            pass
    return f"#{index}"


def _preference(prefs: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """Normalize modern and legacy preference shapes without trusting types."""
    nested = prefs.get(f"{kind}_device")
    if not isinstance(nested, dict):
        nested = prefs.get(f"{kind}_device_identity")
    if not isinstance(nested, dict):
        nested = {}
    name = nested.get("name", prefs.get(f"{kind}_device_name"))
    if not isinstance(name, str) or not name.strip():
        return None
    hostapi = nested.get("hostapi", prefs.get(f"{kind}_device_hostapi"))
    direction = nested.get("direction", prefs.get(f"{kind}_device_direction", kind))
    if not isinstance(direction, str):
        direction = kind
    return {
        "name": name.strip().casefold(),
        "hostapi": hostapi,
        "direction": direction.strip().casefold(),
    }


def _hostapi_matches(pref_value: Any, index: int | None, hostapi_name: str) -> bool:
    if pref_value is None or pref_value == "":
        return True
    pref_index = _as_int(pref_value)
    if pref_index is not None:
        return index == pref_index
    return str(pref_value).strip().casefold() == hostapi_name.casefold()


def _default_index(kind: str, devices: list[dict[str, Any]]) -> int | None:
    """Return a valid numeric PortAudio default, never an unchecked None."""
    try:
        import sounddevice as sd

        raw = getattr(getattr(sd, "default", None), "device", None)
        if isinstance(raw, (tuple, list)):
            position = 0 if kind == "input" else 1
            index = _as_int(raw[position]) if len(raw) > position else None
        else:
            index = _as_int(raw)
        if index is not None and 0 <= index < len(devices) and _channel_count(devices[index], kind) > 0:
            return index
    except Exception:
        pass
    return None


def candidates_with_tier(kind: Literal["input", "output"] | str) -> list[tuple[int | None, str]]:
    """Return current numeric candidates in preference order.

    No fabricated ``None`` candidate is returned for an empty or invalid
    device list. The system default is represented by its current numeric ID
    only after it is verified to exist and support the requested direction.
    """
    if kind not in _CHANNEL_KEY:
        raise ValueError(f"Invalid kind: {kind!r}; expected 'input' or 'output'.")

    devices = list_devices()
    hostapi_cache: dict[int, str] = {}
    infos: list[dict[str, Any]] = []
    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        hostapi = _as_int(device.get("hostapi"))
        hostapi_name = _hostapi_name(hostapi, hostapi_cache)
        name = str(device.get("name", "")).strip()
        infos.append(
            {
                "index": index,
                "channels": _channel_count(device, kind),
                "name": name,
                "name_lower": name.casefold(),
                "hostapi": hostapi,
                "hostapi_name": hostapi_name,
                "unsupported": any(marker in hostapi_name for marker in _UNSUPPORTED_HOSTAPIS),
            }
        )

    result: list[tuple[int | None, str]] = []
    seen: set[int] = set()

    def add(info: dict[str, Any], tier: str) -> None:
        index = info["index"]
        if index not in seen:
            seen.add(index)
            result.append((index, tier))

    pref = _preference(get_audio_prefs(), kind)
    if pref and pref["direction"] in (kind, "", "all"):
        matches = [
            info
            for info in infos
            if info["channels"] > 0
            and info["name_lower"] == pref["name"]
            and _hostapi_matches(pref["hostapi"], info["hostapi"], info["hostapi_name"])
        ]
        if len(matches) == 1:
            add(matches[0], "preference")

    usable = [info for info in infos if info["channels"] > 0]
    supported = [info for info in usable if not info["unsupported"]]
    hints = _NAME_HINTS[kind]
    for info in supported:
        if any(hint in info["name_lower"] for hint in hints) and not any(
            marker in info["name_lower"] for marker in EXCLUDE
        ):
            add(info, "named")
    for info in supported:
        if not any(marker in info["name_lower"] for marker in EXCLUDE):
            add(info, "preferred")
    for info in supported:
        add(info, "fallback_excluded")
    for info in usable:
        if info["unsupported"]:
            add(info, "hostapi_unsupported")

    default_index = _default_index(kind, devices)
    if default_index is not None:
        for info in infos:
            if info["index"] == default_index:
                add(info, "system_default")
                break
    return result


def best_candidate(kind: Literal["input", "output"] | str) -> tuple[int | None, str]:
    """Return the best current candidate, or an explicit no-device result."""
    candidates = candidates_with_tier(kind)
    return candidates[0] if candidates else (None, "no_device")


def get_candidates(kind: Literal["input", "output"] | str) -> list[int]:
    """Return only current numeric IDs for stream-opening code."""
    return [index for index, _tier in candidates_with_tier(kind) if isinstance(index, int)]
