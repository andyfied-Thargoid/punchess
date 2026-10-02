import os
import re
import time
from typing import Any, Dict, Iterable, List

import chess
import httpx

BASE_URL = os.getenv("PUNCHESS_URL", "http://localhost:2700")
BOT_NAME = os.getenv("PUNCHESS_BOT_NAME", "llama.cpp-bot")
LLAMACPP_URL = os.getenv("PUNCHESS_LLAMACPP_URL", "http://127.0.0.1:11436/v1")
LLAMACPP_MODEL = os.getenv("PUNCHESS_LLAMACPP_MODEL", "qwen3.5-35b-ud-q3_k_xl")
LLAMACPP_TEMPERATURE = float(os.getenv("PUNCHESS_LLAMACPP_TEMPERATURE", "0"))
LLAMACPP_MAX_TOKENS = int(os.getenv("PUNCHESS_LLAMACPP_MAX_TOKENS", "32"))
POLL_INTERVAL_SECONDS = float(os.getenv("PUNCHESS_POLL_INTERVAL_SECONDS", "0.5"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("PUNCHESS_HTTP_TIMEOUT_SECONDS", "30"))
RETRY_DELAY_SECONDS = float(os.getenv("PUNCHESS_RETRY_DELAY_SECONDS", "2"))
MAX_RETRIES = int(os.getenv("PUNCHESS_MAX_RETRIES", "10"))

SYSTEM_PROMPT = (
    "You are a chess player in a Punchess API match. "
    "Return exactly one legal move in UCI notation and nothing else."
)
UCI_MOVE_RE = re.compile(r"\b([a-h][1-8][a-h][1-8][qrbn]?)\b", re.IGNORECASE)


def legal_moves(game_state: Dict[str, Any]) -> List[str]:
    board = chess.Board(game_state["fen"])
    return [move.uci() for move in board.legal_moves]


def build_prompt(game_state: Dict[str, Any], moves: Iterable[str]) -> str:
    move_list = list(moves)
    previous_moves = " ".join(game_state.get("moves", [])) or "(start of game)"
    return (
        f"Game ID: {game_state['game_id']}\n"
        f"Side to move: {game_state['turn']}\n"
        f"FEN: {game_state['fen']}\n"
        f"Previous moves: {previous_moves}\n"
        "Choose exactly one legal move from this list and reply with only the move in UCI format.\n"
        f"Legal moves: {', '.join(move_list)}"
    )


def extract_move(response_text: str, moves: Iterable[str]) -> str:
    legal = {move.lower() for move in moves}
    candidate = response_text.strip().lower()
    if candidate in legal:
        return candidate

    for match in UCI_MOVE_RE.findall(response_text):
        lowered = match.lower()
        if lowered in legal:
            return lowered

    raise ValueError(f"no legal UCI move found in llama.cpp response: {response_text!r}")


def request_llamacpp_move(game_state: Dict[str, Any], client: httpx.Client) -> str:
    moves = legal_moves(game_state)
    response = client.post(
        f"{LLAMACPP_URL.rstrip('/')}/chat/completions",
        json={
            "model": LLAMACPP_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(game_state, moves)},
            ],
            "temperature": LLAMACPP_TEMPERATURE,
            "max_tokens": LLAMACPP_MAX_TOKENS,
            "stream": False,
        },
    )
    response.raise_for_status()
    payload = response.json()
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"expected chat completion content from llama.cpp, got: {payload!r}") from exc
    if not isinstance(text, str):
        raise ValueError(f"expected string chat completion content, got: {payload!r}")
    return extract_move(text, moves)


def register(client: httpx.Client) -> str:
    response = client.post(
        f"{BASE_URL}/api/agents/register",
        json={
            "name": BOT_NAME,
            "metadata": {
                "template": "python",
                "strategy": "llamacpp",
                "model": LLAMACPP_MODEL,
            },
        },
    )
    response.raise_for_status()
    return response.json()["agent_id"]


def main() -> None:
    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                agent_id = register(client)
                break
            except Exception as exc:
                print(f"Registration attempt {attempt}/{MAX_RETRIES} failed: {exc}")
                if attempt == MAX_RETRIES:
                    raise
                time.sleep(RETRY_DELAY_SECONDS)

        game_id = None
        while not game_id:
            join = client.post(f"{BASE_URL}/api/lobby/join", json={"agent_id": agent_id})
            join.raise_for_status()
            game_id = join.json().get("game_id")
            if not game_id:
                print("Waiting in lobby...")
                time.sleep(1)

        print(f"Joined game {game_id}")
        while True:
            state = client.get(f"{BASE_URL}/api/games/{game_id}")
            state.raise_for_status()
            game_state = state.json()
            if game_state["status"] != "active":
                print(f"Game complete: {game_state['result']} ({game_state['termination_reason']})")
                break

            if game_state["turn_agent_id"] != agent_id:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            try:
                move = request_llamacpp_move(game_state, client)
            except Exception as exc:
                print(f"llama.cpp move selection failed: {exc}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            print(f"Playing {move}")
            response = client.post(
                f"{BASE_URL}/api/games/{game_id}/move",
                json={
                    "agent_id": agent_id,
                    "move": move,
                    "debug": {"source": "python_llamacpp", "model": LLAMACPP_MODEL},
                },
            )
            if response.status_code >= 400:
                print("Move rejected", response.text)
                time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
