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

CRGB mix(CRGB a, CRGB b, uint8_t amount) {
  return a.lerp8(b, amount);
}

}  // namespace

void clockRender(CRGB* outFrame) {
  time_t nowSec = time(nullptr);
  struct tm localTm;
  localtime_r(&nowSec, &localTm);

  const float cx = (kMatrixWidth - 1) * 0.5f;
  const float cy = (kMatrixHeight - 1) * 0.5f;
  const uint8_t breath = beatsin8(12, 40, 110);

  // Soft day/night wash + watch disc + rim.
  const uint8_t hour = localTm.tm_hour;
  const uint8_t baseHue = qadd8(160, sin8(hour * 10) / 6);

  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      const float dx = (float)x - cx;
      const float dy = (float)y - cy;
      const float dist = sqrtf(dx * dx + dy * dy);

      CRGB c = CHSV(baseHue, 120, 12 + (uint8_t)((1.0f - dist / 11.0f) * 18.0f));

      if (dist <= 7.4f) {
        c = mix(c, CHSV(baseHue, 80, 28), 90);
      }
      if (dist > 6.9f && dist < 7.7f) {
        c = CHSV(baseHue + 12, 70, breath);
      }

      // Cardinal ticks roughly at top/right/bottom/left.
      const float ax = fabsf(dx);
      const float ay = fabsf(dy);
      if (dist > 6.5f && dist < 7.8f && ((ax < 0.65f && ay > 5.5f) || (ay < 0.65f && ax > 5.5f))) {
        c = CRGB(200, 210, 230);
      }

      outFrame[y * kMatrixWidth + x] = c;
    }
  }

  if (localTm.tm_year < (2024 - 1900)) {
    const uint8_t pulse = beatsin8(24, 20, 90);
    outFrame[8 * kMatrixWidth + 7] = CRGB(pulse, pulse, pulse);
    outFrame[8 * kMatrixWidth + 8] = CRGB(pulse, pulse, pulse);
    outFrame[7 * kMatrixWidth + 7] = CRGB(pulse, pulse, pulse);
    outFrame[7 * kMatrixWidth + 8] = CRGB(pulse, pulse, pulse);
    return;
  }

  // Seconds pearl on the rim.
  const float secAngle = -1.5707963f + (localTm.tm_sec / 60.0f) * 6.2831853f;
  const float pearlX = cx + cosf(secAngle) * 7.15f;
  const float pearlY = cy + sinf(secAngle) * 7.15f;
  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      const float ddx = (float)x - pearlX;
      const float ddy = (float)y - pearlY;
      if (ddx * ddx + ddy * ddy < 0.75f) {
        outFrame[y * kMatrixWidth + x] = CRGB(255, 240, 210);
      }
    }
  }

  // Dim minute hand.
  const float minAngle =
      -1.5707963f + ((localTm.tm_min + localTm.tm_sec / 60.0f) / 60.0f) * 6.2831853f;
  const float mcos = cosf(minAngle);
  const float msin = sinf(minAngle);
  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      const float dx = (float)x - cx;
      const float dy = (float)y - cy;
      const float along = dx * mcos + dy * msin;
      const float perp = fabsf(-dx * msin + dy * mcos);
      if (along > 0.8f && along < 5.2f && perp < 0.55f) {
        outFrame[y * kMatrixWidth + x] = mix(outFrame[y * kMatrixWidth + x], CRGB(140, 160, 200), 180);
      }
    }
  }

  const CRGB digitColor(220, 230, 250);
  drawDigit(outFrame, 3, 3, localTm.tm_hour / 10, digitColor);
  drawDigit(outFrame, 8, 3, localTm.tm_hour % 10, digitColor);
  drawDigit(outFrame, 3, 9, localTm.tm_min / 10, digitColor);
  drawDigit(outFrame, 8, 9, localTm.tm_min % 10, digitColor);

  if ((localTm.tm_sec % 2) == 0) {
    outFrame[7 * kMatrixWidth + 7] = CRGB(230, 235, 255);
    outFrame[7 * kMatrixWidth + 8] = CRGB(230, 235, 255);
    outFrame[8 * kMatrixWidth + 7] = CRGB(230, 235, 255);
    outFrame[8 * kMatrixWidth + 8] = CRGB(230, 235, 255);
  }
}
