#pragma once

#include <Arduino.h>
#include <FastLED.h>

#include "config.h"

struct PlaybackInfo {
  bool hasTrack = false;
  bool isPlaying = false;
  String trackId;
  String imageUrl;
};

bool spotifyBegin();
bool spotifyEnsureToken();
bool spotifyFetchPlayback(PlaybackInfo& info);
bool spotifyDownloadArt(const String& url, CRGB* art16x16);
