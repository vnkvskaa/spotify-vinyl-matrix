#!/usr/bin/env python3
"""
Live virtual 16x16 Spotify vinyl preview.

Uses the real Spotify currently-playing API, downsamples album art to 16x16,
draws a spinning record, and serves an LED-matrix simulator in the browser.

Usage:
  1) Create .env (see .env.example) OR have Client ID/Secret ready
  2) python3 scripts/get_spotify_token.py   # once, if no .cache/spotify_token.json
  3) pip install -r requirements-preview.txt
  4) python3 scripts/preview_spotify_matrix.py
  5) Open http://127.0.0.1:8765
"""

from __future__ import annotations

import base64
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TOKEN_CACHE = ROOT / ".cache" / "spotify_token.json"
ENV_FILE = ROOT / ".env"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
CURRENTLY_PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-currently-playing"

MATRIX = 16
HOST = "127.0.0.1"
PORT = 8765


def load_dotenv_file() -> None:
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_creds() -> tuple[str, str]:
    load_dotenv_file()
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit(
            "Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET.\n"
            "Create .env from .env.example, then run scripts/get_spotify_token.py"
        )
    return client_id, client_secret


def http_json(
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            if not raw:
                return resp.status, None
            return resp.status, json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode()) if raw else None
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")
        return exc.code, parsed


@dataclass
class FrameState:
    lock: threading.Lock
    pixels: list[list[int]]
    is_playing: bool
    has_track: bool
    title: str
    artists: str
    track_id: str | None
    angle: float
    status: str
    updated_at: float


def blank_pixels() -> list[list[int]]:
    return [[0, 0, 0] for _ in range(MATRIX * MATRIX)]


def post_token(client_id: str, client_secret: str, data: dict[str, str]) -> dict[str, Any]:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    status, payload = http_json(
        "POST",
        TOKEN_URL,
        data=data,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"Token request failed ({status}): {payload}")
    return payload


class SpotifySession:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token: dict[str, Any] | None = None
        if TOKEN_CACHE.exists():
            self.token = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))

    def save(self) -> None:
        if not self.token:
            return
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(json.dumps(self.token, indent=2), encoding="utf-8")

    def ensure_access_token(self) -> str:
        if not self.token or "refresh_token" not in self.token:
            raise RuntimeError(
                "No Spotify refresh token. Run: python3 scripts/get_spotify_token.py"
            )
        expires_at = float(self.token.get("expires_at", 0))
        if time.time() < expires_at and self.token.get("access_token"):
            return str(self.token["access_token"])

        refreshed = post_token(
            self.client_id,
            self.client_secret,
            {
                "grant_type": "refresh_token",
                "refresh_token": str(self.token["refresh_token"]),
            },
        )
        if "refresh_token" not in refreshed:
            refreshed["refresh_token"] = self.token["refresh_token"]
        refreshed["expires_at"] = time.time() + int(refreshed.get("expires_in", 3600)) - 60
        self.token = refreshed
        self.save()
        return str(self.token["access_token"])

    def currently_playing(self) -> dict[str, Any] | None:
        token = self.ensure_access_token()
        status, payload = http_json(
            "GET",
            CURRENTLY_PLAYING_URL + "?additional_types=track,episode",
            headers={"Authorization": f"Bearer {token}"},
        )
        if status == 204:
            return None
        if status == 401:
            self.token["expires_at"] = 0
            token = self.ensure_access_token()
            status, payload = http_json(
                "GET",
                CURRENTLY_PLAYING_URL + "?additional_types=track,episode",
                headers={"Authorization": f"Bearer {token}"},
            )
            if status == 204:
                return None
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"currently-playing failed ({status}): {payload}")
        return payload


