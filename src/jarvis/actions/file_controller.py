import os
import shutil
import platform
import secrets
from pathlib import Path
from datetime import datetime

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"

_SAFE_ROOTS: list[Path] = [
    Path.home(),
]

# --- Windows "bilinen klasör" cozumu (OneDrive Klasor Tasima dahil) --------
#
# GERCEK YASANAN HATA: Path.home() / "Desktop" gibi saf birlestirme, OneDrive
# "Klasor Tasima" (Known Folder Move) aktifse YANLIS bir yola isaret ediyor.
# OneDrive KFM acildiginda kullanicinin GERCEK Masaustu/Belgeler/Indirilenler/
# Resimler/Muzik/Videolar klasorleri "C:\Users\<ad>\OneDrive\Masaustu" gibi bir
# yere tasinir; eski "C:\Users\<ad>\Desktop" ya bos kalir ya da hic yoktur.
# Jarvis eskiden hep bu ESKI, kullanicinin ARTIK GORMEDIGI klasoru kullaniyordu
# - dosya olusturma/silme "basarili" donuyordu ama kullanicinin gercek
# masaustunde hicbir sey degismiyordu (kullanicinin gercekten yasadigi hata).
#
# Dogru cozum: Windows'un SHGetKnownFolderPath Shell API'sini cagirmak - bu,
# OneDrive/Grup Ilkesi/manuel tasima dahil HER TURLU yonlendirmeyi dogru
# sekilde takip eder (registry/env-var parse etmekten cok daha guvenilir).
# Windows disinda ya da API basarisiz olursa eski Path.home()/<isim> davranisina
# duser - hicbir platformda regresyona yol acmaz.

_FOLDERID_GUIDS: dict[str, str] = {
    "desktop":   "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures":  "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music":     "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos":    "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


def _known_folder_path(key: str) -> "Path | None":
    """Windows Shell API ile GERCEK bilinen klasor yolunu doner (OneDrive
    yonlendirmesi dahil). Windows disinda, API yoksa veya sonuc gecersizse
    None doner - cagiran taraf eski davranisa (Path.home()/<isim>) duser."""
    if _OS != "Windows":
        return None
    guid_str = _FOLDERID_GUIDS.get(key)
    if not guid_str:
        return None
    try:
        import ctypes
        from uuid import UUID

        class _GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        u = UUID(guid_str)
        time_low, time_mid, time_hi_version, clock_seq_hi_variant, clock_seq_low, node = u.fields
        guid = _GUID()
        guid.Data1 = time_low
        guid.Data2 = time_mid
        guid.Data3 = time_hi_version
        guid.Data4[0] = clock_seq_hi_variant
        guid.Data4[1] = clock_seq_low
        for i, b in enumerate(node.to_bytes(6, "big")):
            guid.Data4[2 + i] = b

        buf = ctypes.c_wchar_p()
        hresult = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, 0, ctypes.byref(buf)
        )
        if hresult != 0 or not buf.value:
            return None
        path_str = buf.value
        try:
            ctypes.windll.ole32.CoTaskMemFree(buf)
        except Exception:
            pass
        p = Path(path_str)
        return p if p.is_dir() else None
    except Exception:
        return None

# Onaysiz calisan move_file/copy_file, yanlis anlasilan bir sesli komuttan
# dolayi dosyalarin yanlislikla tasinmasina yol acabiliyordu (gercek olay).
# Iki adimli onay: ilk cagri hicbir dosyaya dokunmaz, sadece bir kod uretir.
# Gercek islem SADECE dogru kodla, AYRI bir cagriyla gerceklesir.
_pending_file_ops: dict[str, tuple[str, Path, Path]] = {}
_pending_bulk_deletes: dict[str, tuple[Path, tuple[Path, ...]]] = {}

def _is_safe_path(target: Path) -> bool:
    """Verilen path _SAFE_ROOTS içinde mi? Değilse işlemi reddet."""
    try:
        resolved = target.resolve()
        return any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in _SAFE_ROOTS
        )
    except Exception:
        return False

def _get_desktop() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DESKTOP_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    kf = _known_folder_path("desktop")
    if kf:
        return kf
    return Path.home() / "Desktop"

def _get_downloads() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    kf = _known_folder_path("downloads")
    if kf:
        return kf
    return Path.home() / "Downloads"

def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    kf = _known_folder_path("documents")
    if kf:
        return kf
    return Path.home() / "Documents"

