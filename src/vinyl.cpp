#include "vinyl.h"

#include <math.h>

namespace {

float gAngleDeg = 0.0f;

inline float degToRad(float deg) {
  return deg * 0.017453292519943295f;
}

CRGB sampleArt(const CRGB* art, float fx, float fy) {
  // Nearest-neighbor sample in art space [0..W)
  int x = (int)floorf(fx);
  int y = (int)floorf(fy);
  if (x < 0 || y < 0 || x >= kMatrixWidth || y >= kMatrixHeight) {
    return CRGB::Black;
  }
  return art[y * kMatrixWidth + x];
}

}  // namespace

void vinylResetAngle() {
  gAngleDeg = 0.0f;
}

void vinylAdvance(float deltaSec, bool spinning) {
  if (!spinning) {
    return;
  }
  gAngleDeg = fmodf(gAngleDeg - (360.0f * (kVinylRpm / 60.0f) * deltaSec), 360.0f);
  if (gAngleDeg < 0.0f) {
    gAngleDeg += 360.0f;
  }
}

void vinylMakeDemoArt(CRGB* art) {
  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      const uint8_t qx = x < 8;
      const uint8_t qy = y < 8;
      CRGB c;
      if (qx && qy) {
        c = CRGB(220, 60, 55);
      } else if (!qx && qy) {
        c = CRGB(240, 180, 40);
      } else if (qx && !qy) {
        c = CRGB(40, 140, 230);
      } else {
        c = CRGB(50, 190, 90);
      }
      art[y * kMatrixWidth + x] = c;
    }
  }
}

void vinylRender(const CRGB* art, CRGB* outFrame) {
  const float cx = (kMatrixWidth - 1) * 0.5f;
  const float cy = (kMatrixHeight - 1) * 0.5f;
  const float radius = (kMatrixWidth * 0.5f) - 0.6f;
  const float labelR = radius * 0.22f;
  const float holeR = radius * 0.08f;
  const float cosA = cosf(degToRad(gAngleDeg));
  const float sinA = sinf(degToRad(gAngleDeg));

  for (uint8_t y = 0; y < kMatrixHeight; ++y) {
    for (uint8_t x = 0; x < kMatrixWidth; ++x) {
      const float dx = (float)x - cx;
      const float dy = (float)y - cy;
      const float dist = sqrtf(dx * dx + dy * dy);
      CRGB color = CRGB::Black;

      if (dist <= radius) {
        // Inverse rotate destination -> source art coordinates.
        const float sx = cosA * dx + sinA * dy + cx;
        const float sy = -sinA * dx + cosA * dy + cy;
        color = sampleArt(art, sx, sy);

        // Dark label + spindle hole, like a record.
        if (dist <= holeR) {
          color = CRGB::Black;
        } else if (dist <= labelR) {
          color.nscale8(45);
        }

        // Soft outer rim.
        if (dist > radius - 0.85f) {
          color.nscale8(140);
        }
      }

      outFrame[y * kMatrixWidth + x] = color;
    }
  }
}
