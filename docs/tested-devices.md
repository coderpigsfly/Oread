# Tested devices

The devices Oread has been tested with, and the versions they ran.

## Listening devices

| Device | Connects with | Versions | Audio | Speech model | Hears its own speaker | In the tests |
| --- | --- | --- | --- | --- | --- | --- |
| [Home Assistant Voice PE](https://www.home-assistant.io/voice-pe/) | Home Assistant (ESPHome) | firmware 25.10.0 | 16 kHz | Parakeet | yes | `voice-pe` |
| EcoPad Android tablet (low-end) | [Ava Pro](https://github.com/knoop7/Ava-Pro), to Home Assistant (ESPHome) | Android 10, Ava Pro 0.7.7 | 16 kHz | Parakeet | yes | `tablet` |
| Lenovo IdeaPad 1 15ALC7 | `tools/client.py` | Ubuntu 24.04 | 48 kHz and 16 kHz | Moonshine | no | `laptop` |

The listening devices talk to [Home Assistant](https://github.com/home-assistant/core);
Home Assistant sends Oread the audio over the Wyoming protocol, one port per device.

## Server

| | |
| --- | --- |
| Machine | VM on an Intel Xeon E5-2650 (2012, no AVX2) |
| Cores | 4 for the model charts; 1, 2 and 4 (Docker limits) for the cores chart |
| OS | Ubuntu 24.04 |
| Docker | 29.9.1, Compose 5.6.0 |

## Browsers

Chromium (Chrome, Edge), Firefox and WebKit (Safari's engine), at laptop and
phone sizes, by `tests/web_test.py`.
