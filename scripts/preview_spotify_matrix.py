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
    art: list[list[int]] | None
    is_playing: bool
    has_track: bool
    title: str
    artists: str
    track_id: str | None
    status: str
    updated_at: float
    art_version: int
    progress: float


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


def parse_playback(playback: dict[str, Any] | None) -> tuple[bool, bool, str, str, str | None, str | None, float]:
    if not playback:
        return False, False, "", "", None, None, 0.0
    item = playback.get("item") or {}
    if not item:
        return False, False, "", "", None, None, 0.0

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

    progress = 0.0
    duration = int(item.get("duration_ms") or 0)
    progress_ms = int(playback.get("progress_ms") or 0)
    if duration > 0:
        progress = max(0.0, min(1.0, progress_ms / duration))

    return True, is_playing, title, artists, track_id, image_url, progress


PREVIEW_HTML = ROOT / "preview" / "index.html"
CLOCK_GALLERY_HTML = ROOT / "preview" / "clock-gallery.html"


def load_preview_html() -> bytes:
    if not PREVIEW_HTML.exists():
        raise FileNotFoundError(f"Missing preview page: {PREVIEW_HTML}")
    return PREVIEW_HTML.read_bytes()


def load_clock_gallery_html() -> bytes:
    if not CLOCK_GALLERY_HTML.exists():
        raise FileNotFoundError(f"Missing clock gallery: {CLOCK_GALLERY_HTML}")
    return CLOCK_GALLERY_HTML.read_bytes()


def make_handler(state: FrameState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/" or self.path.startswith("/index"):
                body = load_preview_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/clocks"):
                body = load_clock_gallery_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/api/meta"):
                with state.lock:
                    payload = {
                        "art_version": state.art_version,
                        "is_playing": state.is_playing,
                        "has_track": state.has_track,
                        "title": state.title,
                        "artists": state.artists,
                        "track_id": state.track_id,
                        "status": state.status,
                        "updated_at": state.updated_at,
                        "progress": state.progress,
                    }
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/api/art"):
                with state.lock:
                    payload = {
                        "art": state.art,
                        "art_version": state.art_version,
                    }
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/api/state") or self.path.startswith("/api/frame"):
                with state.lock:
                    payload = {
                        "art": state.art,
                        "art_version": state.art_version,
                        "is_playing": state.is_playing,
                        "has_track": state.has_track,
                        "title": state.title,
                        "artists": state.artists,
                        "track_id": state.track_id,
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


def spotify_poll_loop(session: SpotifySession, state: FrameState) -> None:
    loaded_id: str | None = None

    while True:
        try:
            playback = session.currently_playing()
            has_track, is_playing, title, artists, track_id, image_url, progress = parse_playback(playback)

            if has_track and image_url and track_id != loaded_id:
                print(f"Loading art for: {title} — {artists}")
                art = download_image(image_url)
                art_pixels = [[c[0], c[1], c[2]] for c in downsample_to_matrix(art)]
                loaded_id = track_id
                with state.lock:
                    state.art = art_pixels
                    state.art_version += 1

            if not has_track:
                with state.lock:
                    if state.art is not None or state.has_track:
                        state.art = None
                        state.art_version += 1
                loaded_id = None

            with state.lock:
                state.has_track = has_track
                state.is_playing = is_playing
                state.title = title
                state.artists = artists
                state.track_id = track_id
                state.progress = progress
                state.status = (
                    "playing"
                    if has_track and is_playing
                    else "paused"
                    if has_track
                    else "idle · no track"
                )
                state.updated_at = time.time()
        except Exception as exc:  # noqa: BLE001
            with state.lock:
                state.status = f"error: {exc}"
            print("Spotify poll error:", exc)

        time.sleep(4.0)


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
        art=None,
        is_playing=False,
        has_track=False,
        title="",
        artists="",
        track_id=None,
        status="starting",
        updated_at=time.time(),
        art_version=0,
        progress=0.0,
    )

    thread = threading.Thread(target=spotify_poll_loop, args=(session, state), daemon=True)
    thread.start()

    server = ThreadingHTTPServer((HOST, PORT), make_handler(state))
    url = f"http://{HOST}:{PORT}"
    print(f"Virtual matrix: {url}")
    print(f"Clock gallery: {url}/clocks")
    print("Play something on Spotify, watch the 16x16 disc update.")
    print("Restart this script if it was already running, then refresh the browser.")
    webbrowser.open(f"{url}/clocks")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
