import chess
import pytest

from clients.python_llamacpp import bot


GAME_STATE = {
    "game_id": "game-1",
    "turn": "white",
    "fen": chess.STARTING_FEN,
    "moves": [],
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.url = None
        self.request_json = None

    def post(self, url, json):
        self.url = url
        self.request_json = json
        return FakeResponse(self.payload)


def test_build_prompt_includes_position_and_legal_moves():
    prompt = bot.build_prompt(GAME_STATE, ["e2e4", "d2d4"])

    assert "Game ID: game-1" in prompt
    assert "Side to move: white" in prompt
    assert "Legal moves: e2e4, d2d4" in prompt


def test_extract_move_accepts_only_a_legal_uci_move():
    assert bot.extract_move("I choose e2e4.", ["e2e4", "d2d4"]) == "e2e4"

    with pytest.raises(ValueError, match="no legal UCI move found"):
        bot.extract_move("I would castle here.", ["e2e4", "d2d4"])


def test_request_move_uses_llamacpp_chat_completions_contract(monkeypatch):
    monkeypatch.setattr(bot, "LLAMACPP_URL", "http://p40.example/v1")
    monkeypatch.setattr(bot, "LLAMACPP_MODEL", "qwen3.5-test")
    monkeypatch.setattr(bot, "LLAMACPP_TEMPERATURE", 0.0)
    monkeypatch.setattr(bot, "LLAMACPP_MAX_TOKENS", 12)
    client = FakeClient({"choices": [{"message": {"content": "e2e4"}}]})

    move = bot.request_llamacpp_move(GAME_STATE, client)

    assert move == "e2e4"
    assert client.url == "http://p40.example/v1/chat/completions"
    assert client.request_json == {
        "model": "qwen3.5-test",
        "messages": [
            {"role": "system", "content": bot.SYSTEM_PROMPT},
            {"role": "user", "content": bot.build_prompt(GAME_STATE, bot.legal_moves(GAME_STATE))},
        ],
        "temperature": 0.0,
        "max_tokens": 12,
        "stream": False,
    }
