#include "matrix_display.h"

static CRGB gLeds[kNumLeds];

void matrixBegin() {
  FastLED.addLeds<WS2812B, kLedPin, GRB>(gLeds, kNumLeds);
  FastLED.setBrightness(kBrightness);
  FastLED.clear(true);
}

void matrixClear() {
  FastLED.clear();
}

void matrixShow() {
  FastLED.show();
}

CRGB* matrixLeds() {
  return gLeds;
}

uint16_t matrixXY(uint8_t x, uint8_t y) {
  if (kMatrixFlipX) {
    x = kMatrixWidth - 1 - x;
  }
  if (kMatrixFlipY) {
    y = kMatrixHeight - 1 - y;
  }

  if (kMatrixVertical) {
    if (kMatrixSerpentine && (x & 1)) {
      return x * kMatrixHeight + (kMatrixHeight - 1 - y);
    }
    return x * kMatrixHeight + y;
  }

  if (kMatrixSerpentine && (y & 1)) {
    return y * kMatrixWidth + (kMatrixWidth - 1 - x);
  }
  return y * kMatrixWidth + x;
}

void matrixSetPixel(uint8_t x, uint8_t y, CRGB color) {
  if (x >= kMatrixWidth || y >= kMatrixHeight) {
    return;
  }
  gLeds[matrixXY(x, y)] = color;
}

void matrixBlit(const CRGB* frame) {
  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      gLeds[matrixXY(x, y)] = frame[y * kMatrixWidth + x];
    }
  }
}
