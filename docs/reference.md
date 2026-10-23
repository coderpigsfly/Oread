# Oread: technical reference

How Oread works and how its parts fit, for people working on it. Setting it
up? Use the [user guide](user-guide.md). The overview is the
[README](../README.md).

## Run it

```bash
docker compose up -d --build
docker compose logs -f oread
```

The container runs as your user (1000:1000 unless `.env` says otherwise; see
`.env.example`), so `data/`, `logs/`, `models/` and `keys/` stay yours. The
empty folders ship in git so Docker never creates them as root.

On first start Oread downloads its speech-to-text model (about 240 MB) into
`models/`. After that it starts in a few seconds.

Settings live in `settings.yaml`. Keep your own changes in
`data/settings.yaml`, holding only what you change (same layout); it's
applied on top, so `git pull` never conflicts with them. Restart to apply.
Each listening device gets its own port (laptop 10310, voice-pe 10312,
tablet 10313 to start), and settings can be set for all devices, for a
device type, or for one device. Point each device's client (Home Assistant,
for example) at that device's port.

## First run and signing in

Open `https://<server>:10311/`. The first visit shows the setup screen: enter
the one-time setup code from Oread's log (`docker compose logs oread | grep
"setup code"`), then choose your username and a password (10 characters or
more). That account is the super user. Everyone else is added from there,
each with a role:

| Role | Can |
| --- | --- |
| super | everything, including the vault, permitted clients and other super users |
| administrator | devices, settings, API tokens, Home Assistant, reviewers and viewers |
| reviewer | listen to clips, assign them, create and rename profiles |
| viewer | look only: Stats, People, Devices, Settings |

Each role can grant only roles below its own. Passwords are kept only as
scrypt hashes in `data/users.json`; five wrong passwords in a row lock that
name for 15 minutes. Sessions last 12 hours unused, 30 days at most. Every
change, sign-in and refused sign-in goes in `logs/audit.jsonl`. Forgot the
password?

```bash
docker compose exec oread python -m oread.users reset <name>
```

The pages are plain JavaScript pinned to ECMAScript 2020, with no framework
and nothing loaded from the internet. They work in Chrome, Edge, Firefox and
Safari (14 and later), on a laptop, tablet or phone.

## HTTPS

Oread's pages and API are HTTPS only (`api.tls`):

- **household** (the default): Oread makes its own small certificate
  authority and certificate in `keys/`. Browsers warn until you install the
  authority on each device: download it from `https://<server>:10311/ca.crt`.
  Put the server's address and name in `api.tls_names` (for example
  `[192.168.1.20, myserver]`) so the certificate covers them.
- **files**: a certificate you got elsewhere (Let's Encrypt with a free
  DuckDNS name or your own domain, Tailscale, a reverse proxy):
  `api.cert_file` and `api.key_file`.
- **off**: plain HTTP, only behind a reverse proxy that does HTTPS.

Back up `keys/` apart from `data/`: it holds the vault key and the household
certificate authority.

## API tokens

People sign in to the pages; programs use API tokens. Each token has a role
like a person (administrator unless you pick another; never higher than your
own). Programs send it as `Authorization: Bearer oread_...`; on the API page
(`/docs`), press **Authorize** and paste it.

Make one token per program, so each can be revoked alone:
**POST /tokens**, **GET /tokens** (names, roles and last use),
**DELETE /tokens/{name}**. Tokens are stored only as fingerprints in
`data/tokens.json`. From the server:

```bash
docker compose exec oread python -m oread.auth create <name> [role]
docker compose exec oread python -m oread.auth list
docker compose exec oread python -m oread.auth revoke <name>
```

## What Oread costs to run

The **Stats** page (Resources), or **GET /resources**, reports memory (now and
peak), CPU (cores, average and recent use, the processor and whether it has
AVX2), disk (models in use, all downloaded
models, voice data, logs, free space) and request speed over the last 200
requests, overall and per device. Use it to judge what hardware Oread fits on.

