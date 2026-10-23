# Changelog

Versions are year.month.release, the way Home Assistant numbers its own: 2026.10.0 is the first
release in October 2026, 2026.10.1 the next, 2026.11.0 the first in November. Before October 2026
they were 1.0.0 and 1.0.1.

## 2026.10.0

**Retrain: the device's waiting clips.** When a device's sound changes (a new microphone, a rebuilt
tablet), **People**, **Retrain** now shows the clips that device heard that nobody has assigned yet,
the ones closest to the person's voice first. Each can be assigned without leaving the page: to the
person, to one of the closest voices, to an assistant's own voice, to anyone else, or to "not a
person" (the clip is discarded). A clip closest to an assistant's own voice is hidden unless the
person is one of its two closest.

**The Wepwawet standard, version 2.** Oread's OpenAPI document names how a voice system speaks of it
(its spoken name), how long its data lives (a record), and the sound it takes in (the human voice).

**Versions** are numbered year.month.release, and `tools/release.py` refuses a version in another
form, a version that `oread/__init__.py` and `release.yaml` disagree on, or one with no section here.

## 1.0.1

- Tested devices link Ava Pro, Home Assistant and the Voice PE.
- The devices reach Home Assistant over ESPHome, and Home Assistant sends Oread the audio over
  Wyoming (it said Wyoming for the devices).

## 1.0.0

The first public release: speech to text and speaker ID on the processor alone, one listening port
per device, the Learn, People, Devices, Settings, Imports, Connections, Try it, Stats, Users and
Setup guide pages, and OSPRI gathering a record of every request.
