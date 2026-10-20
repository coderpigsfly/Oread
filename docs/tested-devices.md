# Tested devices

The devices Oread has been tested with, and the versions they ran.

## Listening devices

| Device | Connects with | Versions | Audio | Speech model | Hears its own speaker | In the tests |
| --- | --- | --- | --- | --- | --- | --- |
| Home Assistant Voice PE | Home Assistant (Wyoming) | firmware 25.10.0 | 16 kHz | Parakeet | yes | `voice-pe` |
| EcoPad Android tablet (low-end) | Ava Pro, to Home Assistant (Wyoming) | Android 10, Ava Pro 0.7.7 | 16 kHz | Parakeet | yes | `tablet` |
| Lenovo IdeaPad 1 15ALC7 | `tools/client.py` | Ubuntu 24.04 | 48 kHz and 16 kHz | Moonshine | no | `laptop` |

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
