# Spotify Vinyl Matrix (ESP32 + 16×16)

Пиксельная «виниловая пластинка» с обложкой текущего трека Spotify на матрице **WS2812 16×16** и плате **ESP32**.  
Когда музыка не играет — на экране **часы**.

Идея визуала близка к [tnarla/spotify-matrix](https://github.com/tnarla/spotify-matrix), но железо другое: не Raspberry Pi / 64×64 HUB75, а бюджетный ESP32 + NeoPixel-матрица.

## Что умеет

- Берёт currently playing из Spotify Web API
- Скачивает обложку, сжимает до 16×16
- Рисует круглый диск и крутит его, пока трек играет
- На паузе диск останавливается
- Если трека нет — показывает время (NTP, по умолчанию Москва UTC+3)

## Железо

- ESP32 DevKit (USB-C / micro-USB)
- Матрица **16×16 WS2812B / SK6812** (не HUB75)
- Блок питания **5V 3A** на матрицу + общий GND с ESP32
- Перемычки; DIN по умолчанию на **GPIO 13**

### Подключение

| Матрица | Куда |
|---------|------|
| 5V | БП 5V |
| GND | БП GND **и** ESP32 GND |
| DIN | ESP32 GPIO 13 (можно сменить в `include/config.h`) |

ESP32 питай отдельно по USB.

## Софт

Нужны:

1. [Visual Studio Code](https://code.visualstudio.com/) + расширение **PlatformIO**  
   или PlatformIO Core CLI
2. Аккаунт Spotify (обычно Premium для currently-playing)
3. Python 3 — только чтобы один раз получить refresh token

## Настройка Spotify

1. Открой [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/) → Create app
2. В Redirect URIs добавь **точно**:

```text
http://127.0.0.1:8888/callback
```

3. Скопируй Client ID и Client Secret
4. На компьютере:

```bash
python3 scripts/get_spotify_token.py
```

5. Скрипт выведет `SPOTIFY_REFRESH_TOKEN`

## Виртуальная матрица (пока нет железа)

Можно уже сейчас смотреть, как **реальные обложки Spotify** выглядят на 16×16:

1. Создай приложение на [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. Redirect URI: `http://127.0.0.1:8888/callback`
3. Скопируй `.env.example` → `.env` и впиши Client ID / Secret
4. Один раз получи токен:

```bash
pip install -r requirements-preview.txt
python3 scripts/get_spotify_token.py
```

5. Запусти превью:

```bash
python3 scripts/preview_spotify_matrix.py
```

Откроется `http://127.0.0.1:8765`: живой опрос Spotify → обложка → диск 16×16 с вращением.

## Прошивка

```bash
cp include/secrets.h.example include/secrets.h
```

Заполни `include/secrets.h`:

- Wi‑Fi
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`
- `SPOTIFY_REFRESH_TOKEN`

Потом:

```bash
pio run -t upload
pio device monitor
```

## Если картинка кривая

В `include/config.h` поиграй флагами:

- `kMatrixSerpentine`
- `kMatrixVertical`
- `kMatrixFlipX`
- `kMatrixFlipY`
- `kLedPin`
- `kBrightness`
- `kVinylRpm`
- `kGmtOffsetSec` (часовой пояс)

## Структура

```text
include/config.h          — пины, яркость, fps
include/secrets.h.example — шаблон секретов
src/main.cpp              — главный цикл
src/spotify_client.cpp    — Spotify + JPEG
src/vinyl.cpp             — диск / вращение
src/clock_face.cpp        — часы в idle
src/matrix_display.cpp    — FastLED / XY
scripts/get_spotify_token.py
```

## Дальше

Можно добавить режимы: погода, анимации, кнопка переключения. База уже разделена по модулям.

## Лицензия

MIT — делай что хочешь, будет круто увидеть твою рамку.
