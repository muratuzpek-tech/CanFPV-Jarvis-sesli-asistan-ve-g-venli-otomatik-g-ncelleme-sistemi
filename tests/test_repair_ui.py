from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QShortcut, QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog

from jarvis.core.secure_config import save_config
from jarvis.ui import MainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _face_path() -> str:
    return str(next(Path(__file__).parents[1].glob("src/jarvis/assets/*.png")))


def _jpeg_bytes() -> bytes:
    image = QImage(32, 24, QImage.Format.Format_RGB32)
    image.fill(0x102030)
    payload = QByteArray()
    buffer = QBuffer(payload)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "JPG")
    buffer.close()
    return bytes(payload)


def test_mute_button_and_f4_are_real_qt_actions(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    window = MainWindow(_face_path())
    try:
        assert window._mute_btn.isVisible() is False  # parent is not shown yet
        window.show()
        qapp.processEvents()
        assert window._mute_btn.isVisible()
        assert window._muted is False
        QTest.mouseClick(window._mute_btn, Qt.MouseButton.LeftButton)
        assert window._muted is True
        # DUZELTME (canli testte bulundu, 2026-09-22): offscreen/headless
        # test ortaminda pencere aktivasyonu gercek bir pencere yoneticisi
        # olmadigi icin QShortcut'in varsayilan WindowShortcut baglamini
        # (aktif pencere sarti) tetiklemiyor - activateWindow() bile
        # yetmiyor, bu platformun kendi sinirlamasi. Gercek kod (_toggle_mute,
        # F4 QShortcut baglantisi ui.py'de) dogru ve degismedi. OS tus
        # olayini simule etmek yerine, F4'e baglanmis GERCEK QShortcut
        # nesnesini bulup dogrudan tetikliyoruz - testin asil amaci zaten
        # "gercek bir Qt aksiyonu mu (dead code degil mi)" diye dogrulamak.
        f4_shortcuts = [sc for sc in window.findChildren(QShortcut)
                        if sc.key() == QKeySequence("F4")]
        assert f4_shortcuts, "F4 icin kayitli bir QShortcut bulunamadi"
        f4_shortcuts[0].activated.emit()
        assert window._muted is False
    finally:
        window.close()
        qapp.processEvents()


def test_environment_key_is_presence_only_and_setup_preserves_fields(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv("GEMINI_API_KEY", "env-presence-only")
    window = MainWindow(_face_path())
    try:
        assert window._ready is True
        assert window._check_config() is True
    finally:
        window.close()
        qapp.processEvents()

    monkeypatch.delenv("GEMINI_API_KEY")
    save_config({"gemini_api_key": "old", "os_system": "linux", "other": "keep"})
    window = MainWindow(_face_path())
    try:
        window._on_setup_done("new-key", "windows")
        saved = json.loads((tmp_path / "config" / "api_keys.json").read_text(encoding="utf-8"))
        assert saved["gemini_api_key"] == "new-key"
        assert os.environ["GEMINI_API_KEY"] == "new-key"
        assert saved["os_system"] == "windows"
        assert saved["other"] == "keep"
    finally:
        window.close()
        qapp.processEvents()


def test_camera_frame_has_visible_stack_target(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    window = MainWindow(_face_path())
    try:
        window._on_cam_stream(True)
        assert window._chat_stack.currentWidget() is window._camera_page
        window._on_cam_frame(_jpeg_bytes())
        assert not window._cam_live_lbl.pixmap().isNull()
        window._on_cam_stream(False)
        assert window._chat_stack.currentWidget() is window._chat_panel
    finally:
        window.close()
        qapp.processEvents()


def test_send_is_visible_and_callback_invoked(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    received: list[str] = []
    window = MainWindow(_face_path())
    try:
        window.on_text_command = received.append
        window._input.setText("offline hello")
        window._send()
        QTest.qWait(80)
        assert received == ["offline hello"]
        assert window._chat_messages_layout.count() >= 2
        assert any("offline hello" in label.text() for label in window.findChildren(type(window._chat_empty_lbl)) if label.text())
    finally:
        window.close()
        qapp.processEvents()


def test_navigation_and_file_picker_attach_without_approval_claim(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "home"))
    selected = tmp_path / "note.txt"
    selected.write_text("offline", encoding="utf-8")
    window = MainWindow(_face_path())
    try:
        window.show()
        if window._overlay is not None:
            window._overlay.hide()
        window.activateWindow()
        # DUZELTME (canli testte bulundu, 2026-09-22): tek bir
        # qapp.processEvents() cagrisi, offscreen platformda pencerenin
        # GERCEKTEN aktif hale gelmesi icin yeterli event-loop turunu
        # garanti etmiyordu - bu yuzden setFocus() cagrisi (ui.py, "Dosyalar"
        # sekmesi tiklaninca) gecerli olmadan test devam ediyor, hasFocus()
        # hep False donuyordu. Qt'nin bu tam senaryo icin onerdigi
        # qWaitForWindowActive, pencere gercekten aktif olana kadar
        # (timeout ile) event loop'u dondurur - izole testte calistigi
        # dogrulandi. Gercek kod (_drop_zone.setFocus() cagrisi) dogruydu.
        assert QTest.qWaitForWindowActive(window, 2000), "pencere aktif olmadi"
        window._nav_buttons["Sistem"].click()
        assert window._chat_stack.currentWidget() is window.hud
        window._nav_buttons["Dosyalar"].click()
        qapp.processEvents()
        assert window._drop_zone.hasFocus()
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(selected), "All Files (*.*)"))
        window._drop_zone._browse()
        assert window._current_file == str(selected)
        assert "tell jarvis" in window._file_hint.text().lower()
    finally:
        window.close()
        qapp.processEvents()


def test_close_stops_owned_timers(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    window = MainWindow(_face_path())
    window.close()
    qapp.processEvents()
    assert not window._clock_tmr.isActive()
    assert not window._metric_tmr.isActive()
    assert not window._drop_zone._anim_tmr.isActive()
    assert not window._log._tmr.isActive()
    assert not window.hud._tmr.isActive()
