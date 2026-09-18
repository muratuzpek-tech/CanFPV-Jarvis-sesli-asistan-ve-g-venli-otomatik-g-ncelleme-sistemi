"""
Ortak ses cihazi secim katmani.

main.py (gercek akisi acar) ve health_check.py (cihazlarin saglikli olup
olmadigini test eder) ayni "hangi mikrofon/hoparlor gercek?" mantigini iki
ayri yerde tutuyordu. Bu modul o mantigi TEK yerde toplar, boylece EXCLUDE
listesi veya oncelik sirasi degisince tek dosya guncellenir.

Kullanim:
    from jarvis.actions.audio_devices import best_candidate, candidates_with_tier, device_name

    idx, tier = best_candidate("input")
    for idx, tier in candidates_with_tier("output"):
        ...
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Bluetooth kulaklik (airpods/hands-free), VB-Audio sanal kablosu (cable) ve
# Windows'un soyut ses esleyicisi (mapper) ACIKCA elenir - bunlarin hicbiri
# gercek bir fiziksel cihaz degildir ve sessizlige/yanlis algilamaya yol acar.
EXCLUDE: tuple[str, ...] = ("cable", "ses eşleştiricisi", "sound mapper", "mapper", "vb-audio")

# Windows WDM-KS (Kernel Streaming) host API'si, PortAudio'nun BLOKLAYICI
# (blocking) akis modunu desteklemiyor - main.py hem mikrofon (sd.InputStream
# callback modunda calissa da bazi surucularde ayni sorunu yasayabiliyor) hem
# de hoparlor (sd.RawOutputStream, TAMAMEN blocking) icin bu modu kullaniyor.
# Sonuc: "Unanticipated host error [PaErrorCode -9999]: 'Blocking API not
# supported yet' [Windows WDM-KS error -9999]" - ayni fiziksel cihazin
# MME/DirectSound/WASAPI kopyalari zaten listede oldugu icin, WDM-KS
# girdilerini tamamen atlamak gercek cihaz kapsamini AZALTMAZ, sadece
# bastan basarisiz olacagi belli denemeleri (ve devre kesiciyi bosuna
# tuketmeyi) onler.
_UNSUPPORTED_HOSTAPIS: tuple[str, ...] = ("wdm-ks",)


def _hostapi_name(hostapi_index: int, hostapi_cache: dict[int, str]) -> str:
    if hostapi_index in hostapi_cache:
        return hostapi_cache[hostapi_index]
    try:
        import sounddevice as sd
        name = str(sd.query_hostapis(hostapi_index).get("name", "")).lower()
    except Exception:
        name = ""
    hostapi_cache[hostapi_index] = name
    return name

# Cihaz adinda gecerse "gercek mikrofon/hoparlor" sayilan anahtar kelimeler.
_NAME_HINTS: dict[str, tuple[str, ...]] = {
    "input":  ("mikrofon", "microphone"),
    "output": ("hoparlör", "speaker", "kulaklık", "headphone", "realtek"),
}
_CHANNEL_KEY: dict[str, str] = {
    "input":  "max_input_channels",
    "output": "max_output_channels",
}


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR: Path = _get_base_dir()
PREFS_PATH: Path = BASE_DIR / "config" / "audio_prefs.json"


# --- Kullanicinin elle sectigi tercih (opsiyonel) ------------------------

def get_audio_prefs() -> dict[str, Any]:
    """{'input_device_name': str|None, 'output_device_name': str|None}
    dondurur. Dosya yoksa veya bozuksa bos sozluk doner - hicbir sey
    kirilmaz, sadece otomatik secime geri dusulur."""
    if not PREFS_PATH.is_file():
        return {}
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.debug("[AudioDevices] Tercih dosyasi okunamadi (%s): %s", PREFS_PATH, e)
        return {}


def set_audio_prefs(
    input_device_name: str | None = None,
    output_device_name: str | None = None,
) -> None:
    """Verilen alanlari mevcut tercih dosyasina isler (None = degistirme).
    Bos string ('') verilirse o tercih temizlenir (tekrar otomatik secime
    donulur). Atomik yazma kullanarak yarim kalmis dosya yazimlarini onler."""
    prefs = get_audio_prefs()
    if input_device_name is not None:
        if input_device_name == "":
            prefs.pop("input_device_name", None)
        else:
            prefs["input_device_name"] = input_device_name
    if output_device_name is not None:
        if output_device_name == "":
            prefs.pop("output_device_name", None)
        else:
            prefs["output_device_name"] = output_device_name

    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Atomik yazim: gecici dosyaya yazilip hedef konuma tasinir
        with tempfile.NamedTemporaryFile(
            "w",
            dir=PREFS_PATH.parent,
            delete=False,
            encoding="utf-8",
            suffix=".tmp",
        ) as tmp:
            json.dump(prefs, tmp, ensure_ascii=False, indent=2)
            temp_name = tmp.name
        Path(temp_name).replace(PREFS_PATH)
    except Exception as e:
        logger.error("[AudioDevices] Tercihler kaydedilemedi (%s): %s", PREFS_PATH, e)


# --- Cihaz listeleme / secim ----------------------------------------------

def list_devices() -> list[dict[str, Any]]:
    """sd.query_devices() sonucunu dict listesi olarak dondurur; PortAudio
    hicbir cihaz goremezse (veya surucu hatasi varsa) bos liste doner."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return list(devices) if devices is not None else []
    except Exception as e:
        logger.warning("[AudioDevices] ⚠️ Cihaz listesi alinamadi: %s", e)
        return []


