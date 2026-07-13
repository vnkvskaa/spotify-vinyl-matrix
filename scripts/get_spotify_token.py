#!/usr/bin/env python3
"""One-time helper: get a Spotify refresh token for the ESP32 firmware."""

from __future__ import annotations

import base64
import http.server
import json
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-currently-playing"
OUT_FILE = Path(".cache/spotify_token.json")


def ask(prompt: str) -> str:
    value = input(prompt).strip()
    if not value:
        raise SystemExit("Value required")
    return value


def save_env(client_id: str, client_secret: str) -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    env_path.write_text(
        "\n".join(
            [
                f"SPOTIFY_CLIENT_ID={client_id}",
                f"SPOTIFY_CLIENT_SECRET={client_secret}",
                f"SPOTIFY_REDIRECT_URI={REDIRECT_URI}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Saved credentials to {env_path}")


def post_token(client_id: str, client_secret: str, data: dict[str, str]) -> dict:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None
    expected_state: str = ""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        if params.get("state", [""])[0] != self.expected_state:
            CallbackHandler.error = "state mismatch"
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch")
            return

        if "error" in params:
            CallbackHandler.error = params["error"][0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed")
            return

        CallbackHandler.code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK. You can close this tab and return to the terminal.")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> None:
    print("Create an app at https://developer.spotify.com/dashboard")
    print(f"Add redirect URI exactly: {REDIRECT_URI}")
    print()
    client_id = ask("Client ID: ")
    client_secret = ask("Client Secret: ")
    save_env(client_id, client_secret)

    state = secrets.token_urlsafe(16)
    CallbackHandler.expected_state = state
    server = http.server.HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "state": state,
        }
    )
    url = f"{AUTH_URL}?{query}"
    print("\nOpen this URL if the browser did not open:\n")
    print(url)
    webbrowser.open(url)

    while CallbackHandler.code is None and CallbackHandler.error is None:
        pass

    server.shutdown()
    if CallbackHandler.error:
        raise SystemExit(f"Auth failed: {CallbackHandler.error}")
    if not CallbackHandler.code:
        raise SystemExit("No auth code returned")

    token = post_token(
        client_id,
        client_secret,
        {
            "grant_type": "authorization_code",
            "code": CallbackHandler.code,
            "redirect_uri": REDIRECT_URI,
        },
    )

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(token, indent=2), encoding="utf-8")

    refresh = token.get("refresh_token")
    print("\nSuccess.")
    print(f"Token JSON saved to {OUT_FILE}")
    print("\nPut this into include/secrets.h as SPOTIFY_REFRESH_TOKEN:\n")
    print(refresh)


if __name__ == "__main__":
    main()