**OSPRI records** (oread/ospri.py): with `gather: true` in `data/ospri.yaml` (the OSPRI page; **PATCH
/ospri**), each request without an error adds a line to `data/ospri/records.jsonl`: time, device,
speaker, label, score, guess, by, stt_model, voice_model, heard, audio_s, speech_s, clip. **GET
/ospri** says whether it's gathering, how many records and their dates; **GET
/ospri/records?format=json|csv** exports them with `misheard` (yes or no) and `meant`, joined in from
`data/mishearings.json` by the clip, else by the words heard (the mishearings' own key). Area `ospri`:
reviewers read, administrators switch it.

**Stats, Where the time goes** (oread/timing.py), or **GET /stats/time?tz=<IANA zone>**:
each request's time split into its steps, in order: speaking (the audio arriving: `receive`),
time in (`queue`), speech to text (`stt`; before Oct 18 only `stt+voiceprint` was timed, and all of it
counts here), voice ID beyond it (`stt+voiceprint` less `stt`), OSPRI (`ospri`, none until it's
built) and time to out (`match+save`, `publish`, `reply`). Each request adds a line to
`logs/time-steps.jsonl` ({t, d, s: the six steps}), kept `stats: keep_days` (400); the first start
fills it from `logs/requests.jsonl`. The report gives the last 24 hours and the last 14 days, 8 weeks
(from Monday) and 12 months in the page's time zone, each with its count and each step's median,
slowest 5 percent and average, all devices and each.

## Who may connect to the listening ports

The Wyoming protocol has no way to send a token, so the listening ports are
protected by a list of permitted clients instead: addresses or ranges, set on
the **Connections** page (or **PUT /access**). Anything else is hung up on
before it can send audio. The page also shows the last 20 refused
connections, handy for spotting an address you forgot. An empty list lets
any local-network address connect, never one from the internet.

## Keys Oread uses to reach other programs (the vault)

API tokens are for things calling Oread. The vault is the other direction:
keys and tokens Oread sends when it calls another program (a Home Assistant
long-lived token, the router, MQTT). With the API, **PUT /vault/{name}**
with `{"value": "...", "service": "home-assistant", "note": "..."}` adds or
replaces one; **GET /vault** lists names, labels, the last 4 characters and
when each was last used; **DELETE /vault/{name}** removes one. The API never
gives a key back. From the server (the key is asked for, so it stays out of
shell history):

```
docker compose exec oread python -m oread.vault set home-assistant home-assistant
docker compose exec oread python -m oread.vault list
```

Keys are encrypted in `data/vault.json`. The encryption key is made on first
start in `keys/oread.key` (or comes from the `OREAD_VAULT_KEY` environment
variable), apart from `data/`, so a copy of `data/` holds no usable keys.
**Back up `keys/oread.key` separately.** Without it the stored keys can't be
read and have to be entered again (GET /vault marks them `readable: false`).

## Telling Home Assistant who spoke

Home Assistant's Wyoming integration keeps only the text of Oread's reply and
drops who spoke. Two ways to get it there:

- **Without the intent router:** Oread sets `sensor.oread_<device>_speaker` in
  Home Assistant (state = the person, or `unknown`; attributes: label, guess,
  score, by, clip, heard_at) just before each reply, so it's current when
  Home Assistant passes the text on, and automations can use it (only for
  devices with `publish_speaker` on; off by default). Set
  `home_assistant.url` in `data/settings.yaml`, put a Home Assistant long-lived
  access token in the vault (`PUT /vault/home-assistant`), and check with
  **POST /home-assistant/test**. **GET /home-assistant** shows the last
  attempt. A slow or down Home Assistant never holds a reply more than
  `timeout_s` (0.5 s). Home Assistant's history records these sensors;
  exclude `sensor.oread_*` in its recorder if that isn't wanted.
- **With the intent router:** the router sits on the audio path (Home
  Assistant → router → Oread), reads the speaker straight from Oread's reply
  and passes only the text on. Turn publishing off for the devices it serves:
  untick **Report who spoke** for that device on Settings, Devices
  (`publish_speaker: false` on **PATCH /settings/speaker?device=...**).
- **Oread with the router (oread/mishearings.py, stage 1):** `data/wepwawet.yaml` keeps the
  address and the Wepwawet page's switches: `enabled`, `people_sync`, `nightly_pull`, `pull_hour`.
  **GET /wepwawet** (the page's view, with Oread's people beside the router's column), **PATCH
  /wepwawet** (the switches), **POST /wepwawet/people** (add the missing ones). With people_sync on,
  creating, renaming or deleting a person posts `{action: add | rename | remove, name, was}` to the
  router's `POST /people/oread`; the profile's response carries `wepwawet` (what the router did).
  The nightly pull runs once a day at `pull_hour` (checked every 5 minutes).
- **An assistant's own voice (the patch):** a profile of `kind: assistant` (POST /profiles with
  kind) is left out of matching unless the device's `hears_own_speaker` switch is on (PATCH
  /settings/speaker); then a known match on it carries `own_voice: true` in the Transcript's
  context. **GET /profiles** lists people only; `?all=true` adds the assistants' voices.
