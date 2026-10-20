# Oread user guide

Oread turns what people say to your listening devices (Home Assistant voice
satellites, for example) into text, and works out who said it. It runs on
your own server, in Docker, with no cloud service. This guide takes you from
nothing to a working install, and collects the problems people have actually
run into, with their fixes. Once Oread is running, the same guide is on its
**Setup guide** page (the last item in the menu), matching the version you
have installed.

> Steps marked *(not yet tried on a real install)* follow the tools' own
> documentation but haven't been walked through end to end yet.

## Contents

1. [What you need](#1-what-you-need)
2. [Install](#2-install)
3. [Your own settings](#3-your-own-settings)
4. [First run: create the super user](#4-first-run-create-the-super-user)
5. [HTTPS and the browser warning](#5-https-and-the-browser-warning)
6. [People and roles](#6-people-and-roles)
7. [Who may connect: permitted clients](#7-who-may-connect-permitted-clients)
8. [Try Oread from your computer](#8-try-oread-from-your-computer)
9. [Connect a client](#9-connect-a-client)
10. [Who spoke: getting it to your client](#10-who-spoke-getting-it-to-your-client)
11. [Teach Oread voices](#11-teach-oread-voices)
12. [Back up](#12-back-up)
13. [Update](#13-update)
14. [Stop, start over, or move Oread](#14-stop-start-over-or-move-oread)
15. [Troubleshooting](#15-troubleshooting)

Appendices:

- [A. Example: connecting Home Assistant](#appendix-a-example-connecting-home-assistant)
- [B. For programmers: the API and the listening ports](#appendix-b-for-programmers-the-api-and-the-listening-ports)

---

## 1. What you need

- **A server that runs Docker:** a 64-bit Intel or AMD machine (or a virtual
  machine) with Docker and Docker Compose. Oread runs on the processor alone;
  no graphics card is needed.
- **At least 2 CPU cores and about 1 GB of memory** for Oread with its default
  models (4 cores for quicker replies, or for Parakeet; the README's
  [cores table](https://github.com/coderpigsfly/oread#will-it-fit-on-a-small-machine)
  has the measured times), **about 1 GB of disk** (more if you try other
  models), and free disk for saved voice clips.
  The Stats page shows what Oread really uses on your machine, and (Where the time goes) how
  long each step of a request takes: by day, week and month.
- **A voice assistant that speaks Wyoming** (Home Assistant, for example)
  with at least one listening device (a Voice PE, an Android tablet running a
  voice app, and so on).
- A browser on a laptop, tablet or phone: Chrome, Edge, Firefox, or Safari
  14 or later.
- **Fixed addresses** for Oread's server and for every client that will talk
  to it (your voice assistant, a Wepwawet router if you use one, the computer you test
  from). Oread works by address, not by name: the permitted clients list,
  the certificate and your voice assistant's connection to Oread all use
  them, and if one changes, that connection quietly stops. The easiest way is
  a *DHCP reservation* in your router (often under LAN, DHCP, or "address
  reservation"): pick the device and tie it to its current address. Setting
  a static address on the device itself works too.

Older processors work, but some models are much slower on processors without
AVX2 (see [Troubleshooting](#slow-replies-on-an-older-processor)). The default
model was chosen to be quick on them.

## 2. Install

On the server, as yourself (not with `sudo`, so the folders belong to you):

```bash
mkdir -p ~/docker
cd ~/docker
git clone https://github.com/coderpigsfly/oread.git
cd oread
id -u; id -g
```

This guide keeps Oread in `~/docker/oread`, alongside other Docker apps;
every command below uses that folder. If you put it somewhere else, use your
folder wherever the guide says `~/docker/oread`.
Run every `docker compose` command in this guide from inside that folder
(`cd ~/docker/oread` first); elsewhere Docker can't find Oread's settings.

Oread runs as your own user (not as root), so the files it makes stay yours
to read and edit. It assumes your user and group numbers are both 1000, the
usual for the first user on a Linux machine. If `id -u` or `id -g` printed
something else:

```bash
cp .env.example .env
nano .env        # set OREAD_UID and OREAD_GID to the two numbers
```

Then start it:

```bash
docker compose up -d --build
docker compose logs -f oread
```

The first start downloads Oread's speech models (a few hundred MB) into
`models/`, so it takes a few minutes; later starts take seconds. Leave the
log open: you need it for the next steps. Press Ctrl+C to stop watching the
log (Oread keeps running).

Oread uses these ports on the server:

| Port | What |
| --- | --- |
| 10311 | Oread's pages and API (HTTPS) |
| 10310, 10312-10339 | one per listening device, for Home Assistant |

## 3. Your own settings

Oread's defaults are in `settings.yaml`. **Don't edit that file**: updates
replace it. Put your own changes in `data/settings.yaml` instead, holding
only what you change, in the same layout. Oread applies it on top.

Before the first visit, tell Oread the address and name you'll use to reach
the server, so its certificate matches (see [HTTPS](#5-https-and-the-browser-warning)).
Create `data/settings.yaml` with, for example:

```yaml
api:
  tls_names: [192.168.1.20, myserver]
```

Use your server's own address and name. Then restart Oread:

```bash
docker compose restart oread
```

## 4. First run: create the super user

The first account is the **super user**, who can do everything and adds
everyone else. To make sure it's you and not someone else on your network,
Oread asks for a one-time setup code that can only be read on the server.

1. Find the code (from inside `~/docker/oread`):

   ```bash
   cat data/setup-code.txt
   ```

   It looks like `3F9A-0B12-C7D4`. It's also the last line of
   `docker compose logs oread | grep "setup code"`. It stays the same when
   Oread restarts, until it's used.
2. Open `https://<server address>:10311/` in your browser. Expect a security
   warning the first time; see [HTTPS](#5-https-and-the-browser-warning) for why
   and how to make it stop. For now, choose to continue (in Chrome and Edge:
   **Advanced**, then **Proceed**; in Firefox: **Advanced**, then **Accept
   the Risk and Continue**; in Safari: **Show Details**, then **visit this
   website**).
3. Enter the setup code, choose a username (your own, not "admin"), and a
   password of at least 10 characters.
4. Optionally tick **Start with a sample household** (below).

The code works once; then the file is deleted.

### A sample household to try

Short clips read by three volunteers from the public LibriSpeech recordings
(CC BY 4.0), so the pages have something to show before anyone in your home
has spoken to Oread:

| Who | Clips | Where |
| --- | --- | --- |
| Sample Ada | 6 taught, 2 waiting | **People**, and **Learn** with Oread's guess |
| Sample Ben | 6 taught, 2 waiting | the same |
| A reader Oread hasn't met | 4 waiting | **Learn**, as unknown: assign them to see it learn |

Each clip goes through the same steps as a real request on the `voice-pe`
device (or your first device), using its models; nothing is sent to Home
Assistant. Adding takes about a minute.

Add, or remove, it in **Settings › Sample household**. Removing takes away
the sample's clips, its people and its lines in **Stats**, and nothing of
yours: a clip of yours assigned to a sample person goes back to **Learn**.
To start it over, remove it and add it again.

## 5. HTTPS and the browser warning

Oread's pages are always HTTPS, so passwords never cross your network in the
open. Browsers only trust a certificate when a recognised authority vouches
for it, so out of the box (with Oread's own *household* certificate) they
warn. Pick one of these to make the warning go away for good. You can change
your mind later; Oread just needs a certificate file and a key file.

| Way | Cost | Warnings | Effort |
| --- | --- | --- | --- |
| A. Install Oread's household certificate on each device | free | none on devices where it's installed | a few minutes per device |
| B. A free DuckDNS name with a Let's Encrypt certificate | free | none anywhere | about half an hour, once |
| C. Your own domain with a Let's Encrypt certificate | about $10-15 a year | none anywhere | about half an hour, once |
| D. A reverse proxy you already run, with a real certificate | - | none anywhere | depends on your proxy |
| E. Tailscale, if you already use it | free | none, on devices running Tailscale | a few minutes |

### A. Install Oread's household certificate

Download it on each device: in Oread, **Connections**, **Certificate**,
**Download the certificate** (or open `https://<server address>:10311/ca.crt`).
The file is `oread-household-ca.crt`. Then:

- **Windows (Chrome, Edge):** double-click the file, **Install Certificate**,
  **Current User**, **Place all certificates in the following store**,
  **Browse**, **Trusted Root Certification Authorities**, **OK**, **Next**,
  **Finish**, then **Yes** to the security question. Restart the browser.
- **macOS (Safari, Chrome, Edge):** double-click the file; Keychain Access
  opens and adds it. Find "Oread household CA" in the **login** keychain,
  double-click it, open **Trust**, set **When using this certificate** to
  **Always Trust**, close the window and enter your password.
- **Firefox (any computer):** Firefox keeps its own list. **Settings**,
  **Privacy & Security**, **View Certificates**, **Authorities**, **Import**,
  pick the file, tick **Trust this CA to identify websites**, **OK**.
- **Linux (Chrome, Edge):** **Settings**, **Privacy and security**,
  **Security**, **Manage certificates**, the tab for certificates you've
  installed (named **Custom** or **Authorities**, by version), **Import**,
  pick the file, tick trust for websites.
- **Android (Chrome):** **Settings**, **Security** (or **Security &
  privacy**), **More security settings**, **Encryption & credentials**,
  **Install a certificate**, **CA certificate**, **Install anyway**, pick the
  file. Menu names vary a little by phone maker.
- **iPad and iPhone (Safari):** open the `/ca.crt` address in **Safari** and
  allow the download. Then **Settings**, **Profile Downloaded** (near the top),
  **Install**, enter your passcode, **Install**. Finally **Settings**,
  **General**, **About**, **Certificate Trust Settings**, and turn on full
  trust for "Oread household CA". (The last step is easy to miss; without it
  Safari still warns.)

### B. A free DuckDNS name with Let's Encrypt *(not yet tried on a real install)*

DuckDNS gives you a free name like `yourhouse.duckdns.org`. Let's Encrypt
issues a real certificate for it by checking a note in DuckDNS's records, so
nothing in your house is opened to the internet.

1. Go to [duckdns.org](https://www.duckdns.org), sign in with an account you
   already have, and add a name (for example `yourhouse`).
2. In the **current ip** box for that name, type your server's **home**
   address (like `192.168.1.20`), not your public one, and press **update ip**.
3. Copy your DuckDNS **token** from the top of the page. Keep it private.
4. Get the certificate with a tool that supports DuckDNS, such as acme.sh, on
   the server:

   ```bash
   curl https://get.acme.sh | sh -s email=you@example.com
   export DuckDNS_Token="your-duckdns-token"
   ~/.acme.sh/acme.sh --issue --server letsencrypt --dns dns_duckdns -d yourhouse.duckdns.org
   ~/.acme.sh/acme.sh --install-cert -d yourhouse.duckdns.org \
     --key-file ~/docker/oread/keys/site-key.pem \
     --fullchain-file ~/docker/oread/keys/site-cert.pem \
     --reloadcmd "docker compose -f ~/docker/oread/docker-compose.yml restart oread"
   ```

   acme.sh renews it by itself and restarts Oread when it does.
5. Tell Oread to use it, in `data/settings.yaml` (these are the paths
   *inside* Oread's container, where `~/docker/oread/keys` appears as `/app/keys`):

   ```yaml
   api:
     tls: files
     cert_file: /app/keys/site-cert.pem
     key_file: /app/keys/site-key.pem
   ```

6. Restart Oread and open `https://yourhouse.duckdns.org:10311/`.

If the name doesn't open at home, see
[the name doesn't resolve at home](#a-duckdns-or-own-domain-name-doesnt-open-at-home).

### C. Your own domain *(not yet tried on a real install)*

The same as B, with your domain's DNS provider in place of DuckDNS: add a
record pointing a name (like `oread.example.com`) at the server's home
address, and use your provider's DNS plugin in acme.sh or certbot. Then steps
5 and 6 above.

### D. Behind a reverse proxy

If you already run Nginx Proxy Manager, Caddy, Traefik or Home Assistant's
NGINX add-on with a real certificate, point a name at Oread
(`https://<server>:10311`, trusting Oread's household certificate, or set
`api.tls: off` in `data/settings.yaml` for plain HTTP to the proxy only).
Then use permitted addresses ([section 7](#7-who-may-connect-permitted-clients))
so only the proxy can reach Oread directly.

### E. Tailscale

If you already use Tailscale: in its admin console, on the **DNS** page,
turn on **MagicDNS** and **HTTPS Certificates**. Install Tailscale on the
server, then put Oread behind `tailscale serve`; it's reachable at
`https://<server>.<your tailnet>.ts.net` with a real certificate. Every device
needs Tailscale running to use that name, even at home. Turning on HTTPS
publishes your machine names in public certificate logs, so make sure none of
them say anything private. Oread doesn't depend on Tailscale; this is only one
way to get a certificate.

## 6. People and roles

Each person signs in with their own username and password. Each role can add
and manage only people with a lower role:

| Role | Can |
| --- | --- |
| super | everything, including stored keys, permitted addresses and other super users |
| administrator | devices, settings, API tokens, Home Assistant, reviewers and viewers |
| reviewer | listen to clips, assign them to people, add and rename people |
| viewer | look only: Stats, People, Devices and Settings |

(These are the people who sign in to Oread's pages. The voices Oread
recognises are a different list, on **People**.)

In Oread: **Users** (administrators and super users see it).

- **Add a user:** a **Username** (2-32 letters, digits, . _ or -), a
  **Role**, and a **Password** typed twice (10 characters or more; the page
  says as you type whether they match). Tell them the password yourself; they
  can change it on **Account**. You can give only roles below your own; a
  super user can also make other super users.
- **Role** on someone's row changes their role. **Reset password** gives them
  a new one (and unlocks a locked name). Either signs them out everywhere, so
  they sign in again with the new role or password.
- **Remove** takes their account away; they're signed out at once.
- You can't change or remove your own account here (your password is on
  **Account**), or anyone with a role as high as yours unless you're a super
  user. Oread keeps at least one super user.
- **Audit log** (a tab on the same page) lists every change, sign-in and
  refused sign-in, newest first: when, who, what, the result and the address
  it came from. It never holds passwords or keys.

Change your own password and theme on **Account**.

Five wrong passwords in a row lock that username for 15 minutes. Forgotten a
password? Someone with a higher role can reset it on **Users**, or on the server:

```bash
docker compose exec oread python -m oread.users reset <username>
```

## 7. Who may connect: permitted clients

A *client* is any program that sends Oread audio to turn into text: your
voice assistant (Home Assistant, for example), a Wepwawet router if you use
one, or a computer you test from. Clients can't sign in, so Oread's listening
ports are protected by a list of addresses allowed to send audio. Until you
add one, **any** address on your local network can (but nothing from the
internet), and Oread warns you on the page and in its log.

You need **super user** rights for this. Do it in two steps, in this order:

**Now: the computer you test from.** On that computer, open **Connections**,
**Permitted clients**, and press **Add this computer**. This closes Oread to
everything else while you try it out, before any voice assistant depends on
it.

**Later, just before connecting a client** (your voice assistant, the intent
router, or another program; [section 9](#9-connect-a-client)):
add that client's address, or it will be turned away.

1. Find the client's address. For Home Assistant: **Settings**, **System**,
   **Network**; it's the IPv4 address shown for its network adapter (like
   `192.168.1.50`).
2. In Oread: **Connections**, **Permitted clients**. Type that address in
   **Add an address or range** and press **Add**.

A whole range works too, like `192.168.1.0/24` for every address from
192.168.1.0 to 192.168.1.255, but single addresses are safer. Changes apply at
once, to the next connection.

**Recently refused** lists the last addresses turned away, with the
listening device's name and the time. If your voice assistant shows up there
(you forgot it, or its address changed), press **Allow** beside it, then give
it a fixed address ([section 1](#1-what-you-need)) so it doesn't happen again.

## 8. Try Oread from your computer

Before connecting anything, check that Oread hears you, from the computer (or
phone) you permitted in [section 7](#7-who-may-connect-permitted-clients).
Nothing to install: it uses the browser's microphone.

1. In Oread: **Try it** (after **Connections** in the menu).
2. **Test as**: pick a listening device. Oread handles the test exactly as if
   the audio came from that device, with its settings.
3. Press **Start speaking**, say something (a few seconds; the bar moves while
   it hears you), then press **Stop** (it stops by itself after 15 seconds).
4. Oread shows the words it heard and who it thinks spoke. Until it's been
   taught voices, that's **Unknown**.

The browser asks once for permission to use the microphone; allow it. Every
test is saved to **Learn** like any other clip, so tests of 2 seconds
or more can also be used to teach Oread your voice
([section 11](#11-teach-oread-voices)). The Home Assistant "who spoke" sensor
isn't changed by tests. You need the **reviewer** role or higher. On an iPad
or iPhone this needs Safari 14.1 or later.

## 9. Connect a client

A client is whatever sends Oread the audio from your listening devices: your
voice assistant (Home Assistant, for example), a Wepwawet router, or another
program. Connecting one takes three things, in this order:

1. **Permit the client.** Add its address in **Connections**, **Permitted
   clients** ([section 7](#7-who-may-connect-permitted-clients)). Once any
   address is on that list, everything else is turned away.
2. **Find the device's port.** In Oread: **Devices**. Each listening device
   (a satellite, a tablet, a test computer) has its own port; that's how Oread
   knows which device it's hearing. To start: laptop 10310, voice-pe 10312,
   tablet 10313. **Copy address** copies the server's address and that
   port together. Add a device there for each new satellite (Oread picks the
   next free port and starts listening at once), and rename or remove them
   there too. Renaming keeps the same port, so the client needs no change.
3. **Point the client at it.** In the client's speech-to-text settings, use
   the Wyoming protocol, Oread's server address, and that device's port: one
   connection per device.

For a step-by-step example, see
[Appendix A: Example: connecting Home Assistant](#appendix-a-example-connecting-home-assistant).

To go back to the client's old speech-to-text at any time, switch it back in
the client; this is also what to do if Oread is ever down.

### Choosing models (optional)

Every device uses Oread's default models unless its type or you choose otherwise:
**Moonshine** to turn speech into words, and **TitaNet small** to tell voices
apart. They did best in our tests, but a different microphone or room can
change that, so each device can use another model. In Oread: **Settings**,
**Devices** (or **Settings** on the device's tile on **Devices**, which opens
it at that device); pick a **Speech model** or **Voice model** and press
**Save** (or pick the first choice, **Default** or **From its type**, to go
back). The device's port pauses for a moment while the model loads. The
Devices page shows which models each device uses; it's changed only here.

| Speech model | Memory | Good to know |
| --- | --- | --- |
| Moonshine (default) | about 380 MB | fast and accurate on household commands |
| Parakeet | about 810 MB | most accurate in our tests; about twice the time and memory |
| Zipformer | about 170 MB | fastest and smallest; least accurate |
| Whisper small | about 950 MB | about ten times slower without a graphics card |

What it costs:

- **Memory:** each *different* model is loaded once and shared. Ten devices
  on the default cost the same as one; one device on Parakeet adds about
  810 MB. A model nobody uses any more is let go.
- **Speed:** a slower model keeps one of Oread's two working slots busy
  longer, so other devices wait more often. **Stats** shows memory and waits.
- **Download:** a model is downloaded the first time it's chosen, which can
  take a few minutes.

**One device's settings.** In Oread: **Settings**, **Devices**. Each device
shows its models and how it decides who spoke: **Person unknown below**,
**Person named at**, **Phrases from** / **Phrases to**, **Phrase habits**
(off, shadow, on), **Shortest clip to learn from**, and **Report who spoke**.
Under each value it says where it comes from: the voice model, or *Set for
this device*. Change values and press **Save**; they're used at once and
kept for that device only. **Back to defaults** forgets that device's own
values and goes back to its models' and type's, also at once.

**Each model's own settings, and the default.** In Oread: **Settings**,
**Models**. Every model is listed with its settings:

- **Threads** (every model): CPU threads one request may use. More is
  faster, up to the cores you have.
- **Voice models also:** **Person unknown below** and **Person named at**
  (the match thresholds: below the first the speaker is unknown, at or above
  the second Oread names the person, in between is maybe), and **Phrases from** / **Phrases to** (the
  range where habit phrases may settle a maybe). Each voice model scores
  voices differently, so each keeps its own thresholds. CAM++ and WeSpeaker
  start on TitaNet's values, which haven't been tuned for them yet.

Change a value and press **Save**: every device using that model picks it up
at once (a thread change reloads the model, so those devices' ports pause
for a moment). The shipped value is shown under anything you've changed, and
**Back to shipped** undoes your changes. **Make default** makes that model
the one devices use when neither their type nor the device chooses another;
those devices switch at once. A value set for one device (**Settings**,
**Devices**) stays on top of the model's. Your changes are kept in
`data/models.yaml`, which updates never touch.

**Where models come from: Imports.** In Oread: **Imports** (under
**Settings** in the menu). The tabs are **Speech models**, **Voice models**
and **Voice detectors** (the default one trims the quiet for devices that
ask for it, below; `tools/client.py` uses one on your computer, from its copy of
`models.yaml`, and `--vad` picks another),
with a pill for each model; press one to see its entry:

- **Its entry:** the name shown on the pages, how it's loaded (its kind),
  the download address, the files it needs (for a speech model, the folder
  inside its archive and which file plays each part), languages, author,
  license, model card, memory and notes.
- **Save** keeps your change in `data/models.yaml`, which updates never touch.
  If devices use that model, it's loaded again on them at once; a changed
  voice model also works out everyone's voiceprints again from their saved
  clips. A changed address is used the next time the model has to be
  downloaded.
- **Check the link** asks the download address whether it answers (and how
  big the file is), without downloading anything.
- **Back to shipped** puts a shipped model back to Oread's own entry.
- **+ Add a model:** a short name (it can't change later) and everything a
  model of that kind needs. Oread checks the entry before saving it, so a
  mistake is refused instead of stopping Oread. A new model is downloaded the
  first time a device uses it, and starts on the default model's settings.
  Any model sherpa-onnx can run offline works, as one of four kinds
  (`moonshine`, `transducer`, `nemo_transducer`, `whisper`) for speech, or a
  speaker embedding model for voices. Check its license before using it.
- **Remove** takes a model you added off the list, once no device or device
  type uses it and it isn't the default. Its downloaded files stay in
  `models/`.

The same entries are in `models.yaml` (shipped) and `data/models.yaml`
(yours, same layout), if you'd rather edit them by hand and restart.

**Compare before you switch.** On **Devices**, press **Compare** on a
device's tile. It tests a model on clips Oread already has from that device,
and runs only when you press **Start comparing** (it's never done on its own).

- **The words (speech model):** the model listens to the device's newest
  clips, and every clip where its words differ from what Oread heard is shown
  side by side, with a play button. Listen and say which was right; the page
  keeps the tally. (Oread can't score this by itself: it has no "correct"
  words, only what it heard.)
- **Who spoke (voice model):** a real score, because assigned clips say who
  was speaking. For each of the device's assigned clips, Oread learns the
  voices from all the *other* assigned clips and asks the model who it is.
  **Wrong person** is the number to avoid; and the wider the gap between
  **Match: right person** and **Match: closest other**, the better that model
  tells your household apart. It needs at least two assigned clips from that
  device, and works best with a few people who each have several.
- When the results favour the other model, **Use … for …** switches the
  device to it. **Try it** as that device is a quick final check.
- The results stay on the Devices page until you're done with them: **Done**
  or **✕** puts them away for good, and so does **Use … for …**. While a
  comparison is still running, **✕** (or **Cancel**) asks right there before
  stopping it and then shows the clips it got through.

While it runs it works one clip at a time and always leaves room for live
requests; a model being tried is loaded for the test and let go afterwards.
Changing the voice model makes Oread relearn every voice from the clips
already assigned, by itself. Right, maybe and unknown use each model's own
thresholds; the gap between the two match columns doesn't depend on them.

### Device types (optional)

A device type is a kind of listening device, like "Home Assistant Voice PE"
or "Android tablet". When you add a device you can give it a type, and its
tile shows the type's label. A type can also start every device of its kind
on particular models; a device's own choice (**Settings**, **Devices**) still
wins, and the tile says where each model comes from: *(default)*, *(from its
type)*, or nothing when you chose it for that device.

Oread comes with three examples: Home Assistant Voice PE, Android tablet,
and Laptop or desktop. In Oread: **Devices**, **Device types**, at the bottom
of the page:

- **Add a type:** a **Label** people read, a **Short name** (lowercase
  letters, digits, - or _; devices and the API use it, and it can't change
  later), an optional **Note**, and the speech and voice models it should
  start on (leave them on **Default** to use Oread's defaults). It's
  offered in **Add a device** at once.
- **Rename** changes the label and note; the short name stays, so its
  devices keep it.
- **Remove** works once no device uses the type. (It's greyed out until
  then; change those devices' type or remove them first.)

Your types are kept in `data/device-types.yaml`, which updates never touch.
You can edit it by hand too (same layout as `device-types.yaml`, which lists
the shipped examples) and restart Oread.

## 10. Who spoke: getting it to your client

Every answer Oread gives carries the words *and* who spoke. Clients that
read the whole answer (a Wepwawet router, or a program of your own) get the
speaker directly; nothing to set up.

Some clients keep only the words. Home Assistant does: for it, Oread can set
a "who spoke" sensor per device, which its automations can use. That's set up
in [Appendix A](#appendix-a-example-connecting-home-assistant). Whether each
device reports this is shown on **Devices**.

## 11. Teach Oread voices

Oread never names anyone it hasn't been taught. Every time someone speaks to
a listening device (or uses **Try it**), Oread keeps the clip and its words
on the **Learn** page. Telling Oread who was speaking teaches it that voice; the more
clips per person, the better it knows them. You need the **reviewer** role or
higher.

1. In Oread: **Learn**. **Waiting** shows the newest clips first in a table,
   one clip to a row: when and where it was heard, the words (click them to
   see all of a long one), Oread's own guess (**unknown**, **maybe**, or a
   name), its length, and whether it's long enough to teach. Click a column
   heading to sort by it, again to reverse.
2. Press the round play button to listen if you're not sure who it was.
3. In **Who spoke?** pick the person, or **New person…** and type
   their name, then press **Assign**.
4. Made a mistake? Press **Undo** right there. Later, find the clip under
   **Assigned** and use **Move** (to someone else) or **Take back** (back to
   waiting).

**The People page** lists everyone Oread knows by voice, each with how many
clips it has learned from (and from which devices) and how far along it is:
**Not learned yet**, **Learning: 1 of 3**, or **Knows their voice**. There you
can:

- **Add a person** ahead of time, so they're in the list on the Learn page.
- **Rename** someone. Their clips and their voice go with the new name, so
  nothing is relearned.
- **See clips**: the Learn page, showing only that person's clips, to check
  for any assigned by mistake.
- **Delete** someone. Oread forgets their voice and their clips go back to
  waiting on the Learn page.

Anything that can't be undone asks first, right where you pressed: the
button turns into the question, with the action's own button and **Cancel**
(or press Escape). There are no pop-ups.

Once a person has a few clips, their tile also shows phrases they say often,
which Oread can use to help tell people apart.

**What's worth teaching?** (also on the Learn page, at the top)

- **Teach the clips Oread was unsure about.** A "maybe", or a voice you know
  that it called unknown, helps it most.
- **Skip the ones it already names with a high score** (about 0.75 or more).
  They add little; leave them or discard them.
- **Only clear clips:** one person speaking, without TV, music or other
  voices behind them. If you can't tell who it is, Oread can't learn from it.
- **A few at a time, and varied.** Rather than many near-identical clips at
  once, pick a few from different devices, times of day and moods. Three to
  five clips start a person; ten to twenty over time make them solid.
- **When in doubt, leave it out.** One wrong clip blurs that person's voice;
  **Undo** or **Take back** fixes a mistake.

More tips:

- **Short clips can't teach.** Clips under 2 seconds (the minimum is a
  setting) show "Too short to teach"; you can still keep or discard them.
- **Discarding deletes for good.** Tick the clips in the first column, press
  **Discard ticked**, and confirm right there. Clips you leave alone are
  kept until the waiting list passes its limit (the newest 200), then the
  oldest go.
- **Same person, different devices is fine,** and helps: a voice sounds a
  little different through each microphone.

### When a device's sound changes: Retrain

A person's voice is learned from all their clips on every device together. If
one device's sound changes (you raise its microphone gain, turn on noise
suppression, or change the app's recording settings), their voice there can
stop matching: scores that were around 0.7 drop to around 0.35, and Oread says
"maybe" or "unknown" for someone it knew. **People**, **Retrain** gives that
device its own voiceprint for that person, from clips heard since the change.

1. Make the change on the device, speak a few normal requests to it, and
   assign those clips to yourself on **Learn**.
2. **People**, **Retrain**: pick the **person** and the **device**, and, if you
   like, say **why** ("microphone gain up, noise suppression on"): it's kept as the
   record of what changed.
3. The table lists that person's clips from that device, newest first (click
   a heading to sort). **Original** is the call Oread made when it heard the
   clip; it never changes. Tick the clips from after the change. A wrong clip?
   **Take back** puts it back to waiting; reassign it on Learn.
4. **Retrain** makes a trial voiceprint from the ticked clips. Nothing changes
   yet: Oread still decides as before, and requests on that device note what
   the trial would have said. **Trial** shows each clip's score with it (a
   ticked clip is scored without itself, so the number is honest).
5. The **Blind test** scores every clip the device heard, whoever it's
   assigned to (and those waiting), as today and with the trial, counted apart
   for the new sound (since the oldest ticked clip) and the old sound (which a
   trial for the new sound is expected to lose). Open **All … clips** for the
   list. A clip *names* a person when Oread calls them known (maybe and
   unknown name nobody); **Change** marks the clips whose named person would
   change: now names someone, no longer names anyone, or names someone else.
   Both tables fold away with a click on their heading. Above them,
   **Overall** says whether the trial is **Better**, **Worse**, **Mixed** or
   **No change**, judged on the new sound only: more of the person's own
   clips named and none of anyone else's is better; fewer of their own, or
   someone else's named as them, is worse; the same counts let their average
   score decide. Scores carry an arrow (↑ up, ↓ down, → moved less than 0.02):
   **Trial** and **New score** against the person's own score when the clip
   was heard, the blind test's score against today. Every heading with ⇅ sorts;
   the arrow columns sort by how far the score moved.
6. **Accept**: the device's own voiceprint for that person decides there from
   now on, and **New score** fills in. Or **Reject**: nothing is kept.

After an accept, clips of that person you assign from that device join it,
and a clip taken back leaves it. Clips the device heard *before* the accept
are its old sound: on Learn their **Can teach** says **old sound** and they
can't be assigned (to anyone, so they don't blur any voice). **Tick old sound**
ticks every waiting one (on the device picked, or all devices), and
**Discard ticked** clears them. Other devices, other people, the voice model,
the "named at" line and every clip's Original stay as they were. Change the
device again and start over: a new retrain replaces the old. Only clips a
person assigned can retrain (not ones a program assigned with a token). A
person the device has hardly heard is best left alone.

**What each clip records,** for spotting changes later: how it sounded
(speech level, background level, how much is digital silence from a noise
gate, clipping, the shape of the sound in bands, brightness), which models and
settings heard it, the device's settings period (since its last accepted
retrain), who assigned it and when, its score against every person, and, if
the device is matched to its device in your voice assistant (Settings, Devices,
**Voice assistant device**), that device's settings there (microphone volume,
finished-speaking detection, wake word sensitivity). The sound measures are
also kept per device in `data/measures/`, one line per request, with or
without words, and stay when clips are pruned or discarded.

### Mishearings from the house router (optional)

If you use Wepwawet Veil, the house router (coming soon; it follows the
[Wepwawet standard](https://github.com/coderpigsfly/wepwawet_standard)), it keeps what Oread heard wrong under what
was really said, with the clip each was heard in. The **Mishearings** page brings that
list into Oread when you press **Pull from the router**, and the **Wepwawet** page can pull it
every night too:

1. On the router: Settings, **New in the starting copies**, add the **oread** door if it's
   offered; then Security, API keys: make a token tied to the oread door and copy it.
2. On Oread's **Wepwawet** page: the router's address (its chat door, for example
   `http://192.168.1.20:8770`), **Save**; paste the token under **Its token**, **Save**
   (a super user; it goes in the vault as `wepwawet`).
3. **Pull from the router.** Each line shows what was really said, what Oread heard, how
   many times, the devices, the speech model that heard it and the clips (play them while
   Oread still has them). Each clip is looked up in Oread, so its models are kept with the
   line even after the clip is gone, and a clip a mishearing was heard in is no longer
   trimmed from the Learn list. A line the router no longer has stays, marked **gone**.

The address can also be set in `settings.yaml` (`wepwawet: url`); one saved on the page is
kept in `data/wepwawet.yaml` and wins. With no address Oread doesn't use the router at all.

### The Wepwawet page

How Oread works with the house router, all in one place:

- **Enabled.** Off: Oread works on its own; nothing is pulled from or told to the router.
- **The house router:** its address and its token (above).
- **People: Keep people in step.** A person added or renamed in Oread is added or renamed in the
  router's people grid too, by their official name (the one their voice ID has). A person deleted
  in Oread is only taken out of Oread's column there: the router keeps the row, with their names in
  other apps, for you to decide on its People page. The table shows each of Oread's people and
  whether the router has them; **Add the missing ones to the router** adds the rest. The router
  needs its oread door to cover `/people/oread` (it does in its starting copy).
- **Mishearings: Pull them every night**, at the hour you pick (this server's clock).

### Patch: a device that hears itself

Some devices' microphones hear their own speaker: the assistant answers itself, or repeats what it
just said. Oread can learn the assistant's own voice and say when it's the assistant, so the router doesn't
take it for a request:

1. **Devices**: match the device to its Home Assistant device (if it isn't already).
2. **Settings**, **Devices**, the device, **Patch: It hears its own speaker**: on.

The assistant's voice is never on **People**: that page is people only.

That's all. Oread asks Home Assistant which voice the device answers in (its pipeline's
text-to-speech voice), has that voice say 30 lines, and learns them as the assistant's voice,
named after it (for example "en_GB-cori-medium"). It takes a minute or two; **Assistant's voice**, just
below the switch, shows how it went. It looks again whenever Oread starts, so a device moved to
another voice gets that one learned too; **Learn now** looks straight away, and **Learn them over**
says the lines again (after you change them: put your own in `data/voice_lines.txt`, one per line;
its usual answers work well).

The clean lines sound too unlike its voice coming through the device's speaker and the room, so
Oread then learns its real voice from the house router: each request the router found was its own
answer coming back (by its words) comes with each pull of the mishearings (the Wepwawet page; switch
**Pull them every night** on), and its clip goes on its voice for that device. Once there are 5 of
them (`assistant_voice: real_clips_first` in settings.yaml), the assistant's voice is made from those alone,
and **Assistant's voice** says **Knows its voice as this device hears it**.

A voice that isn't Home Assistant's text-to-speech: add it by hand under **Assistant's voice**, **By hand**,
then assign clips of it speaking to it on **Learn**, the same way as a person's (about 10 are
enough). On **Learn** the assistants' voices are listed apart, after the people.

The assistant's voice is never a person: the router doesn't see it in your people. A device that cancels its
own echo doesn't need this.

### Explore: slice the clips and the mishearings

The **Explore** page puts every clip Oread heard, and every word of the mishearings pulled from
the house router, in a pivot table you can rearrange:

- **Clips heard** / **Words misheard**: the two sets of rows.
- Drag a field (Speaker, Speaker is (a person or an assistant's voice), Device, Speech model, Day, Hour, Weekday, Score band, Speech over noise
  band, Misheard, Kind...) into the rows or the columns; click the small arrow on a field to pick
  which of its values count.
- Pick what each cell shows: a count, an average or sum of a number (Score, Seconds, Speech dB...),
  or **Share that are yes (95% range)**, for example the share of clips Misheard. Its range is
  honest about small counts: "50% (9-91%) of 2" means two clips aren't enough to say.
- Pick how it's drawn: a table, a heatmap (darker is more), or a table to copy (TSV).
- **Click a cell** to see and hear the clips behind it.
- **Download these rows (CSV)**: the rows your filters let through, for a spreadsheet or any
  statistics program.

Your layout is remembered in this browser; **Start the layout over** goes back to the first one.

### OSPRI: gather records for analysis

OSPRI (Oread STT Pattern Recognition Improvement) gathers the records for working out, from your
mishearings, how to correct what speech-to-text hears. The analysis is done outside Oread:

- **OSPRI** page, **Gather records**: on, and every request adds a record (when, the device, who spoke
  with the voice ID's label and score, the speech and voice models, what was heard, and its clip). They
  stay when the clip is trimmed from Learn. Off by default; about 300 bytes a request.
- **Export CSV** or **Export JSON**: every record, each with whether it was misheard and what was
  meant, joined in from the mishearings pulled from the house router. Analyse them anywhere.

Applying the corrections from that analysis (OSPRI lite) comes in version 1.1.0.

## 12. Back up

Back up two folders from the server, **separately**:

- `data/`: voice clips, people, accounts, settings, stored keys (encrypted).
- `keys/`: the key that unlocks the stored keys, and the household
  certificate. Keep this apart from `data/`: a copy of `data/` alone holds no
  usable keys. Without `keys/` you'll have to re-enter stored keys and
  reinstall the certificate on your devices.

`logs/` is optional. `models/` is downloaded again if lost.

## 13. Update

```bash
cd ~/docker/oread
git pull
docker compose up -d --build
```

Your own settings in `data/settings.yaml` are kept. (If `git pull` complains
about local changes, see [Troubleshooting](#git-pull-says-your-local-changes-would-be-overwritten).)

## 14. Stop, start over, or move Oread

Run these from inside `~/docker/oread`.

**Stop and start:**

```bash
docker compose down        # stop Oread and remove its container (your data stays)
docker compose up -d       # start it again
```

**Make sure no Oread is running anywhere**, for example before reinstalling,
or if an older copy might have been started from another folder:

```bash
docker ps -a --filter name=oread                 # every Oread container, running or stopped
docker stop oread && docker rm oread             # for each name listed (data stays on disk)
sudo ss -ltnp | grep ':103[1-3][0-9]'            # anything still holding Oread's ports
```

The last command should print nothing. A `python3` at the end of a line
means an Oread started by hand, outside Docker: stop it with
`pkill -f "python3 -m oread"`.

**Start over with a fresh install, keeping the old one as a backup.**
Everything Oread knows (people, clips, accounts, keys) is in the old folder,
so set it aside rather than deleting it:

```bash
cd ~/docker
docker ps -a --filter name=oread                 # should list nothing; stop any first (above)
sudo mv oread oread-old                          # keep the old install, untouched
```

Then install again from [section 2](#2-install). If you want the old install
back later, stop the new one and swap the folders back. To save the model
download, you can copy the old models into the new install before its first
start: `sudo cp -r ~/docker/oread-old/models/. ~/docker/oread/models/` and
then `sudo chown -R $(id -u):$(id -g) ~/docker/oread`.

**Move Oread to another folder:** stop it (`docker compose down`), move the
whole folder (`sudo mv`, then the `chown` above for the new place), `cd`
there and `docker compose up -d`. Everything travels with the folder.

## 15. Troubleshooting

Problems people have actually run into, newest at the top of each group.

### Install and starting up

#### The page won't load right after the first start
On the first start Oread downloads its models before it listens. Watch
`docker compose logs -f oread` until it says Oread's pages are up.

#### Can't save `data/settings.yaml`: "pkexec", "Not authorized" or "Permission denied"
The folder belongs to root, so a desktop text editor asks for administrator
rights (through pkexec) and fails. It happens when Docker made the folders
before they existed (for example after cloning with `sudo`). Give them back to yourself, then edit normally:

```bash
cd ~/docker/oread
sudo chown -R $(id -u):$(id -g) ~/docker/oread
```

If your user and group numbers aren't 1000, also set them in `.env`
([section 2](#2-install)).

#### Oread stops with "Permission denied" in its log
Oread runs as user 1000 (or the numbers in `.env`) and can't write to its
folders. Use the same `chown` command as above, check `.env` matches
`id -u` and `id -g`, and start it again with `docker compose up -d`.

#### Nothing shows after a restart
`docker compose restart` doesn't show the log. Run
`docker compose logs -f oread` to watch it.

#### `git pull` lists files and says "Please move or remove them before you merge"
It happens when Oread's files were copied in by hand. Git found copies of Oread's own files that it doesn't track, and
won't overwrite them. Make the folder match the published version exactly;
your data folders (`data/`, `keys/`, `logs/`, `models/`) are never touched:

```bash
cd ~/docker/oread
cp settings.yaml ~/settings.yaml.bak      # just in case it was edited
git fetch
git reset --hard origin/main
```

If `settings.yaml` had your changes in it, move them into `data/settings.yaml`
([section 3](#3-your-own-settings)).

#### `git pull` says your local changes would be overwritten
Someone edited `settings.yaml` directly. Move your changes into
`data/settings.yaml` ([section 3](#3-your-own-settings)), then
`git checkout settings.yaml` and pull again.

### Signing in and the pages

#### The browser says the connection isn't private, or the certificate isn't valid
Expected until you pick one of the ways in [section 5](#5-https-and-the-browser-warning).

#### Still a warning after installing the household certificate
- The address in your browser must be one the certificate names. Put the
  server's address and name in `api.tls_names` ([section 3](#3-your-own-settings))
  and restart Oread; it makes a new certificate to match.
- On an iPad or iPhone, turn on full trust in **Certificate Trust Settings**
  ([section 5A](#a-install-oreads-household-certificate)).
- Firefox needs the certificate in its own list.
- Restart the browser after installing.

#### The page is blank, or the connection resets
Make sure the address starts with `https://`. The port answers only HTTPS.

#### "That setup code isn't right"
Read the code with `cat data/setup-code.txt` (from inside `~/docker/oread`)
and type it again; case and spaces don't matter. It stays the same until
it's used.

#### `cat data/setup-code.txt` says "No such file or directory"
Either Oread hasn't finished starting yet (wait
until `docker compose logs oread` shows the setup code, then try again), or
you ran it from another folder (`cd ~/docker/oread` first), or setup is
already done and the file was deleted (sign in instead). If the log says it
couldn't save the setup code, Oread can't write to `data/`: see "Oread stops
with Permission denied" above. The code is in the log either way.

#### "Too many wrong setup codes"
After five wrong tries Oread stops accepting the code. Restart it
(`docker compose restart oread`) for five more tries; the code stays the same.

#### "Too many wrong passwords"
That username is locked for 15 minutes. Wait, or have someone with a higher
role reset it, or reset it on the server
([section 6](#6-people-and-roles)).

### Hearing and speed

#### Slow replies on an older processor
Some speech models are much slower on processors without AVX2 (Stats shows
whether yours has it). On a Xeon without AVX2, per short command: Moonshine
(the default) 0.4 s on 4 cores and 1.3 s on 2; Parakeet 1.3 s on 4 cores and
3.5 s on 2. Stay with Moonshine on older processors with few cores.

#### Try it: "The browser wasn't allowed to use the microphone"
The browser asked for the microphone and the answer was no (or it was
blocked earlier). Allow it for Oread's page: in most browsers, click the
microphone or lock icon at the left of the address bar. Browsers only allow
the microphone on `https://` pages, which Oread always is.

#### A very short command comes back with no words
Very short clips (around a second and a half or less) sometimes come back
empty from the default model. Speak the whole command; satellites normally
send enough.

#### Trimming the quiet: faster replies, and no words made up from noise
A device can trim before speech-to-text (**Settings**, **Devices**, **Trim the
quiet after speech**). The voice detector then finds the speech: a clip with
no speech at all isn't decoded (no words, as when nothing is heard), and the
quiet after the last speech is cut, keeping **Kept after speech** seconds (0.6).
The start is never cut; speech-to-text needs it. Who spoke and the saved clip
always use the whole clip. The detector's settings are on **Settings**,
**Models**, under **Voice detectors**. Before turning it on, check them against
your clips; no clip assigned to a person should be skipped:

    docker compose exec oread python tools/trim_check.py

If one is, lower **Sure at** (the threshold) and run it again. A low threshold
also makes `tools/client.py` wait a little longer before it decides you've
stopped talking.

#### Replies slow down when several satellites talk at once
Oread works on two requests at the same moment by default; more wait in line.
Stats shows the longest wait. If waits matter, raise `server.max_concurrent`
in `data/settings.yaml` and restart, and make sure the server has the cores
for it.

### Names and certificates

#### A DuckDNS (or own-domain) name doesn't open at home
Some routers and ad blockers (Pi-hole, for example) refuse to answer when a
public name points to a home address, as a guard against a known attack.
Allow that one name in the router's or Pi-hole's settings (often called DNS
rebind protection).

#### Everything worked, then stopped after a router or power restart
An address probably changed: the router handed the client (or Oread's
server) a different one. Look at **Connections**, **Permitted clients**,
**Recently refused**: if the client is there under a new address, press
**Allow**. If Oread's server moved, update its address in your voice
assistant and in `api.tls_names` ([section 3](#3-your-own-settings)). Then give
both fixed addresses ([section 1](#1-what-you-need)).

#### Every refused address shows as 172.17.0.1 (or another 172.x address)
Docker is hiding the real addresses, so Oread sees Docker's own. Adding that
address would let everyone in, so don't. This happens with some Docker setups
(rootless Docker, or with its "userland proxy"); the usual Docker install
on Linux shows real addresses. Until it's sorted out, limit the satellite
ports with the server's firewall instead.

#### Home Assistant isn't told who spoke
Check **POST /home-assistant/test** on the API page: it says whether the
address is wrong or the token was refused. **GET /home-assistant** shows the
last attempt. A slow or stopped Home Assistant never holds up Oread's replies
by more than half a second.

---

## Appendix A: Example: connecting Home Assistant

*One example of a client. Other systems that speak the Wyoming protocol
connect the same way ([section 9](#9-connect-a-client)).*

### Before you start

- Oread is running and you've tried it from your computer
  ([section 8](#8-try-oread-from-your-computer)).
- Home Assistant has a fixed address ([section 1](#1-what-you-need)). Find it
  in Home Assistant: **Settings**, **System**, **Network** (the IPv4 address
  of its network adapter).
- In Oread, **Connections**, **Permitted clients**: add that address.

### Use Oread for a satellite's speech-to-text

For each satellite (Voice PE, tablet, and so on):

1. In Oread, **Devices**: note the satellite's port (add a device for it if
   there isn't one).
2. In Home Assistant: **Settings**, **Devices & services**, **Add
   integration**, **Wyoming Protocol**. Host: Oread's server address. Port:
   that satellite's port. Each port is added as its own Wyoming entry.
   Home Assistant names every one of them "oread", whichever port it is.
   Rename the entry, and its speech-to-text entity, after the satellite
   (for example "Oread voice-pe"), so the speech-to-text list tells them apart.
   Oread doesn't name them for you on purpose: you keep the names in step.
   If you rename the device in Oread later, rename it in Home Assistant too.
3. **Settings**, **Voice assistants**, open the assistant that satellite
   uses, and pick the new Oread entry as **Speech-to-text**.
4. Say something to the satellite. It should answer as usual, and the clip
   appears on Oread's **Learn** page with the satellite's name. Home
   Assistant needs no restart: the new speech-to-text is used from the next
   thing you say.

To watch it happen, on the server:

```bash
cd ~/docker/oread && docker compose logs -f oread
```

Each request adds a line naming the device, how long the audio was, the
time it took, who Oread thinks spoke, and the words, for example
`voice-pe audio=2.1s work=640ms stt=610ms voiceprint=140ms ... speaker=unknown text='turn on the kitchen light'`
(work: speech to text and the voiceprint together, worked out at the same time; stt and
voiceprint: each on its own).
Press Ctrl+C to stop watching (Oread keeps running). In Home Assistant,
**Settings**, **Voice assistants**, the assistant's **⋮** menu, **Debug**
shows the same request from Home Assistant's side, including which
speech-to-text it used.

If a satellite stops answering, look at **Connections**, **Permitted
clients**, **Recently refused** in Oread: Home Assistant's address there means
it isn't permitted (press **Allow**). To go back to Home Assistant's own
speech-to-text, pick it again in step 3.

Note: two satellites that share one assistant in Home Assistant also share
its speech-to-text entry, so Oread hears them as one device. To tell them
apart, give each satellite its own assistant.

### Tell Home Assistant who spoke

Home Assistant keeps only the words Oread hears, not who said them, so Oread
can set a sensor per device: `sensor.oread_<device>_speaker`, holding the
person's name (or `unknown`). Automations can use it ("if Ann asked, give
Ann's briefing"). The same address and token let each clip record its
device's settings there (match each device on **Settings**, **Devices**,
**Voice assistant device**).

1. In Home Assistant: your profile (bottom left), **Security**, **Long-lived
   access tokens**, **Create token**, name it "Oread", copy it.
2. Store it in Oread under the name `home-assistant`. For now this is on the
   API page (`/docs`): **PUT /vault/home-assistant**, signed in as a super
   user, with the token as the value. A page for it is planned.
3. Add Home Assistant's address to `data/settings.yaml` and restart Oread:

   ```yaml
   home_assistant:
     url: http://<Home Assistant's address>:8123
   ```

4. Check it: **POST /home-assistant/test** on the API page (for now).

Home Assistant's history keeps these sensors; to leave them out, exclude
`sensor.oread_*` in Home Assistant's recorder settings. **Report who spoke** is
off for every device to start with; tick it on **Settings**, **Devices** for
each device that should set the sensor. If you use a Wepwawet router, it gets
the speaker another way, so leave it off for the devices it serves.

---

## Appendix B: For programmers: the API and the listening ports

*For people writing programs that talk to Oread. Nobody needs this to set up
or use Oread.*

Oread has two ways in:

- **The API** on port 10311 (HTTPS): everything the pages do, as JSON. An
  interactive version with "Try it out" buttons is at
  `https://<server>:10311/docs` (sign in on Oread's pages first; otherwise it
  sends you to the sign-in screen), and the machine-readable description is
  at `/openapi.json` (a sign-in or a token).
- **The listening ports** (10310, 10312-10339, one per listening device):
  the Wyoming protocol, for sending audio and getting back text and the
  speaker. Only permitted clients may connect (section 7); with none listed,
  only addresses on the local network.

Nobody gets an answer from the API without signing in or a valid token,
apart from signing in itself, first-run setup and the certificate download.
A test checks every call for this, so a new call can't slip through open.

### Signing in to the API

Programs use an **API token**. Make one on the server
(`docker compose exec oread python -m oread.auth create <name> [role]`) or
with `POST /tokens` (shown once; copy it). Send it on every call:

```
Authorization: Bearer oread_...
```

Each token has a role, like a person, and can do only what that role allows
(the **Who may** column below): `viewer` < `reviewer` < `administrator` <
`super`. A token can't have a higher role than the person who made it.

Oread's own pages use a **session** instead: `POST /api/session` with
`{"username", "password"}` sets an `oread_session` cookie (HttpOnly,
SameSite=Strict). Calls that change something with a session cookie must also
send `X-Requested-With: oread`, which a page on another site can't add.

Oread uses its household certificate unless you've given it another
([section 5](#5-https-and-the-browser-warning)). From a program, either trust
it (download `/ca.crt`) or, for a quick test on your own network,
turn certificate checks off (`curl -k`).

```bash
curl --cacert oread-household-ca.crt -H "Authorization: Bearer oread_..." \
  https://192.168.1.20:10311/status
```

### Answers and errors

Answers are JSON. Errors are JSON too, with a `detail` saying what's wrong:

| Code | Means |
| --- | --- |
| 400 | the request doesn't make sense (the detail says why) |
| 401 | no token or session, or it isn't valid: sign in |
| 403 | signed in, but your role can't do this (or a change from a session without `X-Requested-With: oread`) |
| 404 | no such thing (clip, person, device, key) |
| 409 | it clashes with what's there (a name already used, the last super user) |
| 422 | a field is missing or the wrong type (the detail lists them) |
| 429 | too many wrong passwords: that name is locked for a while |

### Every call

Fields marked `?` are optional. "Who may" is the lowest role allowed.

<!-- api-reference:start (generated by tools/api_reference.py; don't edit by hand) -->

#### Signing in (no sign-in needed)

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /api/setup` | anyone | - | Does Oread still need its first user? |
| `POST /api/setup` | anyone | `code`: string, `username`: string, `password`: string | First run: the setup code (data/setup-code.txt or the log), then the super user's name and password |
| `GET /api/session` | anyone | - | Who is signed in, and what they may use |
| `POST /api/session` | anyone | `username`: string, `password`: string | Sign in |
| `DELETE /api/session` | anyone | - | Sign out |
| `GET /ca.crt` | anyone | - | Oread's household certificate authority, to install on your devices |

#### Your account

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `POST /api/account/password` | anyone signed in | `current`: string, `new`: string | Change your own password |
| `GET /guide` | anyone signed in | - | The user guide (Markdown), as shipped with this version of Oread |

#### Status

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /status` | viewer | - | Version, devices and counts |

#### Resources

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /resources` | viewer | - | Memory, CPU, disk and request speed (for choosing hardware) |
| `GET /stats/time` | viewer | query `tz`? | Where the time goes: each step, last 24 hours, by day, week and month |
| `GET /measures` | viewer | query `device`, `limit`? | How a device's requests sounded, newest last (kept after clips go) |

#### Phrases

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /profiles/{name}/phrases` | viewer | query `top`? | A person's most-used phrases and words |

#### Clips

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /clips` | reviewer | query `status`?, `device`?, `limit`?, `person`? | Clips heard, waiting or assigned (newest first) |
| `GET /clips/{clip_id}` | reviewer | - | One clip |
| `DELETE /clips/{clip_id}` | reviewer | - | Discard a clip |
| `GET /clips/{clip_id}/audio` | reviewer | - | Play a clip (WAV) |
| `POST /clips/{clip_id}/assign` | reviewer | `profile`: string | Assign a clip to a person (creates the profile if new) |
| `POST /clips/{clip_id}/unassign` | reviewer | - | Take a clip back off its profile |
| `GET /explore` | reviewer | - | Every clip heard and every word misheard, as rows for a pivot table |

#### Profiles

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /profiles` | viewer | query `all`? | People and how many clips each has |
| `POST /profiles` | reviewer | `name`: string, `kind`?: `person` \| `assistant` | Create a profile |
| `GET /assistant-voices` | viewer | - | The assistant voices learned from text-to-speech |
| `POST /assistant-voices/learn` | reviewer | `again`?: boolean | Learn the assistant's own voice now, from the voice each device answers in |
| `PATCH /profiles/{name}` | reviewer | `new_name`: string | Rename a profile |
| `DELETE /profiles/{name}` | reviewer | - | Delete a profile (its clips go back to waiting) |
| `GET /retrain` | viewer | query `device`, `person` | A person's clips on a device: the call each got when heard, and its score now |
| `POST /retrain` | reviewer | `device`: string, `person`: string, `clips`: list of string, `why`?: string | Retrain: a trial voiceprint for a person on a device, from the ticked clips |
| `GET /retrain/blind` | viewer | query `device`, `person` | Blind test: every clip on the device, who it would name with the trial |
| `POST /retrain/accept` | reviewer | `device`: string, `person`: string | Accept the trial: it decides on that device from now on |
| `POST /retrain/reject` | reviewer | `device`: string, `person`: string | Reject the trial: nothing is kept |

#### Devices

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /devices` | viewer | - | Listening devices, their ports and models |
| `POST /devices` | administrator | `name`: string, `type`?: string, `port`?: integer, `stt_model`?: string, `speaker_model`?: string | Add a device (starts listening at once) |
| `PATCH /devices/{name}` | administrator | `new_name`?: string, `stt_model`?: string, `speaker_model`?: string, `assistant_device`?: string | Rename a device, or change its models ("" = back to the default) |
| `DELETE /devices/{name}` | administrator | - | Remove a device (stops its port; its clips are kept) |
| `GET /device-types` | viewer | - | Kinds of device: label, note, starting models, which devices use each |
| `POST /device-types` | administrator | `name`: string, `label`: string, `note`?: string, `stt_model`?: string, `speaker_model`?: string | Add a device type (saved in data/device-types.yaml) |
| `PATCH /device-types/{name}` | administrator | `label`?: string, `note`?: string | Change a type's label or note |
| `DELETE /device-types/{name}` | administrator | - | Remove a type no device uses |
| `GET /models` | viewer | - | Models a device can use: memory, notes, who uses them |

#### Settings

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `PATCH /models/{kind}/{name}` | administrator | `settings`: object | Change a model's own settings (every device using it picks them up now) |
| `POST /models/{kind}/{name}/default` | administrator | - | Make this the default model (devices without their own choice switch now) |
| `DELETE /models/{kind}/{name}/settings` | administrator | - | Put a model's settings back to the shipped ones |
| `GET /imports` | viewer | - | Where every model comes from: download address, files, license (the Imports page) |
| `POST /imports/{kind}` | administrator | `name`: string, `fields`: object | Add a model to the list (saved in data/models.yaml) |
| `PUT /imports/{kind}/{name}` | administrator | `fields`: object | Change where a model comes from (devices using it load it again) |
| `DELETE /imports/{kind}/{name}` | administrator | - | A shipped model back to models.yaml's entry; a model you added off the list |
| `POST /imports/{kind}/{name}/check` | administrator | - | Check that a model's download address answers (downloads nothing) |
| `GET /settings` | viewer | - | Each device's models and speaker knobs |
| `PATCH /settings/speaker` | administrator | query `device`?; `min_training_seconds`?: number, `unknown_below`?: number, `match_above`?: number, `phrase_from`?: number, `phrase_to`?: number, `phrase_mode`?: `off` \| `shadow` \| `on`, `publish_speaker`?: boolean, `trim_silence`?: boolean, `hears_own_speaker`?: boolean | Change speaker knobs now (all devices, or one with ?device=) |
| `DELETE /settings/speaker` | administrator | query `device`? | Put speaker settings back to the model's, type's and settings.yaml values (now) |

#### Users

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /users` | administrator | - | Everyone who can sign in |
| `POST /users` | administrator | `username`: string, `password`: string, `role`: `viewer` \| `reviewer` \| `administrator` \| `super` | Add a person (roles below your own) |
| `PATCH /users/{name}` | administrator | `role`?: `viewer` \| `reviewer` \| `administrator` \| `super`, `password`?: string | Change a person's role or reset their password (signs them out) |
| `DELETE /users/{name}` | administrator | - | Remove a person |

#### Audit

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /audit` | administrator | query `limit`? | Who changed what, newest first |

#### Tokens

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /tokens` | administrator | - | API tokens (names and last use, never the tokens) |
| `POST /tokens` | administrator | `name`: string, `role`?: `viewer` \| `reviewer` \| `administrator` \| `super` | Create an API token (shown once; copy it) |
| `DELETE /tokens/{name}` | administrator | - | Revoke an API token |

#### Home Assistant (reporting who spoke)

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /home-assistant` | administrator | - | Telling Home Assistant who spoke: address, token and the last attempt |
| `GET /assistant/devices` | administrator | - | The voice assistant's devices, to match each listening device to one |
| `POST /home-assistant/test` | administrator | - | Check the address and token (changes nothing) |

#### Mishearings (pulled from the house router)

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /mishearings` | reviewer | - | The mishearings pulled from Wepwawet Veil (the house router), with their clips |
| `POST /mishearings/pull` | reviewer | - | Pull the router's mishearings now and merge them in |

#### The house router's address

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /wepwawet` | administrator | - | How Oread works with the house router, and its people beside ours |
| `PATCH /wepwawet` | administrator | `enabled`?: boolean, `people_sync`?: boolean, `nightly_pull`?: boolean, `pull_hour`?: integer | Switch Oread's work with the router on or off, people in step, the nightly pull |
| `POST /wepwawet/people` | administrator | - | Add every person here the router doesn't have yet |
| `PUT /mishearings/router` | administrator | `url`: string | Set the router's address for pulling (empty: off) |

#### Access

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /access` | super | - | Clients permitted on the listening ports, and who was recently refused |
| `PUT /access` | super | `allowed_clients`: list of string | Set the clients permitted on the listening ports |

#### Vault

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /vault` | super | - | Keys Oread uses to reach other programs (names and hints, never the keys) |
| `PUT /vault/{name}` | super | `value`: string, `service`?: string, `note`?: string | Add or replace a key |
| `DELETE /vault/{name}` | super | - | Delete a key |

#### Try

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `POST /api/try` | reviewer | query `device`, `rate`? | Try it: send audio as if from a listening device; get the words and the speaker |

#### Sample

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /sample` | viewer | - | The sample household: whether it's here, and what it holds |
| `POST /sample` | administrator | - | Add the sample household (about a minute) |
| `DELETE /sample` | administrator | - | Remove the sample household, and nothing else |

#### Compare

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `POST /devices/{name}/compare` | administrator | `kind`: `speech` \| `voice`, `model`: string, `limit`?: integer | Compare a model on this device's own clips (runs only when asked) |
| `GET /compare` | administrator | - | The running or last comparison, with results |
| `DELETE /compare` | administrator | - | Stop the running comparison, or put away a finished one |
| `POST /compare/judge` | administrator | `clip`: string, `choice`: `current` \| `candidate` \| `neither` \| `` | Speech comparison: say which words were right for a clip |

#### Ospri

| Call | Who may | Takes | What it does |
| --- | --- | --- | --- |
| `GET /ospri` | reviewer | - | OSPRI: whether records are gathered, how many, over which dates |
| `PATCH /ospri` | administrator | `gather`: boolean | OSPRI: gather records, or stop (kept in data/ospri.yaml) |
| `GET /ospri/records` | reviewer | query `format`? | OSPRI: every record, with what was meant joined in (JSON or CSV) |

<!-- api-reference:end -->

### The listening ports (Wyoming)

Each listening device has its own port; the port is how Oread knows which
device it's hearing. Only permitted clients may connect
([section 7](#7-who-may-connect-permitted-clients)); anything else is hung up
on at once. One request per connection:

1. Optionally `describe`; Oread answers with `info` (its speech-to-text
   model).
2. `transcribe` (optional), `audio-start` with `rate`, `width` and
   `channels`, then `audio-chunk` events, then `audio-stop`. 16 kHz, 16-bit,
   mono is what voice satellites send and what Oread works in; other rates
   are converted.
3. Oread answers with one `transcript` event and closes the connection:

```json
{"type": "transcript",
 "data": {"text": "turn on the kitchen lights",
          "context": {"speaker": "Ann", "label": "known", "guess": "Ann",
                      "score": 0.71, "by": "voice", "device": "voice-pe",
                      "clip": "20261012-101530-123-voice-pe"}}}
```

| Field | Means |
| --- | --- |
| `speaker` | the person, or `null` when Oread isn't sure |
| `label` | `known`, `maybe`, `unknown`, or `too short` (under the length a voiceprint needs) |
| `guess` | the closest person even when unsure (`null` with nobody taught yet) |
| `score` | how close the voice is to that person, 0 to 1 |
| `by` | `voice`, or `voice+phrase` when a person's habit phrases settled a "maybe" |
| `device` | which listening device heard it |
| `clip` | the saved clip's id (on the Learn page), or `null` when nothing was heard |
| `stt_ms`, `voiceprint_ms` | how long speech to text and the voiceprint each took, in ms (they run at the same time) |

Home Assistant keeps only `text`; programs that speak Wyoming themselves
(like a Wepwawet router) get all of it.

