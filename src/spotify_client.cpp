#include "spotify_client.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <climits>
#include <cstring>
#include <mbedtls/base64.h>

#include <ArduinoJson.h>
#include <JPEGDEC.h>

#include "secrets.h"

namespace {

String gAccessToken;
uint32_t gAccessTokenExpiresAtMs = 0;

JPEGDEC gJpeg;
CRGB* gArtTarget = nullptr;

struct AccumulateContext {
  uint16_t srcW = 0;
  uint16_t srcH = 0;
  uint32_t sumR[kNumLeds]{};
  uint32_t sumG[kNumLeds]{};
  uint32_t sumB[kNumLeds]{};
  uint16_t count[kNumLeds]{};
};

AccumulateContext gAcc;

int jpegDrawCallback(JPEGDRAW* draw) {
  if (!draw || gAcc.srcW == 0 || gAcc.srcH == 0) {
    return 0;
  }

  const uint16_t* pixels = draw->pPixels;
  for (int y = 0; y < draw->iHeight; ++y) {
    for (int x = 0; x < draw->iWidth; ++x) {
      const int srcX = draw->x + x;
      const int srcY = draw->y + y;
      if (srcX < 0 || srcY < 0 || srcX >= gAcc.srcW || srcY >= gAcc.srcH) {
        continue;
      }

      const int dstX = (srcX * kMatrixWidth) / gAcc.srcW;
      const int dstY = (srcY * kMatrixHeight) / gAcc.srcH;
      if (dstX < 0 || dstY < 0 || dstX >= kMatrixWidth || dstY >= kMatrixHeight) {
        continue;
      }

      const uint16_t idx = dstY * kMatrixWidth + dstX;
      const uint16_t pixel = pixels[y * draw->iWidth + x];
      const uint8_t r = ((pixel >> 11) & 0x1F) << 3;
      const uint8_t g = ((pixel >> 5) & 0x3F) << 2;
      const uint8_t b = (pixel & 0x1F) << 3;

      gAcc.sumR[idx] += r;
      gAcc.sumG[idx] += g;
      gAcc.sumB[idx] += b;
      gAcc.count[idx] += 1;
    }
  }
  return 1;
}

bool refreshAccessToken() {
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, "https://accounts.spotify.com/api/token")) {
    Serial.println("Spotify: token begin failed");
    return false;
  }

  const String credentials = String(SPOTIFY_CLIENT_ID) + ":" + String(SPOTIFY_CLIENT_SECRET);
  unsigned char encoded[256];
  size_t encodedLen = 0;
  if (mbedtls_base64_encode(
          encoded,
          sizeof(encoded) - 1,
          &encodedLen,
          reinterpret_cast<const unsigned char*>(credentials.c_str()),
          credentials.length()) != 0) {
    Serial.println("Spotify: base64 encode failed");
    http.end();
    return false;
  }
  encoded[encodedLen] = 0;
  http.addHeader("Authorization", String("Basic ") + reinterpret_cast<char*>(encoded));
  http.addHeader("Content-Type", "application/x-www-form-urlencoded");

  const String body = String("grant_type=refresh_token&refresh_token=") + SPOTIFY_REFRESH_TOKEN;
  const int code = http.POST(body);
  const String payload = http.getString();
  http.end();

  if (code != 200) {
    Serial.printf("Spotify: token HTTP %d: %s\n", code, payload.c_str());
    return false;
  }

  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.printf("Spotify: token JSON error: %s\n", err.c_str());
    return false;
  }

  const char* access = doc["access_token"];
  if (!access) {
    Serial.println("Spotify: access_token missing");
    return false;
  }

  gAccessToken = access;
  const uint32_t expiresInSec = doc["expires_in"] | 3600;
  gAccessTokenExpiresAtMs = millis() + expiresInSec * 1000UL - kTokenRefreshSkewMs;
  Serial.println("Spotify: access token refreshed");
  return true;
}

bool decodeJpegToArt(const uint8_t* data, int len, CRGB* art16x16) {
  memset(&gAcc, 0, sizeof(gAcc));
  gArtTarget = art16x16;

  if (!gJpeg.openRAM((uint8_t*)data, len, jpegDrawCallback)) {
    Serial.println("Spotify: JPEG open failed");
    return false;
  }

  gAcc.srcW = gJpeg.getWidth();
  gAcc.srcH = gJpeg.getHeight();
  if (gAcc.srcW == 0 || gAcc.srcH == 0) {
    gJpeg.close();
    return false;
  }

  // RGB565 is what the callback receives.
  gJpeg.setPixelType(RGB565_LITTLE_ENDIAN);
  const int ok = gJpeg.decode(0, 0, 0);
  gJpeg.close();
  if (!ok) {
    Serial.println("Spotify: JPEG decode failed");
    return false;
  }

  for (uint16_t i = 0; i < kNumLeds; ++i) {
    if (gAcc.count[i] == 0) {
      art16x16[i] = CRGB::Black;
      continue;
    }
    art16x16[i] = CRGB(
        gAcc.sumR[i] / gAcc.count[i],
        gAcc.sumG[i] / gAcc.count[i],
        gAcc.sumB[i] / gAcc.count[i]);
  }
  return true;
}

}  // namespace

