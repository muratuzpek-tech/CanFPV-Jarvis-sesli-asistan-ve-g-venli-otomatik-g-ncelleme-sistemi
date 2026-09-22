import jarvis.actions.local_llm as llm

# DUZELTME (canli testte bulundu, 2026-09-22): bu test sabit/sahte bir
# model listesi kullanarak _list_ollama_models()'i mock'luyordu (dogru
# yaklasim - gercek makinedeki kurulu modellere bagimli olmamali), AMA
# beklenen sonuc ('qwen3.5:0.8b') _PREFERRED_MODELS'in GUNCEL sirasiyla
# uyusmuyordu: local_llm.py'de "qwen2.5-coder:7b" listede "qwen3.5:0.8b"'den
# ONCE geliyor (kasitli - JARVIS'in kod yardimcisi gorevleri icin coder
# modeli tercih edilir). Iki model de mock listede oldugunda dogru/beklenen
# sonuc "qwen2.5-coder:7b" olmalı - eski test bunu "qwen3.5:0.8b" sanip
# YANLIS bir beklentiyle yaziliydi.
original = llm._list_ollama_models
try:
    llm._list_ollama_models = lambda: ['qwen2.5-coder:7b', 'qwen3.5:2b', 'qwen3.5:0.8b']
    assert llm._pick_ollama_model() == 'qwen2.5-coder:7b'
    # Coder modeli YOKSA, siradaki tercih (qwen3.5:0.8b) secilmeli - bu da
    # ayrica dogrulaniyor, boylece iki senaryo da (coder varken/yokken) test
    # edilmis oluyor.
    llm._list_ollama_models = lambda: ['qwen3.5:2b', 'qwen3.5:0.8b']
    assert llm._pick_ollama_model() == 'qwen3.5:0.8b'
finally:
    llm._list_ollama_models = original
print('OLLAMA_FAST_MODEL_SELECTION_OK')
