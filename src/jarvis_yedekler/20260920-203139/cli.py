"""Text-mode Jarvis entry point.

Usage:
    python jarvis_cli.py
    python jarvis_cli.py "CPU kullanımını kontrol et"
"""
from __future__ import annotations

import argparse
import sys

from jarvis.core.agent import JarvisAgent
from jarvis.actions.audio_devices import list_devices, get_audio_prefs, set_audio_prefs
from jarvis.actions.self_improve import self_improve


def _print_devices(kind: str) -> list[int]:
    """kind: 'input' veya 'output'. Uygun cihazlari numaralandirip yazdirir,
    kullanicinin secebilecegi index'lerin listesini dondurur."""
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices = list_devices()
    usable = [i for i, d in enumerate(devices) if d.get(channel_key, 0) > 0]
    for i in usable:
        print(f"  [{i}] {devices[i]['name']}")
    return usable


def _ses_ayarlari() -> None:
    """Kullanicinin mikrofon/hoparlor tercihini config/audio_prefs.json'a
    yazmasini saglayan basit bir sihirbaz. Bos birakilirsa otomatik secime
    geri donulur."""
    prefs = get_audio_prefs()
    print("\n--- Ses cihazı ayarları ---")
    if prefs.get("input_device_name") or prefs.get("output_device_name"):
        print(f"Mevcut mikrofon tercihi : {prefs.get('input_device_name', '(otomatik)')}")
        print(f"Mevcut hoparlör tercihi : {prefs.get('output_device_name', '(otomatik)')}")

    print("\nMikrofonlar:")
    _print_devices("input")
    sec = input("Mikrofon için numara seç (boş = otomatik, 'x' = değiştirme): ").strip()
    if sec.lower() != "x":
        if sec == "":
            set_audio_prefs(input_device_name="")
            print("Mikrofon tercihi temizlendi, otomatik seçime dönüldü.")
        else:
            try:
                idx = int(sec)
                name = list_devices()[idx]["name"]
                set_audio_prefs(input_device_name=name)
                print(f"Mikrofon tercihi kaydedildi: {name}")
            except Exception as e:
                print(f"Geçersiz seçim, değişiklik yapılmadı: {e}")

    print("\nHoparlörler:")
    _print_devices("output")
    sec = input("Hoparlör için numara seç (boş = otomatik, 'x' = değiştirme): ").strip()
    if sec.lower() != "x":
        if sec == "":
            set_audio_prefs(output_device_name="")
            print("Hoparlör tercihi temizlendi, otomatik seçime dönüldü.")
        else:
            try:
                idx = int(sec)
                name = list_devices()[idx]["name"]
                set_audio_prefs(output_device_name=name)
                print(f"Hoparlör tercihi kaydedildi: {name}")
            except Exception as e:
                print(f"Geçersiz seçim, değişiklik yapılmadı: {e}")

    print("Not: değişikliklerin etkili olması için Jarvis'i yeniden başlat.\n")


def _gelistir(arg: str) -> None:
    """/gelistir [dosya_yolu] [| hedef] - self_improve dongusunu manuel
    tetikler. Dosya verilmezse actions/ altindan otomatik secer. '|' sonrasi
    varsa hedef/goal olarak gecilir, ornek:
      /gelistir actions/weather_report.py | hata yonetimini iyilestir"""
    file_path, _, goal = arg.partition("|")
    file_path = file_path.strip()
    goal = goal.strip()
    print("\n--- Kendini geliştirme döngüsü ---")
    if file_path:
        print(f"Hedef dosya: {file_path}")
    else:
        print("Hedef dosya belirtilmedi, otomatik seçilecek.")
    print("Önce tam proje yedeği alınacak, sonra değişiklik doğrulanacak "
          "(sözdizimi + import). Doğrulama geçmezse dosya orijinaline döner.\n")

    params = {}
    if file_path:
        params["file_path"] = file_path
    if goal:
        params["goal"] = goal

    try:
        result = self_improve(parameters=params)
        print(f"\n{result}\n")
    except Exception as e:
        print(f"\nKendini geliştirme başarısız: {type(e).__name__}: {e}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis tool-using assistant")
    parser.add_argument("prompt", nargs="*", help="Tek seferlik komut")
    args = parser.parse_args()
    agent = JarvisAgent()
    if args.prompt:
        print(agent.ask(" ".join(args.prompt)))
        return 0
    print("Jarvis hazır. Çıkmak için 'çıkış' veya Ctrl+C yazın. "
          "Mikrofon/hoparlör seçmek için '/ses', kendini geliştirmesi için "
          "'/gelistir' yazabilirsiniz.")
    while True:
        try:
            text = input("\nSiz > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nJarvis: Görüşmek üzere efendim.")
            return 0
        if not text:
            continue
        if text.lower() in {"çıkış", "cikis", "exit", "quit", "q"}:
            print("Jarvis: Görüşmek üzere efendim.")
            return 0
        if text.lower() == "/context":
            print(agent.context.status())
            continue
        if text.lower() == "/plugins":
            agent.plugins.discover()
            print(agent.plugins.status())
            continue
        if text.lower() == "/ses":
            _ses_ayarlari()
            continue
        if text.lower() == "/gelistir" or text.lower().startswith("/gelistir "):
            _gelistir(text[len("/gelistir"):].strip())
            continue
        try:
            print(f"\nJarvis > {agent.ask(text)}")
        except Exception as exc:
            print(f"\nJarvis hata: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
