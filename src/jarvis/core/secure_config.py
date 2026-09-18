"""Sır yönetimi: önce ortam değişkeni, sonra KULLANICI veri dizini, en son paket içi.

v25'te `config/api_keys.json` kurulu kod klasörünün içindeydi; uygulama oraya
yazmaya da çalışıyordu. Bunun üç sonucu vardı: anahtar dağıtım zip'ine sızma
riski, "Program Files" altında yazma hatası ve her güncellemede dosyanın
kaybolması. Artık gerçek dosya `jarvis.paths.config_dir()` altında tutulur;
paket içindeki kopya yalnızca ESKİ kurulumlardan gelen veri için okunur.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from jarvis.paths import certs_dir, config_dir, package_dir


def base_dir() -> Path:
    """Geriye dönük uyum: eski çağrı yerleri paket dizinini bekliyor."""
    return package_dir()


def api_keys_path(for_write: bool = False) -> Path:
    """Okunacak/yazılacak api_keys.json yolu.

    Okuma: env yolu -> kullanıcı veri dizini -> (varsa) eski paket içi dosya.
    Yazma: her zaman kullanıcı veri dizini.
    """
    env = os.environ.get("JARVIS_API_KEYS", "").strip()
    if env:
        return Path(env).expanduser()

    user_path = config_dir() / "api_keys.json"
    if for_write or user_path.exists():
        return user_path

    legacy = package_dir() / "config" / "api_keys.json"
    return legacy if legacy.exists() else user_path


def load_config() -> dict:
    try:
        data = json.loads(api_keys_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data: dict) -> Path:
    """Yapılandırmayı SADECE kullanıcı veri dizinine yazar."""
    path = api_keys_path(for_write=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    return path


def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key:
        return key
    key = str(load_config().get("gemini_api_key", "")).strip()
    if key and not key.startswith("REPLACE_"):
        return key
    raise RuntimeError("GEMINI_API_KEY ortam değişkeni tanımlı değil.")


def tls_paths() -> tuple[Path, Path]:
    """Dashboard TLS anahtar/sertifika yolu (kullanıcı veri dizininde)."""
    d = certs_dir()
    return d / "jarvis.key", d / "jarvis.crt"


def ensure_self_signed_cert() -> tuple[Path, Path] | None:
    """Yoksa yerel ağ için kendinden imzalı sertifika üretir.

    v25'te GERÇEK bir RSA özel anahtarı (`config/certs/jarvis.key`) dağıtım
    paketinin içinde geliyordu - paketi indiren herkes aynı anahtara sahip
    olduğu için TLS hiçbir şey korumuyordu. Anahtar artık kurulan makinede,
    ilk çalıştırmada üretilir ve depoya/pakete asla girmez.
    """
    key_path, cert_path = tls_paths()
    if key_path.exists() and cert_path.exists():
        return key_path, cert_path
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MuratJARVIS Dashboard")])
        now = datetime.datetime.now(datetime.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256())
        )
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        if os.name == "posix":
            key_path.chmod(0o600)
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return key_path, cert_path
    except Exception as exc:
        print(f"[TLS] Kendinden imzalı sertifika üretilemedi, düz HTTP kullanılacak: {exc}")
        return None
