#include <Arduino.h>
#include <WiFi.h>

#include "clock_face.h"
#include "config.h"
#include "matrix_display.h"
#include "secrets.h"
#include "spotify_client.h"
#include "vinyl.h"

namespace {

CRGB gArt[kNumLeds];
CRGB gFrame[kNumLeds];
PlaybackInfo gPlayback;
String gLoadedTrackId;
uint32_t gLastPollMs = 0;
uint32_t gLastFrameMs = 0;
bool gHasArt = false;

void connectWifi() {
  Serial.printf("WiFi: connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - start) < 30000) {
    delay(400);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi: OK ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("WiFi: failed — check secrets.h");
  }
}

void pollSpotify() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  PlaybackInfo info;
  if (!spotifyFetchPlayback(info)) {
    return;
  }

  gPlayback = info;
  if (!info.hasTrack || info.imageUrl.length() == 0) {
    gHasArt = false;
    gLoadedTrackId = "";
    return;
  }

  if (info.trackId != gLoadedTrackId) {
    Serial.printf("Spotify: new track %s\n", info.trackId.c_str());
    if (spotifyDownloadArt(info.imageUrl, gArt)) {
      gHasArt = true;
      gLoadedTrackId = info.trackId;
      vinylResetAngle();
      Serial.println("Spotify: art loaded");
    } else {
      Serial.println("Spotify: art download/decode failed");
    }
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println();
  Serial.println("spotify-vinyl-matrix boot");

  matrixBegin();
  vinylMakeDemoArt(gArt);
  gHasArt = true;

  connectWifi();
  configTime(kGmtOffsetSec, kDaylightOffsetSec, "pool.ntp.org", "time.nist.gov");

  if (WiFi.status() == WL_CONNECTED) {
    if (!spotifyBegin()) {
      Serial.println("Spotify: auth failed — check Client ID/Secret/Refresh token");
    }
  }

  gLastPollMs = millis() - kSpotifyPollMs;
  gLastFrameMs = millis();
}

void loop() {
  const uint32_t now = millis();

  if (now - gLastPollMs >= kSpotifyPollMs) {
    gLastPollMs = now;
    pollSpotify();
  }

  const float deltaSec = (now - gLastFrameMs) / 1000.0f;
  gLastFrameMs = now;

  const bool showVinyl = gPlayback.hasTrack && gHasArt;
  if (showVinyl) {
    vinylAdvance(deltaSec, gPlayback.isPlaying);
    vinylRender(gArt, gFrame);
  } else {
    clockRender(gFrame);
  }

  matrixBlit(gFrame);
  matrixShow();

  const uint32_t frameBudget = 1000UL / kTargetFps;
  const uint32_t elapsed = millis() - now;
  if (elapsed < frameBudget) {
    delay(frameBudget - elapsed);
  }
}
