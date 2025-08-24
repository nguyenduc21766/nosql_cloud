import json
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "settings.json"
TOKEN_FILE    = Path(__file__).parent / ".token"

def _load_token() -> str:
    # 1) settings.json (preferred)
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse /app/settings.json: {e}")
        token = (data.get("token") or "").strip()
        if not token:
            raise RuntimeError(
                "settings.json found but missing 'token'. "
                'Put: {"token":"<your-secret>"}'
            )
        return token

    # 2) .token (plain text fallback)
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(".token is empty. Put your token on the first line.")
        return token

    # 3) nothing found
    raise RuntimeError(
        "No /app/settings.json or /app/.token found.\n"
        "Create /app/settings.json from /app/settings_example.json, or create /app/.token."
    )

EXPECTED_TOKEN = _load_token()
