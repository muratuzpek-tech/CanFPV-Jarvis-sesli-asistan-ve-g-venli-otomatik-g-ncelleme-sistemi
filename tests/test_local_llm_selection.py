import jarvis.actions.local_llm as llm

original = llm._list_ollama_models
try:
    llm._list_ollama_models = lambda: ['qwen2.5-coder:7b', 'qwen3.5:2b', 'qwen3.5:0.8b']
    assert llm._pick_ollama_model() == 'qwen3.5:0.8b'
finally:
    llm._list_ollama_models = original
print('OLLAMA_FAST_MODEL_SELECTION_OK')