bool spotifyBegin() {
  gAccessToken = "";
  gAccessTokenExpiresAtMs = 0;
  return spotifyEnsureToken();
}

bool spotifyEnsureToken() {
  if (gAccessToken.length() > 0 && (int32_t)(millis() - gAccessTokenExpiresAtMs) < 0) {
    return true;
  }
  return refreshAccessToken();
}

bool spotifyFetchPlayback(PlaybackInfo& info) {
  info = PlaybackInfo{};

  if (!spotifyEnsureToken()) {
    return false;
  }

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, "https://api.spotify.com/v1/me/player/currently-playing?additional_types=track,episode")) {
    return false;
  }
  http.addHeader("Authorization", "Bearer " + gAccessToken);

  const int code = http.GET();
  if (code == 204) {
    http.end();
    return true;  // nothing playing
  }

  if (code == 401) {
    http.end();
    gAccessToken = "";
    if (!refreshAccessToken()) {
      return false;
    }
    return spotifyFetchPlayback(info);
  }

  if (code == 429) {
    Serial.println("Spotify: rate limited");
    http.end();
    return false;
  }

  if (code != 200) {
    Serial.printf("Spotify: currently-playing HTTP %d\n", code);
    http.end();
    return false;
  }

  const String payload = http.getString();
  http.end();

  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, payload);
  if (err) {
    Serial.printf("Spotify: playback JSON error: %s\n", err.c_str());
    return false;
  }

  JsonObject item = doc["item"];
  if (item.isNull()) {
    return true;
  }

  info.hasTrack = true;
  info.isPlaying = doc["is_playing"] | false;
  const char* id = item["id"];
  info.trackId = id ? id : "";

  JsonArray images;
  const char* type = item["type"];
  if (type && strcmp(type, "episode") == 0) {
    images = item["images"].as<JsonArray>();
  } else {
    images = item["album"]["images"].as<JsonArray>();
  }

  if (images.isNull() || images.size() == 0) {
    return true;
  }

  // Prefer the smallest image to save RAM/time.
  int bestW = INT_MAX;
  const char* bestUrl = nullptr;
  for (JsonObject image : images) {
    const int w = image["width"] | 9999;
    const char* url = image["url"];
    if (url && w < bestW) {
      bestW = w;
      bestUrl = url;
    }
  }
  if (bestUrl) {
    info.imageUrl = bestUrl;
  }
  return true;
}

bool spotifyDownloadArt(const String& url, CRGB* art16x16) {
  if (url.length() == 0 || art16x16 == nullptr) {
    return false;
  }

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, url)) {
    Serial.println("Spotify: art begin failed");
    return false;
  }

  const int code = http.GET();
  if (code != 200) {
    Serial.printf("Spotify: art HTTP %d\n", code);
    http.end();
    return false;
  }

  const int len = http.getSize();
  // Keep a hard cap — album thumbs are usually small.
  if (len <= 0 || len > 120000) {
    Serial.printf("Spotify: unexpected art size %d\n", len);
    http.end();
    return false;
  }

  uint8_t* buffer = (uint8_t*)malloc(len);
  if (!buffer) {
    Serial.println("Spotify: art malloc failed");
    http.end();
    return false;
  }

  WiFiClient* stream = http.getStreamPtr();
  int readTotal = 0;
  const uint32_t start = millis();
  while (http.connected() && readTotal < len && (millis() - start) < 15000) {
    const size_t avail = stream->available();
    if (avail) {
      const int toRead = min((int)avail, len - readTotal);
      const int got = stream->readBytes(buffer + readTotal, toRead);
      readTotal += got;
    } else {
      delay(1);
    }
  }
  http.end();

  bool ok = false;
  if (readTotal == len) {
    ok = decodeJpegToArt(buffer, len, art16x16);
  } else {
    Serial.printf("Spotify: art incomplete %d/%d\n", readTotal, len);
  }

  free(buffer);
  return ok;
}