def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    kf = _known_folder_path("pictures")
    if kf:
        return kf
    return Path.home() / "Pictures"

def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    kf = _known_folder_path("music")
    if kf:
        return kf
    return Path.home() / "Music"

def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    kf = _known_folder_path("videos")
    if kf:
        return kf
    return Path.home() / "Videos"


_SHORTCUT_DIRS: tuple[str, ...] = (
    "desktop", "downloads", "documents", "pictures", "music", "videos", "home",
)
# Model bazen Turkce klasor adlarini da kullanabiliyor - Ingilizce kisayola
# esleyip ayni mantigi calistirmak icin.
_SHORTCUT_TR_ALIASES: dict[str, str] = {
    "masaüstü": "desktop", "masaustu": "desktop",
    "indirilenler": "downloads",
    "belgeler": "documents",
    "resimler": "pictures",
    "müzik": "music", "muzik": "music",
    "videolar": "videos",
    "ev": "home",
}


def _normalize_shortcut(word: str) -> str:
    w = word.strip().lower()
    return _SHORTCUT_TR_ALIASES.get(w, w)


def _normalize_path_name(path: str, name: str) -> tuple[str, str]:
    """Model bazen path='desktop', name='dosya.txt' diye AYRI parametre
    gonderiyor, bazen (ozellikle sesli komutlarda) hepsini tek bir path
    icine ('desktop/dosya.txt' veya 'masaüstü/dosya.txt') sikistirip name'i
    bos birakiyor. Ikinci durumda _resolve_path bunu bilinen bir kisayol
    olarak tanimadigi icin (tam string eslesmesi ariyor), proje klasorune
    gore ANLAMSIZ bir relatif yola donusuyor ve dosya hep 'bulunamadi'
    cikiyordu - kullanicinin gercekten yasadigi hata buydu.

    name bosken path icinde bir ayirici varsa ve ilk parca bilinen bir
    kisayolsa, path'i kisayol + kalan kismi isim olarak boluyoruz."""
    if name:
        return path, name
    raw = path.strip()
    for sep in ("/", "\\"):
        if sep in raw:
            head, _, rest = raw.partition(sep)
            key = _normalize_shortcut(head)
            if key in _SHORTCUT_DIRS and rest:
                return key, rest
    return path, name


def _normalize_file_name(name: str) -> str:
    """Sesli komutlarda dosya adına eklenen Türkçe fiil eklerini ayır.

    Örnek: ``JARVIS_TEST_HEALTH.txt dosyasını sil`` ->
    ``JARVIS_TEST_HEALTH.txt``. Yalnızca bilinen komut son ekleri kaldırılır;
    dosya adının içindeki kelimelere dokunulmaz.
    """
    value = str(name or "").strip().strip('"\'`')
    suffixes = (
        " dosyasını sil", " dosyayı sil", " dosyasini sil",
        " dosyayi sil", " dosyasını kaldır", " dosyayı kaldır",
        " dosyasini kaldir", " dosyayi kaldir", " dosyasını siler misin",
        " dosyayı siler misin", " dosyasını sil lütfen", " dosyayı sil lütfen",
    )
    lowered = value.casefold()
    for suffix in suffixes:
        if lowered.endswith(suffix.casefold()):
            return value[: -len(suffix)].strip().strip('"\'`')
    return value


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
    }
    lower = _normalize_shortcut(raw)
    if lower in shortcuts:
        return shortcuts[lower]
    return Path(raw).expanduser()

def _resolve_target_name(base: Path, name: str) -> tuple[Path | None, str | None]:
    """'name' base icinde TAM ismiyle yoksa, UZANTISIZ isim eslesmesine bakar
    (ör. kullanici 'murat12345' der, gercek dosya 'murat12345.txt'dir).

    Sesli/yazili komutlarda kullanicilar neredeyse hicbir zaman dosya
    uzantisini soylemez/yazmaz - eskiden bu yuzden tam olarak var olan bir
    dosya bile 'Not found' donuyordu ve Jarvis 'boyle bir dosya yok' gibi
    yanlis bir cevap veriyordu (kullanicinin gercekten yasadigi hata).

    Tek eslesme varsa onu kullanir; birden fazla eslesme varsa (ör. hem
    'murat12345.txt' hem 'murat12345.docx' varsa) hangisini kastettigini
    netlestirmesi icin acikca bir hata mesaji doner - sessizce rastgele
    birini SILMEZ/TASIMAZ."""
    target = base / name
    if target.exists() or not base.is_dir():
        return target, None

    name_lower = name.strip().lower()
    stem_lower = Path(name).stem.lower()
    matches = []
    try:
        for item in base.iterdir():
            if item.name.lower() == name_lower or item.stem.lower() == stem_lower:
                matches.append(item)
    except Exception:
        return target, None

    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(m.name for m in matches)
        return None, f"Birden fazla eşleşme bulundu, hangisini kastettiğini netleştir: {names}"
    return target, None


