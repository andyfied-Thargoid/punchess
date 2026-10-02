import importlib

from server.app import main


def test_default_port_is_2700(monkeypatch):
    monkeypatch.delenv("PUNCHESS_PORT", raising=False)
    reloaded = importlib.reload(main)
    assert reloaded.PORT == 2700


def test_llamacpp_client_is_available_as_a_bundled_client():
    assert main.BUNDLED_CLIENTS["python_llamacpp"] == {
        "id": "python_llamacpp",
        "name": "Python llama.cpp bot",
        "description": "LLM-powered client using a llama.cpp OpenAI-compatible endpoint.",
        "script": "clients/python_llamacpp/bot.py",
    }