def download_image(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers={"User-Agent": "spotify-vinyl-preview/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return Image.open(BytesIO(resp.read())).convert("RGB")


def downsample_to_matrix(art: Image.Image) -> list[tuple[int, int, int]]:
    fitted = art.resize((MATRIX, MATRIX), Image.Resampling.BOX)
    pixels: list[tuple[int, int, int]] = []
    for y in range(MATRIX):
        for x in range(MATRIX):
            pixels.append(fitted.getpixel((x, y)))  # type: ignore[arg-type]
    return pixels


def render_vinyl(
    art_pixels: list[tuple[int, int, int]] | None,
    angle_deg: float,
) -> list[list[int]]:
    """Same idea as ESP32 firmware: circular disc + label + hole + rotation."""
    out = blank_pixels()
    if art_pixels is None:
        # idle ring like clock outline
        cx = (MATRIX - 1) * 0.5
        cy = (MATRIX - 1) * 0.5
        radius = MATRIX * 0.5 - 0.7
        for y in range(MATRIX):
            for x in range(MATRIX):
                dx = x - cx
                dy = y - cy
                dist = math.sqrt(dx * dx + dy * dy)
                if radius - 0.55 < dist < radius + 0.35:
                    out[y * MATRIX + x] = [28, 28, 32]
        return out

    cx = (MATRIX - 1) * 0.5
    cy = (MATRIX - 1) * 0.5
    radius = MATRIX * 0.5 - 0.6
    label_r = radius * 0.22
    hole_r = radius * 0.08
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)

    def sample(fx: float, fy: float) -> tuple[int, int, int]:
        x = int(math.floor(fx))
        y = int(math.floor(fy))
        if x < 0 or y < 0 or x >= MATRIX or y >= MATRIX:
            return (0, 0, 0)
        return art_pixels[y * MATRIX + x]

    for y in range(MATRIX):
        for x in range(MATRIX):
            dx = x - cx
            dy = y - cy
            dist = math.sqrt(dx * dx + dy * dy)
            color = (0, 0, 0)
            if dist <= radius:
                sx = cos_a * dx + sin_a * dy + cx
                sy = -sin_a * dx + cos_a * dy + cy
                r, g, b = sample(sx, sy)
                if dist <= hole_r:
                    r = g = b = 0
                elif dist <= label_r:
                    r, g, b = int(r * 0.18), int(g * 0.18), int(b * 0.18)
                if dist > radius - 0.85:
                    r, g, b = int(r * 0.55), int(g * 0.55), int(b * 0.55)
                color = (r, g, b)
            out[y * MATRIX + x] = [color[0], color[1], color[2]]
    return out


def parse_playback(playback: dict[str, Any] | None) -> tuple[bool, bool, str, str, str | None, str | None]:
    if not playback:
        return False, False, "", "", None, None
    item = playback.get("item") or {}
    if not item:
        return False, False, "", "", None, None

    is_playing = bool(playback.get("is_playing"))
    track_id = item.get("id")
    title = item.get("name") or ""
    if item.get("type") == "episode":
        artists = (item.get("show") or {}).get("name") or ""
        images = item.get("images") or []
    else:
        artists = ", ".join(a.get("name", "") for a in (item.get("artists") or []))
        images = (item.get("album") or {}).get("images") or []

    image_url = None
    if images:
        image_url = min(images, key=lambda img: img.get("width") or 10_000).get("url")
    return True, is_playing, title, artists, track_id, image_url


PAGE_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Spotify 16×16 preview</title>
  <style>
    :root {
      --bg: #111114;
      --panel: #1a1a1f;
      --text: #ececf1;
      --muted: #9a9aa6;
      --line: #2c2c34;
      --led: #050506;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .wrap {
      width: min(920px, 100%);
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 28px;
      align-items: center;
    }
    @media (max-width: 800px) {
      .wrap { grid-template-columns: 1fr; }
    }
    .stage {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 28px;
      display: grid;
      place-items: center;
      gap: 14px;
    }
    .matrix {
      width: min(360px, 80vw);
      aspect-ratio: 1;
      display: grid;
      grid-template-columns: repeat(16, 1fr);
      grid-template-rows: repeat(16, 1fr);
      gap: 3px;
      padding: 10px;
      background: #09090b;
      border-radius: 12px;
    }
    .led {
      border-radius: 2px;
      background: var(--led);
    }
    .meta h1 {
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: -0.03em;
      font-weight: 600;
    }
    .meta p { margin: 0 0 10px; color: var(--muted); line-height: 1.45; }
    .track {
      margin-top: 18px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--panel);
    }
    .track .title { font-size: 18px; margin-bottom: 4px; }
    .track .artists { color: var(--muted); font-size: 14px; }
    .badge {
      display: inline-block;
      margin-top: 12px;
      padding: 4px 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      font-size: 12px;
      color: var(--muted);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .hint { font-size: 13px; color: var(--muted); margin-top: 16px; }
    code {
      font-family: "IBM Plex Mono", ui-monospace, monospace;
      font-size: 12px;
      color: #d7d7e0;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="stage">
      <div class="matrix" id="matrix"></div>
      <div class="badge" id="mode">connecting</div>
    </div>
    <div class="meta">
      <h1>Virtual 16×16</h1>
      <p>Живой превью с реального Spotify: обложка жмётся в 16×16 и крутится как пластинка — так же, как будет на матрице.</p>
      <div class="track">
        <div class="title" id="title">Ждём трек…</div>
        <div class="artists" id="artists">Включи что-нибудь в Spotify</div>
      </div>
      <p class="hint">Статус: <code id="status">boot</code></p>
    </div>
  </div>
  <script>
    const matrix = document.getElementById("matrix");
    const leds = [];
    for (let i = 0; i < 256; i++) {
      const d = document.createElement("div");
      d.className = "led";
      matrix.appendChild(d);
      leds.push(d);
    }

    async function tick() {
      try {
        const res = await fetch("/api/frame");
        const data = await res.json();
        for (let i = 0; i < 256; i++) {
          const [r, g, b] = data.pixels[i];
          leds[i].style.background = `rgb(${r},${g},${b})`;
        }
        document.getElementById("title").textContent = data.has_track ? data.title : "Ничего не играет";
        document.getElementById("artists").textContent = data.has_track ? data.artists : "Включи трек в Spotify";
        document.getElementById("status").textContent = data.status;
        document.getElementById("mode").textContent = data.has_track
          ? (data.is_playing ? "playing · vinyl" : "paused · vinyl")
          : "idle";
      } catch (err) {
        document.getElementById("status").textContent = String(err);
      }
    }
    tick();
    setInterval(tick, 80);
  </script>
</body>
</html>
"""


def make_handler(state: FrameState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path.startswith("/index"):
                body = PAGE_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/api/frame"):
                with state.lock:
                    payload = {
                        "pixels": state.pixels,
                        "is_playing": state.is_playing,
                        "has_track": state.has_track,
                        "title": state.title,
                        "artists": state.artists,
                        "track_id": state.track_id,
                        "angle": state.angle,
                        "status": state.status,
                        "updated_at": state.updated_at,
                    }
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            self.send_response(404)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def poll_loop(session: SpotifySession, state: FrameState) -> None:
    art_pixels: list[tuple[int, int, int]] | None = None
    loaded_id: str | None = None
    rpm = 18.0
    last_anim = time.monotonic()
    last_poll = 0.0

    while True:
        now = time.monotonic()
        dt = now - last_anim
        last_anim = now

        if now - last_poll >= 3.0:
            last_poll = now
            try:
                playback = session.currently_playing()
                has_track, is_playing, title, artists, track_id, image_url = parse_playback(playback)

                if has_track and image_url and track_id != loaded_id:
                    print(f"Loading art for: {title} — {artists}")
                    art = download_image(image_url)
                    art_pixels = downsample_to_matrix(art)
                    loaded_id = track_id
                    with state.lock:
                        state.angle = 0.0

                if not has_track:
                    art_pixels = None
                    loaded_id = None

                with state.lock:
                    state.has_track = has_track
                    state.is_playing = is_playing
                    state.title = title
                    state.artists = artists
                    state.track_id = track_id
                    state.status = (
                        "playing"
                        if has_track and is_playing
                        else "paused"
                        if has_track
                        else "idle · no track"
                    )
            except Exception as exc:  # noqa: BLE001
                with state.lock:
                    state.status = f"error: {exc}"
                print("Spotify poll error:", exc)

        with state.lock:
            if state.has_track and state.is_playing:
                state.angle = (state.angle - 360.0 * (rpm / 60.0) * dt) % 360.0
            angle = state.angle
            has_track = state.has_track
            state.pixels = render_vinyl(art_pixels if has_track else None, angle)
            state.updated_at = time.time()

        time.sleep(1 / 20)


def main() -> None:
    client_id, client_secret = require_creds()
    if not TOKEN_CACHE.exists():
        raise SystemExit(
            "No .cache/spotify_token.json yet.\n"
            "Run first: python3 scripts/get_spotify_token.py"
        )

    session = SpotifySession(client_id, client_secret)
    state = FrameState(
        lock=threading.Lock(),
        pixels=blank_pixels(),
        is_playing=False,
        has_track=False,
        title="",
        artists="",
        track_id=None,
        angle=0.0,
        status="starting",
        updated_at=time.time(),
    )

    thread = threading.Thread(target=poll_loop, args=(session, state), daemon=True)
    thread.start()

    server = ThreadingHTTPServer((HOST, PORT), make_handler(state))
    url = f"http://{HOST}:{PORT}"
    print(f"Virtual matrix: {url}")
    print("Play something on Spotify, watch the 16x16 disc update.")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