def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _safe_trash(target: Path) -> str:

    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        # DUZELTME (kullanici onayli, 2026-09-15, "bos hedef guvenligi"):
        # name bos gelirse eskiden target=base (klasorun KENDISI) oluyordu -
        # write_text() bir klasore yazmaya calisip IsADirectoryError
        # firlatiyordu (yakalaniyordu ama mesaj cig bir Python hatasiydi ve
        # kok neden gizleniyordu). Simdi net, erken bir hata donuluyor -
        # base/target hic hesaplanmiyor, diske HICBIR dokunma olmuyor.
        if not name:
            return "Could not create file: dosya adı belirtilmedi (isim boş olduğu için işlem güvenlik amacıyla durduruldu, hedef klasörün kendisine dokunulmadı)."
        base   = _resolve_path(path)
        target = base / name
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        # DUZELTME (kullanici onayli analiz raporu, 2026-09-15): write_text()
        # exception firlatmadi diye BASARILI SAYMA - "agent 'yaptim' dedi"
        # ile "gercekten oldu" ARASINDAKI fark tam burada aciliyordu (canli
        # testte gorulen sahte basari). Dosyayi TEKRAR OKUYUP gercekten
        # diskte oldugunu ve icerigin GERCEKTEN yazildigi gibi oldugunu
        # dogrula - sadece bu gecerse basari mesaji don.
        if not target.is_file():
            return f"Could not create file: dosya yazıldıktan sonra diskte bulunamadı ({target})"
        if target.read_text(encoding="utf-8") != content:
            return f"Could not create file: yazılan içerik doğrulanamadı ({target})"
        return f"File created: {target.name}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        # DUZELTME (kullanici onayli, 2026-09-15, "bos hedef guvenligi"): name
        # bos gelirse eskiden target=base oluyordu; base COGU ZAMAN zaten
        # var olan bir klasor (ör. Desktop) oldugu icin mkdir(exist_ok=True)
        # SESSIZCE hicbir sey yapmadan basariyla donuyor ve "Folder created:
        # <base>" gibi TAM BIR SAHTE BASARI mesaji uretiyordu - hicbir yeni
        # klasor olusmadigi halde. Simdi erken, acik bir hata donuluyor.
        if not name:
            return "Could not create folder: klasör adı belirtilmedi (isim boş olduğu için işlem güvenlik amacıyla durduruldu, mevcut klasöre dokunulmadı)."
        base   = _resolve_path(path)
        target = base / name
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.mkdir(parents=True, exist_ok=True)
        # DUZELTME (aynı rapor): mkdir() exception firlatmadi diye BASARILI
        # SAYMA - klasorun GERCEKTEN diskte var oldugunu tekrar kontrol et.
        if not target.is_dir():
            return f"Could not create folder: klasör oluşturulduktan sonra diskte bulunamadı ({target})"
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base = _resolve_path(path)
        if name:
            target, ambiguous = _resolve_target_name(base, name)
            if ambiguous:
                return ambiguous
        else:
            target = base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        # Güvenli dizin kontrolü — kritik kullanıcı klasörlerini koru
        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        return _safe_trash(target)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def delete_all_files(path: str = "downloads", confirm_code: str = "") -> str:
    """Move direct files in a safe folder to Trash, never the folder/subfolders.

    First call is preview-only and returns a short-lived confirmation code.
    The second call must provide that exact code.
    """
    try:
        base = _resolve_path(path)
        if not _is_safe_path(base):
            return f"Access denied: {base}"
        if not base.is_dir():
            return f"Not a directory: {base}"
        protected = {p.resolve() for p in (
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        )}
        if base.resolve() in protected and base.resolve() == Path.home().resolve():
            return "Protected directory, bulk deletion is not allowed here."
        files = tuple(item for item in base.iterdir() if item.is_file() and not item.name.startswith("."))
        if not confirm_code:
            code = secrets.token_hex(3)
            _pending_bulk_deletes[code] = (base, files)
            return (f"ONAY GEREKLİ: {len(files)} dosya '{base}' içinde bulundu. "
                    f"Alt klasörler ve klasörün kendisi korunacak. Onaydan sonra "
                    f"dosyalar Çöp Kutusu'na taşınacak. confirm_code={code}")
        pending = _pending_bulk_deletes.pop(confirm_code, None)
        if pending is None or pending[0] != base:
            return "Onay kodu geçersiz veya süresi dolmuş. Önce önizleme isteyin."
        moved, failed = 0, []
        for item in pending[1]:
            try:
                _safe_trash(item)
                moved += 1
            except Exception as exc:
                failed.append(f"{item.name}: {exc}")
        result = f"Bulk delete complete: {moved}/{len(pending[1])} files moved to Trash."
        if failed:
            result += " Failed: " + "; ".join(failed[:5])
        return result
    except Exception as e:
        return f"Could not bulk delete: {e}"