def device_name(index: int | None) -> str:
    """Log/HUD icin okunabilir isim. index None ise sistem varsayilanini
    ifade eder."""
    if index is None:
        return "Sistem varsayılanı"
    devices = list_devices()
    try:
        if 0 <= index < len(devices):
            return str(devices[index].get("name", f"#{index}"))
        return f"#{index}"
    except Exception:
        return f"#{index}"


def candidates_with_tier(kind: Literal["input", "output"] | str) -> list[tuple[int | None, str]]:
    """kind: 'input' veya 'output'. En iyi adaydan en kotuye siralanmis
    (index, tier) listesi dondurur. tier degerleri:
      'preference'        - kullanicinin config/audio_prefs.json'da sectigi
      'named'             - adinda 'mikrofon'/'hoparlor' vb. gecen, gercek cihaz
      'preferred'         - yasakli listede olmayan herhangi bir giris/cikis
      'fallback_excluded' - sadece yasakli (cable/mapper) cihazlar kaldiysa
      'system_default'    - PortAudio'nun kendi varsayilani (device=None)
    """
    if kind not in ("input", "output"):
        raise ValueError(f"Gecersiz kind: {kind!r}. 'input' veya 'output' olmalidir.")

    channel_key = _CHANNEL_KEY[kind]
    hints = _NAME_HINTS[kind]
    devices = list_devices()
    seen: set[int] = set()
    result: list[tuple[int | None, str]] = []
    hostapi_cache: dict[int, str] = {}

    def _add(idx: int, tier: str) -> None:
        if idx not in seen:
            seen.add(idx)
            result.append((idx, tier))

    # Cihaz isimlerini kucuk harfe cevirip onbellekleyerek coklu aramayi hizlandir.
    # WDM-KS uzerinden gelen girdileri ayri tutuyoruz - bunlar blocking akis
    # modunu desteklemedigi icin bastan basarisiz olacagi belli (bkz. yukaridaki
    # _UNSUPPORTED_HOSTAPIS aciklamasi); ayni fiziksel cihazin diger host API
    # kopyalari (MME/DirectSound/WASAPI) zaten listede oldugundan bunlari
    # tamamen elemek gercek kapsamdan bir sey kaybettirmez.
    cached_info: list[tuple[int, int, str]] = []
    wdmks_info: list[tuple[int, int, str]] = []
    for i, d in enumerate(devices):
        channels = int(d.get(channel_key, 0) or 0)
        name = str(d.get("name", "")).lower()
        hostapi = _hostapi_name(int(d.get("hostapi", -1) or -1), hostapi_cache)
        if any(h in hostapi for h in _UNSUPPORTED_HOSTAPIS):
            wdmks_info.append((i, channels, name))
        else:
            cached_info.append((i, channels, name))

    # 0. Kullanicinin elle sectigi tercih (varsa ve hala takiliysa).
    pref_key = f"{kind}_device_name"
    pref_name = get_audio_prefs().get(pref_key)
    if pref_name:
        target_name = pref_name.lower()
        for idx, channels, name in cached_info:
            if channels > 0 and target_name in name:
                _add(idx, "preference")
                break

    # 1. Adinda acikca mikrofon/hoparlor gecen, yasakli olmayan cihaz.
    for idx, channels, name in cached_info:
        if (
            channels > 0
            and any(h in name for h in hints)
            and not any(x in name for x in EXCLUDE)
        ):
            _add(idx, "named")

    # 2. Yasakli listede olmayan herhangi bir giris/cikis.
    for idx, channels, name in cached_info:
        if channels > 0 and not any(x in name for x in EXCLUDE):
            _add(idx, "preferred")

    # 3. Yasakli olanlar dahil, WDM-KS DISI kanal sayisi uygun her sey.
    for idx, channels, _name in cached_info:
        if channels > 0:
            _add(idx, "fallback_excluded")

    # 4. Son care: WDM-KS girdileri - blocking modda basarisiz olacagi neredeyse
    # kesin, ama hic baska secenek yoksa (tek cihaz sadece WDM-KS uzerinden
    # goruluyorsa) yine de denemeye deger.
    for idx, channels, _name in wdmks_info:
        if channels > 0:
            _add(idx, "hostapi_unsupported")

    # 5. PortAudio'nun kendi varsayilani.
    result.append((None, "system_default"))
    return result


def best_candidate(kind: Literal["input", "output"] | str) -> tuple[int | None, str]:
    return candidates_with_tier(kind)[0]


def get_candidates(kind: Literal["input", "output"] | str) -> list[int | None]:
    """main.py'nin sirayla deneyecegi duz index listesi (tier bilgisi olmadan)."""
    return [idx for idx, _tier in candidates_with_tier(kind)]