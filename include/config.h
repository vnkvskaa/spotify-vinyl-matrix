#pragma once

// Hardware
static constexpr uint8_t kLedPin = 13;          // DIN на этот GPIO
static constexpr uint8_t kMatrixWidth = 16;
static constexpr uint8_t kMatrixHeight = 16;
static constexpr uint16_t kNumLeds = kMatrixWidth * kMatrixHeight;

// Большинство дешёвых 16x16 идут «змейкой». Если картинка зеркальная —
// поменяй kMatrixSerpentine / kMatrixVertical / kMatrixFlipX / kMatrixFlipY.
static constexpr bool kMatrixSerpentine = true;
static constexpr bool kMatrixVertical = false;
static constexpr bool kMatrixFlipX = false;
static constexpr bool kMatrixFlipY = false;

// Display
static constexpr uint8_t kBrightness = 48;      // 16–64 комфортно для рамки
static constexpr float kVinylRpm = 18.0f;        // скорость вращения пластинки
static constexpr uint8_t kTargetFps = 20;

// Spotify polling
static constexpr uint32_t kSpotifyPollMs = 4000;
static constexpr uint32_t kTokenRefreshSkewMs = 60000;

// NTP / clock (Москва UTC+3). Для другого пояса поменяй kGmtOffsetSec.
static constexpr long kGmtOffsetSec = 3 * 3600;
static constexpr int kDaylightOffsetSec = 0;
