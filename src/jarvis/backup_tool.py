"""
CanFPV Jarvis — Yedekleme ve Geri Alma Aracı

Manuel bir araçtır: hiçbir şeyi otomatik çalıştırmaz, internetten hiçbir şey
indirmez, ne değiştireceğine kendi kendine karar vermez. Sen çalıştırırsın,
sen kontrol edersin.

Önceki sürümdeki hata: yedek klasörü projenin İÇİNDE duruyordu
(proje/.jarvis_backup) — bir klasörü kendi alt klasörüne kopyalamak kırılgan
bir tasarımdı. Bu sürümde yedekler projenin TAMAMEN DIŞINDA, zaman damgalı
ayrı klasörlerde tutulur; hem daha güvenli hem de birden fazla yedek geçmişi
saklamaya izin verir (sadece son yedek değil).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


class JarvisBackupTool:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path).resolve()
        # Yedekler projenin YANINDA, ayrı bir klasörde - proje klasörünün
        # kendi içinde DEĞİL. Bu, "kendi kendini kopyalama" riskini tamamen
        # ortadan kaldırır.
        self.backups_root = self.project_path.parent / f"{self.project_path.name}_yedekler"
        self.version_file = self.project_path / "version.json"

    # ── Sürüm takibi ─────────────────────────────────────────────────────
    def get_current_version(self) -> str:
        if not self.version_file.exists():
            return "1.0.0"
        try:
            data = json.loads(self.version_file.read_text(encoding="utf-8"))
            return data.get("version", "1.0.0")
        except Exception:
            return "1.0.0"

    def update_version(self, new_version: str) -> None:
        data = {"version": new_version, "updated_at": datetime.now().isoformat()}
        self.version_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"✓ Sürüm güncellendi: {new_version}")

    # ── Yedekleme ────────────────────────────────────────────────────────
    def create_backup(self) -> Path:
        """Tam bir proje yedeği oluşturur, zaman damgalı ayrı bir klasöre.
        Önceki yedekleri SİLMEZ - her biri korunur, geçmiş birikir."""
        self.backups_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.backups_root / stamp

        # Ayni saniye icinde iki yedek alinirsa (ornegin rollback() kendi
        # guvenlik yedegini alirken) klasor adi cakisabilir - benzersiz
        # olana kadar bir sayac ekle.
        counter = 1
        while destination.exists():
            destination = self.backups_root / f"{stamp}-{counter}"
            counter += 1

        print(f"Yedek oluşturuluyor: {destination}")
        shutil.copytree(
            self.project_path,
            destination,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        print("✓ Yedek oluşturuldu.")
        return destination

    def list_backups(self) -> list[Path]:
        """Mevcut tüm yedekleri, en yeniden en eskiye sıralı döndürür."""
        if not self.backups_root.exists():
            return []
        return sorted(
            (p for p in self.backups_root.iterdir() if p.is_dir()),
            key=lambda p: p.name, reverse=True,
        )

    def cleanup_old_backups(self, keep: int = 10) -> int:
        """En yeni `keep` yedek dışındakileri siler. Kaç tane silindiğini döndürür."""
        backups = self.list_backups()
        to_delete = backups[keep:]
        for backup in to_delete:
            shutil.rmtree(backup)
        if to_delete:
            print(f"✓ {len(to_delete)} eski yedek temizlendi.")
        return len(to_delete)

    # ── Geri alma ────────────────────────────────────────────────────────
    def rollback(self, backup_path: Path | None = None) -> bool:
        """Belirtilen yedeği (verilmezse EN YENİ yedeği) geri yükler.
        Geri yüklemeden ÖNCE mevcut durumun da bir yedeğini alır - böylece
        yanlış bir rollback bile geri alınabilir."""
        if backup_path is None:
            backups = self.list_backups()
            if not backups:
                print("✗ Hiç yedek bulunamadı.")
                return False
            backup_path = backups[0]

        if not backup_path.exists():
            print(f"✗ Yedek bulunamadı: {backup_path}")
            return False

        # Guvenlik: rollback yapmadan once mevcut (muhtemelen bozuk) durumun
        # da yedegini al - boylece "yanlis yedegi geri yukledim" durumundan
        # bile donus mumkun olur.
        print("Rollback öncesi güvenlik yedeği alınıyor...")
        self.create_backup()

        print(f"Geri alınıyor: {backup_path}")
        for item in self.project_path.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as error:
                print(f"Silme hatası ({item.name}): {error}")

        for item in backup_path.iterdir():
            destination = self.project_path / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)

        print("✓ Rollback tamamlandı.")
        return True

    def restart_jarvis(self) -> bool:
        main_file = self.project_path / "main.py"
        if not main_file.exists():
            print("⚠ main.py bulunamadı.")
            return False
        subprocess.Popen([sys.executable, str(main_file)], cwd=str(self.project_path))
        return True


if __name__ == "__main__":
    project_path = Path(__file__).resolve().parent.parent
    tool = JarvisBackupTool(project_path)

    print()
    print("=" * 40)
    print("   CANFPV JARVIS — YEDEKLEME ARACI")
    print("=" * 40)
    print()
    print("Mevcut sürüm:", tool.get_current_version())
    print("Kayıtlı yedek sayısı:", len(tool.list_backups()))
    print()
    print("Kullanım (Python'dan içe aktararak):")
    print("  tool.create_backup()        — yeni bir yedek al")
    print("  tool.list_backups()         — yedekleri listele")
    print("  tool.rollback()             — en son yedeğe geri dön")
    print("  tool.cleanup_old_backups()  — eski yedekleri temizle")