- **An assistant's voice learned from her text-to-speech (oread/assistant_voice.py):** for
  each device with `hears_own_speaker` on and a Home Assistant device matched, Oread reads the values
  of that device's selects (POST /api/template) and Home Assistant's pipelines (its websocket,
  `assist_pipeline/pipeline/list`; the `websockets` library); a select whose value is a pipeline's
  name (or `preferred`) gives the pipeline, and its `tts_engine`, `tts_voice` and `tts_language` the
  voice. Each line of `oread/voice_lines.txt` (or `data/voice_lines.txt`) is said by Home Assistant
  (POST /api/tts_get_url, 16 kHz mono WAV) and saved as a made clip (`device: tts`, `made: {engine,
  voice, language}`) on a profile of `kind: assistant` with `voice:` set, named after the voice. Once
  per voice: when the switch is turned on, at start, and on **POST /assistant-voices/learn**
  (`again: true` learns them over, keeping the profile's name); **GET /assistant-voices** shows the
  last look. Deleting the profile deletes its made clips.
- **Her voice from the router's echoes:** the router's GET /learn/mishearings also
  carries `echoes` (each request that was her own answer coming back, with its clip: clip, device,
  heard, when, by: words or voice). Each pull hands them to the assistant voices: a clip found by her
  words, still here and not assigned, is assigned (by `house router`, kind `echo`) to the learned
  voice whose `voice.devices` holds its device (set each time Oread looks). The pull's summary
  carries `echoes: {taught, already, not_here, no_voice, by_voice, refused}`. A profile's voiceprint
  is the mean of its clips, but once it has `assistant_voice: real_clips_first` (5) heard clips, of
  those alone. GET /profiles gives each profile's `made` count. The page shows it all on Settings,
  Devices, under each device's switch; People shows people only.
- **Explore (oread/explore.py):** **GET /explore** gives `clips` (one row per clip heard,
  made ones left out) and `words` (each word of each mishearing with a meaning, compared with
  difflib: right, swapped, dropped, added) as flat rows. The page (PivotTable.js 2.23.0 with jQuery
  3.7.1 and jQuery UI 1.13.3, all MIT, in `oread/web/vendor/`, loaded only on that page) adds the
  local day, hour, weekday, month, bands of the numbers, and `Wrong` for words; its own aggregator
  "Share that are yes (95% range)" gives a Wilson interval. The layout is kept per browser.
- **The router's mishearings (oread/mishearings.py):** with `wepwawet: url` set
  (or the address saved on the Mishearings page, kept in `data/wepwawet.yaml`)
  and the router's token for its oread door in the vault (`wepwawet`),
  **POST /mishearings/pull** reads the router's GET /learn/mishearings and merges
  it into `data/mishearings.json`: lines by their words (capitals and
  punctuation aside), each clip looked up here (its `heard_with`, kept with the
  line) and marked `kept_for: mishearing` so the review list never trims it; a
  line the router dropped stays, `gone`. **GET /mishearings** is the page's view.

The same address and token read each matched device's own settings in the
voice assistant (Home Assistant is the one Oread connects to today, through
oread/publish.py; nothing else in Oread is tied to it): every number, select
and switch of the device a listening device is matched to (`assistant_device`
on **PATCH /devices/{name}**, from **GET /assistant/devices**; Settings,
Devices, **Voice assistant device**; the old key `ha_device` in
`data/devices.yaml` is still read). Read in the background, at most once a
minute per device and never while a request waits; each clip keeps the last
reading as `assistant_settings` (`read_at`, `values`; clips from Oct 16 before
this change call it `ha`). Try it requests don't read it.

## Devices

On the **Devices** page, add a device with a name and type. Oread picks the
next free port (from `server.port_range`, 10310-10339), starts listening at
once, and shows the address to copy into the client. The same page renames a
device (its port and clips go with it), removes one (its clips are kept),
picks each device's speech and voice models, and compares models on the
device's own clips when asked. The API equivalents are **POST**, **PATCH**
and **DELETE /devices**.

Device types (a Voice PE, an Android tablet, a laptop) come from
`device-types.yaml`, with your own in `data/device-types.yaml` on top. Each
has a label, an optional note, and optional starting `stt` / `speaker`
settings for every device of that type (a device's own settings still win).
The Devices page adds types, renames their labels and removes unused ones
(**/device-types** in the API).

The first device list comes from `settings.yaml`. After the first change on
the Devices page, the list lives in `data/devices.yaml` (delete that file to
go back to `settings.yaml`).

## Voices: the Learn page

Every request that heard words is saved as a clip (audio, transcript, which
device heard it, its voiceprint, and Oread's best guess). The newest 200
unassigned clips wait on the **Learn** page. Assigning a clip to a person makes it
part of that person's profile; the profile's voiceprint is the average of its
clips, so each assignment improves recognition. Clips shorter than
`min_training_seconds` (2 s) are matched but can't be assigned.

Learn shows the clips as a table (sortable by any column) and plays each one,
shows its words and Oread's guess, and assigns or takes it back; ticked clips
are discarded together (**Discard ticked**). Anything that can't be undone asks
in place of the button pressed, never in a pop-up (askFirst in app.js).
Stats, and Settings' device and model boxes, fold open and closed with a click
on their heading; the browser remembers which are closed. **People** adds, renames and deletes profiles and shows
each person's clips.

Speaker knobs (Settings page, Devices tab, or **PATCH /settings/speaker**) change `min_training_seconds`, `unknown_below`,
`match_above`, the phrase knobs below and `trim_silence`, for all devices or for one with
`?device=`. Changes apply at once and survive restarts (saved in
`data/tuning.yaml`, on top of `settings.yaml`); **DELETE /settings/speaker**
(Back to defaults) forgets them, at once. **GET /settings** shows each device's current values.

Phrase habits: **Stats**, Phrase habits, charts each person's top 10 phrases
and words from their assigned clips (counted once per clip, shown once used
twice). It shows when phrase habits are strong enough to help tell people
apart, and how each person's words tend to come out in text.

Phrases helping the voice match: when the voice score is between
`phrase_from` (0.45) and `phrase_to` (0.55), a fair guess but not a sure one,
Oread looks for that person's habit phrases in what was said. A habit is a
phrase used in at least 3 of their clips, mostly by them (so "turn on the
lights", which everyone says, points to nobody). A habit heard confirms the
voice's guess, or picks between two people the voice found nearly tied; the
reply then says `by: voice+phrase`. Phrases never rule anyone out, never
override a clear voice match, and never name someone the voice didn't
already point to. `phrase_mode`: **shadow** (the default: the clip and the
request log note what phrases would have decided, nothing changes), **on**,
or **off**. All three are speaker knobs, per device. Stats lists each
person's habits.

Each match is labelled **known** (at or above `match_above`), **maybe**
(between the thresholds), or **unknown** (below `unknown_below`). The clip and
the result keep every person's score (`scores`), not only the closest three.

What a clip records besides its words and voiceprint: `measures` (oread/measures.py:
`speech_db`, `noise_db`, `gated_pct`, `peak_db`, `clipped_pct`, `bands_db` against
300-1000 Hz, `brightness_hz`, `clip_s`, and `speech_s` when trimming), `heard_with`
(speech model, voice model, trimming and the detector's settings, Oread's version),
`period` (when the device's current settings period began: its last accepted
retrain), `assistant_settings` (the device's settings in the voice assistant, above), `shadow` (what a
pending retrain would have said) and, once assigned, `assigned` (`by`, `kind`: user
or token, `at`). The measures and the rest also go to `data/measures/<device>.jsonl`,
one line per request (with `no_speech` and `try_it` flags), kept when clips go;
**GET /measures?device=** reads it.

Retraining one person on one device (oread/retrain.py; People, Retrain): the
device's own voiceprint for a person, the average of clips a person ticked (and,
once accepted, of that person's later clips from the device assigned by hand),
used in place of their all-device voiceprint on that device only. **POST /retrain**
makes a trial (pending; requests on the device log `shadow` with it, today's call
decides), **GET /retrain** lists the person's clips with `result` (the call when
heard), `trial_score` and `new_score` (a clip in the voiceprint is scored without
itself), **GET /retrain/blind** scores every clip on the device as today and with
the trial (counts since the oldest ticked clip and before it, and `verdict`: better,
worse, mixed or no change on the new sound, with the person's average score today and
with the trial), **POST
/retrain/accept** or **/retrain/reject**. Accepting starts a settings period.
Saved in `data/device_profiles.json`; renames of people and devices follow. A clip heard before its
device's last accepted retrain is `old_sound` (on every clip the API shows) and can't be
assigned (409).

Self-test for speaker ID (uses public clips and a throwaway folder; real
profiles are never touched):

```bash
docker compose exec oread python -m oread.selftest
```

## Test it from a laptop

```bash
pip install wyoming numpy pyyaml sounddevice sherpa-onnx
python3 tools/client.py --host <server address>   # prints the transcript and the speaker
python3 tools/regress.py --host <server address>
```

`client.py` records from the laptop microphone and prints what Oread heard,
who it thinks spoke, and the speech and voice models it used. It stops when
you stop talking, using the voice detector named under `defaults: vad` in
`models.yaml` (its own settings are there too; yours go in the laptop's
`data/models.yaml`); `--vad <name>` picks another listed under `vad:`. It
reads the copy of the repo it runs from, not the server's.
`regress.py` runs the test cases in `tests/cases.yaml`; run it after every
change. Household voice clips belong in `tests/private/` (never committed).

The tests' devices are the ones Oread was tested on: `voice-pe` is a Home
Assistant Voice PE, `tablet` a low-end EcoPad Android tablet running Ava Pro
to connect to Home Assistant, `laptop` a Lenovo IdeaPad on Ubuntu 24.04
through `tools/client.py`.

## Test the pages

```bash
npm install && npm run lint          # refuses anything newer than ECMAScript 2020
pip install playwright && playwright install chromium firefox webkit
python3 tests/web_test.py            # setup, sign-in, roles, theme, phone layout, lockout
```

`web_test.py` starts its own Oread on empty temporary data and runs every
check in Chromium (Chrome, Edge), Firefox and WebKit (Safari's engine) at
laptop and phone sizes; engines not installed are skipped and named. WebKit
is close to Safari but not identical, so check on a real iPad before a release.

## Compare models

`tests/phrases.txt` is the list every model is measured on. Record yourself
reading it once (clips stay in `tests/private/`, never committed), then
benchmark each model on the same clips:

```bash
python3 tools/record_set.py --host <server address>
python3 tools/bench.py --host <server address>
# change stt.model in the server's settings.yaml, restart Oread, bench again
python3 tools/bench.py --matrix    # accuracy and speed, one row per model
python3 tools/bench.py --misses    # what each model got wrong, phrase by phrase
```

## Python and library versions

- The Docker image pins its Python and Debian release (`python:3.12-slim-trixie`).
- `requirements.in` lists Oread's direct libraries. **Pinned exactly:**
  sherpa-onnx (a new version can change transcripts and voiceprints) and
  wyoming (the protocol clients speak); upgrade these on purpose and
  rerun `regress.py` and `bench.py`. **Ranged:** everything else (numpy,
  pyyaml, fastapi, uvicorn, cryptography), where any compatible release is fine.
- `requirements.txt` is generated from it by `tools/lock.sh` and pins every
  package exactly, so every build gets the same versions.
- To move to a newer Python: change the Dockerfile's `FROM` line and `PYTHON`
  in `tools/lock.sh`, run `tools/lock.sh`, rebuild, then run the tests.

## Resource log

Every request adds one line to `logs/requests.jsonl`: time per step
(receive, queue, stt+voiceprint, reply, and inside that stt, voiceprint and sound each on its own,
since Oct 18), CPU time, memory, and the real-time factor (`rtf`, speech to text's own: 0.1 means
10 seconds of audio took 1 second), and `speech_s`, the
seconds decoded after trimming on a device with `trim_silence` on (0 when the
clip had no speech and wasn't decoded), and `shadow`, what a pending retrain on
the device would have said (People, Retrain). CPU time is measured
for the whole process, so requests that overlap share their numbers.
The file keeps the newest 10,000 requests (`logging.keep_requests`; 0 keeps
all). The longest queue wait and the hourly history are kept separately, so
trimming loses neither.

Once a minute Oread also notes its CPU and memory (a kernel read, nothing
written). Minutes roll up into hours, and each finished hour is appended to
`logs/resources-history.jsonl` (about 30 days are kept). `/resources` shows the
average and peak over the last hour, 24 hours and 30 days, and that history
survives restarts.

Many satellites at once: `server.max_concurrent` (2) requests are decoded at
the same moment; more wait in line. Each request's wait is in the log (the
`queue` step), and `/resources` shows the longest wait ever (kept in
`logs/queue-record.json`), how many recent requests waited, each device's
longest wait, and each hour's longest wait. If waits show up, raise
`server.max_concurrent` in `data/settings.yaml` and restart; `/resources` →
capacity shows the threads that uses when all are busy next to the cores
available, so you can see when the machine needs more cores.

## Models

The list lives in `models.yaml`: speech models, voice models, and voice
detectors (`vad:`, used by `tools/client.py`), each with its download
address, files, license, measured memory, notes and its own starting
`settings:` (threads; for voice models also the match thresholds and phrase
range). `defaults:` names the model of each kind used when nothing else
chooses one. A device's settings are layered: its model's own, then
`settings.yaml` `defaults`, its type, the device, then values set for it
while running. The Settings page (Models tab) or **PATCH /models/{kind}/{name}**
and **POST /models/{kind}/{name}/default** change them, saved in
`data/models.yaml` (only what differs from the shipped values); add models
there too, same layout. The Imports page shows and edits each model's
entry (download address, files, license), adds models and removes ones you
added (**/imports** in the API), checking every change before it's saved.

Models are downloaded, never shipped in this repository. Each has its own license.

| Model | Author | License |
| --- | --- | --- |
| [Moonshine base](https://github.com/usefulsensors/moonshine) (default) | Useful Sensors | MIT |
| [Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) | NVIDIA | CC BY 4.0 |
| [Zipformer, LibriSpeech 2023-06-26](https://huggingface.co/Zengwei/icefall-asr-librispeech-zipformer-2023-05-15) | k2-fsa / icefall | Apache 2.0 |
| [Whisper small.en](https://github.com/openai/whisper) | OpenAI | MIT |
| [TitaNet Small](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemo/models/titanet_small) (voiceprints, default) | NVIDIA | Apache 2.0 (NeMo toolkit) |
| [CAM++ English](https://www.modelscope.cn/models/iic/speech_campplus_sv_en_voxceleb_16k) (voiceprints) | 3D-Speaker | Apache 2.0 |
| [WeSpeaker ResNet34](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md) (voiceprints) | WeSpeaker | CC BY 4.0 (as its training data, VoxCeleb) |
| [Silero VAD](https://github.com/snakers4/silero-vad) (laptop client only) | Silero | MIT |

All are int8 versions packaged by sherpa-onnx.

## License

Apache License 2.0. See `LICENSE` and `NOTICE`.

## Releasing (development and production)

This repo (dev-oread) is private development. A public repo, made when Oread goes public under
its own name, only ever receives releases, built by `tools/release.py` from what `release.yaml`
says: every tracked file except its `never:` list (data/, keys/, logs/, models/, .env; the empty
folders' `.keep` files stay, through `keep:`). Your household's Oread lives in data/. Only its
settings files (settings.yaml, devices.yaml, tuning.yaml, access.yaml) are kept in development, so
both of you see the same setup; the voices (clips/, profiles.json), accounts, sign-ins and tokens
are never in git: back them up with keys/ instead. A release never ships anything in data/.

- `python3 tools/release.py --check`: builds the public copy and shows what would go out; nothing
  is published.
- `python3 tools/release.py`: the same, then asks; on `yes`, one commit in the public repo tagged
  `v<version>`, and this repo's commit tagged `release-v<version>`.

Set `public:` (the public repo's address) and `version:` in release.yaml when you're ready. The
public history starts at the first release.

Oread's own version is `__version__` in `oread/__init__.py` (2026.10.0; year.month.release, with its section in CHANGELOG.md). It's what its
OpenAPI document says, so the house router notices an update; change it with every release, and
keep release.yaml's `version:` the same.
