#pragma once

#include <Arduino.h>
#include <FastLED.h>

#include "config.h"

void matrixBegin();
void matrixClear();
void matrixShow();
uint16_t matrixXY(uint8_t x, uint8_t y);
CRGB* matrixLeds();
void matrixSetPixel(uint8_t x, uint8_t y, CRGB color);
void matrixBlit(const CRGB* frame);
