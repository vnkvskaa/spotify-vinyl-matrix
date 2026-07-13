#include "clock_face.h"

#include <math.h>
#include <time.h>

namespace {

// Tiny 3x5 digits, bit MSB left.
const uint8_t kDigits[10][5] = {
    {0b111, 0b101, 0b101, 0b101, 0b111},  // 0
    {0b010, 0b110, 0b010, 0b010, 0b111},  // 1
    {0b111, 0b001, 0b111, 0b100, 0b111},  // 2
    {0b111, 0b001, 0b111, 0b001, 0b111},  // 3
    {0b101, 0b101, 0b111, 0b001, 0b001},  // 4
    {0b111, 0b100, 0b111, 0b001, 0b111},  // 5
    {0b111, 0b100, 0b111, 0b101, 0b111},  // 6
    {0b111, 0b001, 0b001, 0b001, 0b001},  // 7
    {0b111, 0b101, 0b111, 0b101, 0b111},  // 8
    {0b111, 0b101, 0b111, 0b001, 0b111},  // 9
};

void drawDigit(CRGB* frame, int originX, int originY, int digit, CRGB color) {
  if (digit < 0 || digit > 9) {
    return;
  }
  for (int row = 0; row < 5; ++row) {
    for (int col = 0; col < 3; ++col) {
      if (kDigits[digit][row] & (0b100 >> col)) {
        const int x = originX + col;
        const int y = originY + row;
        if (x >= 0 && y >= 0 && x < kMatrixWidth && y < kMatrixHeight) {
          frame[y * kMatrixWidth + x] = color;
        }
      }
    }
  }
}

}  // namespace

void clockRender(CRGB* outFrame) {
  for (uint16_t i = 0; i < kNumLeds; ++i) {
    outFrame[i] = CRGB(0, 0, 0);
  }

  // Subtle idle disc outline.
  const float cx = (kMatrixWidth - 1) * 0.5f;
  const float cy = (kMatrixHeight - 1) * 0.5f;
  const float radius = (kMatrixWidth * 0.5f) - 0.7f;
  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      const float dx = (float)x - cx;
      const float dy = (float)y - cy;
      const float dist = sqrtf(dx * dx + dy * dy);
      if (dist > radius - 0.55f && dist < radius + 0.35f) {
        outFrame[y * kMatrixWidth + x] = CRGB(28, 28, 32);
      }
    }
  }

  time_t now = time(nullptr);
  struct tm localTm;
  localtime_r(&now, &localTm);

  // If NTP not ready yet, show pulsing center.
  if (localTm.tm_year < (2024 - 1900)) {
    const uint8_t pulse = beatsin8(24, 20, 90);
    outFrame[8 * kMatrixWidth + 7] = CRGB(pulse, pulse, pulse);
    outFrame[8 * kMatrixWidth + 8] = CRGB(pulse, pulse, pulse);
    outFrame[7 * kMatrixWidth + 7] = CRGB(pulse, pulse, pulse);
    outFrame[7 * kMatrixWidth + 8] = CRGB(pulse, pulse, pulse);
    return;
  }

  const int hour = localTm.tm_hour;
  const int minute = localTm.tm_min;
  const CRGB color(180, 190, 210);

  // HH on top row, MM on bottom. Digits are 3x5 with a 1px gap.
  drawDigit(outFrame, 4, 2, hour / 10, color);
  drawDigit(outFrame, 9, 2, hour % 10, color);
  drawDigit(outFrame, 4, 9, minute / 10, color);
  drawDigit(outFrame, 9, 9, minute % 10, color);

  if ((localTm.tm_sec % 2) == 0) {
    outFrame[7 * kMatrixWidth + 7] = color;
    outFrame[7 * kMatrixWidth + 8] = color;
  }
}
