#pragma once

#include <Arduino.h>
#include <FastLED.h>

#include "config.h"

void vinylResetAngle();
void vinylAdvance(float deltaSec, bool spinning);
void vinylRender(const CRGB* art, CRGB* outFrame);
void vinylMakeDemoArt(CRGB* art);
