import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from jarvis.ui import JarvisUI

base = Path(__file__).resolve().parent
face = base / "face.png"
if not face.exists():
    candidates = list((base / "assets").glob("*.png"))
    face = candidates[0] if candidates else base / "config" / "jarvis.ico"

app = QApplication.instance() or QApplication(sys.argv)
ui = JarvisUI(str(face))
ui.write_log("SMOKE: UI başlatıldı ve telemetri akışı hazır.")
ui.set_state("LISTENING")
ui._win.grab().save(str(base / "ui_smoke.png"))
QTimer.singleShot(700, app.quit)
app.exec()
print(f"UI_SMOKE_OK face={face.name} screenshot={base / 'ui_smoke.png'}")