def move_file(path: str, name: str = "", destination: str = "", confirm_code: str = "") -> str:
    try:
        base = _resolve_path(path)
        if name:
            src, ambiguous = _resolve_target_name(base, name)
            if ambiguous:
                return ambiguous
        else:
            src = base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        if not confirm_code:
            code = secrets.token_hex(2)
            _pending_file_ops[code] = ("move", src, dst)
            return (
                f"ONAY GEREKLİ (henüz taşınmadı): '{src}' -> '{dst}'. "
                f"Kullanıcıya bu taşımayı tarif et ve kullanıcı SESLİ/YAZILI olarak "
                f"açıkça onaylarsa (kullanıcının bir sonraki mesajında), move_file'i "
                f"aynı path/name/destination ile ve confirm_code='{code}' parametresiyle "
                f"TEKRAR çağır. Kullanıcı onaylamadan bu kodu kendi kendine kullanma."
            )

        pending = _pending_file_ops.pop(confirm_code, None)
        if pending is None or pending[0] != "move" or pending[1] != src or pending[2] != dst:
            return "Onay kodu geçersiz veya süresi dolmuş. Önce confirm_code vermeden çağırıp yeni kod alın."

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        if name:
            src, ambiguous = _resolve_target_name(base, name)
            if ambiguous:
                return ambiguous
        else:
            src = base
        dst  = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))

        return f"Copied: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        target.rename(new_path)
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"

        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        # DUZELTME (kullanici onayli, 2026-09-15, "bos hedef guvenligi"):
        # name bos gelirse eskiden target=base oluyordu - open(base, "w")
        # base bir klasor oldugu icin IsADirectoryError firlatiyordu
        # (yakalaniyordu ama cig Python hata mesaji kok nedeni gizliyordu;
        # canli E2E testte bu YUZDEN "Dosyaya yaz" adimi CWD'nin kendisine
        # yazmaya calisip patlamisti). Simdi net, erken bir hata donuluyor.
        if not name:
            return "Could not write file: dosya adı belirtilmedi (isim boş olduğu için işlem güvenlik amacıyla durduruldu, hedef klasörün kendisine yazılmadı)."
        base   = _resolve_path(path)
        target = base / name
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as f:
            f.write(content)
        # DUZELTME (kullanici onayli analiz raporu, 2026-09-15): yazma
        # exception firlatmadi diye BASARILI SAYMA - dosyayi TEKRAR OKUYUP
        # icerigin GERCEKTEN orada oldugunu dogrula. append=True'da tam
        # esitlik degil, SONDA bulunma kontrol edilir (dosyada onceden baska
        # icerik olabilir).
        if not target.is_file():
            return f"Could not write file: dosya yazıldıktan sonra diskte bulunamadı ({target})"
        actual = target.read_text(encoding="utf-8")
        ok = actual.endswith(content) if append else (actual == content)
        if not ok:
            return f"Could not write file: yazılan içerik doğrulanamadı ({target})"
        action = "Appended to" if append else "Written to"
        return f"{action}: {target.name}"
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20) -> str:
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results    = []
        dir_count  = 0
        max_dirs   = 500  # performans + güvenlik limiti

        for item in search_path.rglob("*"):
            if item.is_dir():
                dir_count += 1
                if dir_count > max_dirs:
                    break
                continue
            if not item.is_file():
                continue
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)  # maksimum 50
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in search_path.rglob("*"):
            if item.is_file():
                try:
                    files.append((item.stat().st_size, item))
                except Exception:
                    continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    moved, skipped = [], []

    try:
        for item in desktop.iterdir():
            # Klasörlere, gizli dosyalara ve organize klasörlerine dokunma
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in {k for k in type_map}:
                continue

            ext        = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, exts in type_map.items():
                if ext in exts:
                    target_dir = desktop / folder
                    break

            target_dir.mkdir(exist_ok=True)
            new_path = target_dir / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            shutil.move(str(item), str(new_path))
            moved.append(f"{item.name} → {target_dir.name}/")

        result = f"Desktop organized: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(preview)
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    except Exception as e:
        return f"Could not organize desktop: {e}"


