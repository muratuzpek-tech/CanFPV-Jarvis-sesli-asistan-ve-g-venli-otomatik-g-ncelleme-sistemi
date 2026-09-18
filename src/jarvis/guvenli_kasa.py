"""Güvenli dosya kasası.

Şifreleme: Fernet (AES-128-CBC + HMAC-SHA256) ve PBKDF2-HMAC-SHA256.
Orijinal dosya varsayılan olarak silinmez; bu nedenle orijinal dosyayı açarsanız
şifresiz açılması normaldir. Şifreli dosya .encrypted uzantısıyla oluşur.
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError as exc:
    raise SystemExit("Eksik paket: python -m pip install cryptography") from exc

MAGIC = b"JARVISENC1"
ITERATIONS = 390_000
SALT_SIZE = 16


def derive_key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    if not password:
        raise ValueError("Parola boş olamaz.")
    raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return base64.urlsafe_b64encode(raw)


def encrypt_file(source: Path, password: str, delete_original: bool = False) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix == ".encrypted":
        raise ValueError("Bu dosya zaten şifreli görünüyor.")
    salt = os.urandom(SALT_SIZE)
    encrypted = Fernet(derive_key(password, salt)).encrypt(source.read_bytes())
    target = source.with_name(source.name + ".encrypted")
    target.write_bytes(MAGIC + struct.pack(">I", ITERATIONS) + salt + encrypted)
    if delete_original:
        source.unlink()
    return target


def decrypt_file(source: Path, password: str, delete_encrypted: bool = False) -> Path:
    if not source.is_file() or source.suffix != ".encrypted":
        raise ValueError("Şifre çözmek için .encrypted dosyası seçin.")
    blob = source.read_bytes()
    header_size = len(MAGIC) + 4 + SALT_SIZE
    if len(blob) <= header_size or not blob.startswith(MAGIC):
        raise ValueError("Bu dosya Jarvis şifreleme biçiminde değil.")
    iterations = struct.unpack(">I", blob[len(MAGIC):len(MAGIC) + 4])[0]
    salt_start = len(MAGIC) + 4
    salt = blob[salt_start:salt_start + SALT_SIZE]
    try:
        # Iterasyon sayisi dosya basligindan okunur: ITERATIONS ileride
        # arttirilirsa eski kasa dosyalari da acilabilir kalir.
        plain = Fernet(derive_key(password, salt, iterations)).decrypt(blob[header_size:])
    except InvalidToken as exc:
        raise ValueError("Parola yanlış veya dosya bozulmuş.") from exc
    target = Path(str(source)[:-len(".encrypted")])
    if target.exists():
        target = target.with_name(target.stem + ".decrypted" + target.suffix)
    target.write_bytes(plain)
    if delete_encrypted:
        source.unlink()
    return target


class VaultApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Jarvis Güvenli Dosya Kasası")
        self.geometry("560x250")
        self.resizable(False, False)
        self.selected: Path | None = None
        tk.Label(self, text="Dosya şifreleme kasası", font=("Segoe UI", 16, "bold")).pack(pady=14)
        self.path_label = tk.Label(self, text="Henüz dosya seçilmedi", wraplength=520)
        self.path_label.pack(pady=5)
        tk.Button(self, text="Dosya seç", width=24, command=self.choose).pack(pady=5)
        buttons = tk.Frame(self)
        buttons.pack(pady=8)
        tk.Button(buttons, text="Şifrele", width=18, command=self.encrypt).grid(row=0, column=0, padx=5)
        tk.Button(buttons, text="Şifreyi çöz", width=18, command=self.decrypt).grid(row=0, column=1, padx=5)
        tk.Label(self, text="Not: Orijinal dosya varsayılan olarak korunur. Açık dosya yerine .encrypted dosyasını test edin.", fg="#884400", wraplength=520).pack(pady=12)

    def choose(self) -> None:
        name = filedialog.askopenfilename()
        if name:
            self.selected = Path(name)
            self.path_label.config(text=str(self.selected))

    def encrypt(self) -> None:
        if not self.selected:
            messagebox.showwarning("Dosya yok", "Önce bir dosya seçin.")
            return
        password = simpledialog.askstring("Parola", "Şifreleme parolası:", show="*")
        if password is None:
            return
        try:
            target = encrypt_file(self.selected, password)
            messagebox.showinfo("Başarılı", f"Şifreli dosya oluşturuldu:\n{target}\n\nOrijinal dosya silinmedi.")
        except Exception as exc:
            messagebox.showerror("Şifreleme hatası", str(exc))

    def decrypt(self) -> None:
        if not self.selected:
            messagebox.showwarning("Dosya yok", "Önce .encrypted dosyasını seçin.")
            return
        password = simpledialog.askstring("Parola", "Şifre çözme parolası:", show="*")
        if password is None:
            return
        try:
            target = decrypt_file(self.selected, password)
            messagebox.showinfo("Başarılı", f"Şifresi çözülmüş dosya:\n{target}")
        except Exception as exc:
            messagebox.showerror("Şifre çözme hatası", str(exc))


if __name__ == "__main__":
    VaultApp().mainloop()
