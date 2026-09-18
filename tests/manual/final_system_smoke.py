import os
import sys
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from jarvis.ui import JarvisUI

base = Path(__file__).resolve().parent
app = QApplication.instance() or QApplication(sys.argv)
ui = JarvisUI(str(base / 'assets' / 'jarvis_icon_3d.png'))
if getattr(ui._win, '_overlay', None):
    ui._win._overlay.hide()
ui.set_state('LISTENING')
ui.write_log('FINAL SMOKE: UI bağlantıları hazır')
ui._win._content_panel.hide()
assert not ui._win._content_panel.isVisible()
ui.set_mic_device('Smoke Microphone')
ui.set_speaker_device('Smoke Speaker')
assert 'Smoke Microphone' in ui._win._mic_lbl.text()
assert 'Smoke Speaker' in ui._win._speaker_lbl.text()
ui._win._apply_state('SPEAKING')
assert ui._win.hud.speaking is True
ui._win._apply_state('LISTENING')
ui._win.grab().save(str(base / 'ui_final_smoke.png'))
QTimer.singleShot(250, app.quit)
app.exec()
print('FINAL_SYSTEM_SMOKE_OK')