def extract_archive(path: str, name: str = "", destination: str = "") -> str:
    """Bir .zip dosyasini GUVENLI sekilde acar — discovery.py'nin karantina
    icin kullandigi AYNI zip-slip korumasi (bir zip icindeki '../../...'
    gibi yollarin hedef klasor disina cikmasini engeller).

    GERCEK YASANAN SORUN: file_controller'da 'extract' hic yoktu, bu yuzden
    bir kullanici istegi dev_agent'a ('kendi kodunu yaz ve calistir')
    dusuyordu - dev_agent'in ELLE yazdigi extraction kodu bu korumaya sahip
    DEGILDI ve calismadi (bkz. Jarvis_Improvement_Automation denemesi).
    Artik zip acmak icin GUVENLI, test edilmis TEK yol budur."""
    import zipfile

    base = _resolve_path(path)
    if name:
        src, ambiguous = _resolve_target_name(base, name)
        if ambiguous:
            return ambiguous
    else:
        src = base

    if not src.exists():
        return f"Not found: {src.name if name else src}"
    if not _is_safe_path(src):
        return f"Access denied (source): {src}"
    if not src.is_file() or src.suffix.lower() != ".zip":
        return f"Not a .zip file: {src.name}"

    # Hedef verilmezse, zip'in bulundugu klasorde zip ile AYNI isimde bir
    # alt klasore acilir - ne cikarildigi/nereye cikarildigi hep belli olur,
    # rastgele bir yere dagilmaz.
    dest = _resolve_path(destination) if destination else (src.parent / src.stem)
    if not _is_safe_path(dest):
        return f"Access denied (destination): {dest}"

    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            for member in zf.infolist():
                member_path = (dest / member.filename).resolve()
                if not str(member_path).startswith(str(dest.resolve())):
                    return f"Güvensiz zip içeriği tespit edildi (zip-slip), açma iptal edildi: {member.filename}"
            zf.extractall(dest)
        return f"Extracted: {src.name} → {dest}"
    except zipfile.BadZipFile:
        return f"Bozuk ya da geçerli olmayan zip dosyası: {src.name}"
    except Exception as e:
        return f"Could not extract: {e}"


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        stat = target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"

def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).lower().strip()
    # Sesli model bazen şema içindeki "delete" yerine doğal dil aliası
    # gönderebiliyor. Güvenli silme yolu yine yalnızca delete_file üzerinden
    # geçtiği için bu aliaslar davranışı genişletmez; sadece doğru dispatcher
    # dalına ulaşmayı sağlar.
    action = {
        "sil": "delete",
        "sil_file": "delete",
        "delete_file": "delete",
        "remove": "delete",
        "trash": "delete",
        "delete_all": "delete_all_files",
        "delete_all_files": "delete_all_files",
        "bulk_delete": "delete_all_files",
        "tümünü sil": "delete_all_files",
        "tumunu sil": "delete_all_files",
        "oluştur": "create_file",
        "olustur": "create_file",
    }.get(action, action)
    path   = params.get("path", "desktop")
    name   = _normalize_file_name(params.get("name", ""))
    path, name = _normalize_path_name(path, name)

    if player:
        player.write_log(f"[file] {action} {path}/{name}" if name else f"[file] {action} {path}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "create_file":
            return create_file(path, name=name, content=params.get("content", ""))

        elif action == "create_folder":
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)
        elif action == "delete_all_files":
            return delete_all_files(path=path, confirm_code=params.get("confirm_code", ""))

        elif action == "move":
            return move_file(path, name=name, destination=params.get("destination", ""),
                              confirm_code=params.get("confirm_code", ""))

        elif action == "copy":
            return copy_file(path, name=name, destination=params.get("destination", ""))

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "read":
            return read_file(path, name=name)

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize_desktop":
            return organize_desktop()

        elif action == "info":
            return get_file_info(path, name=name)

        elif action == "extract":
            return extract_archive(path, name=name, destination=params.get("destination", ""))

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"
