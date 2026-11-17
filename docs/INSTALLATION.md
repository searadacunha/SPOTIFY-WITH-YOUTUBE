# Installation

Target: a fresh macOS machine, an Android TV / Google TV on the same network with
SmartTube and Spotify installed, and no prior setup. Follow the steps in order;
each one can be verified before the next.

## 1. Host tools

```sh
brew install python@3.12 android-platform-tools ffmpeg node
python3.12 --version
adb --version
ffmpeg -version | head -1
node --version
```

The service runs under launchd with `PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`.
Tools installed elsewhere must be given as absolute paths in `config.json`
(`adb_path`, `ffmpeg_path`, `node_path`).

## 2. Project

```sh
git clone https://github.com/searadacunha/Spotify-With-Youtube.git
cd Spotify-With-Youtube
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests
```

Expected: `OK` with no failures. The unit tests touch neither the network nor the TV.

## 3. TV side

1. Install SmartTube from its official source and open it once:
   [docs/SMARTTUBE.md](SMARTTUBE.md).
2. Enable developer options, ADB debugging and (Android 11+) wireless debugging,
   then pair and connect from the Mac: [docs/ADB.md](ADB.md). End state:

   ```sh
   adb devices
   # 192.168.x.x:5555   device
   ```
3. Send one video by hand to prove the TV side independently of this project:
   [docs/SMARTTUBE.md, "Manual test"](SMARTTUBE.md#manual-test-do-this-first).

## 4. Configuration

```sh
cp config.example.json config.json
```

Edit `config.json`: set `tv_target` to the exact `host:port` shown by `adb devices`.
Leave the rest initially. By default, `spotify_connect_autostart` is `true`: a new Spotify Connect song selected on the phone and played on the TV can trigger SmartTube without first opening Spotify on the TV. Set it to `false` for manual-only activation. The complete defaults are in `config.example.json`;
matching settings are explained in [MATCHING.md](MATCHING.md). The file is git-ignored.

### If phone playback does not create a Spotify TV media session

The default `spotify_source: tv` reads the Android media session from the Spotify
TV application. Some phone-to-TV connections instead use Google Cast. To monitor
the Spotify Connect/Cast device without opening Spotify TV, use the optional
`spotify_source: connect` mode (requires Spotify's Web API):

1. Create a Spotify developer app with redirect URI `http://127.0.0.1:8765/callback`.
   Development Mode requires a Spotify Premium account and is rate-limited.
2. Run `cp .env.example .env`, set `SPOTIFY_CLIENT_ID` to your app's client ID,
   then run `./smarttube login` to grant the required read-only scopes.
3. From Spotify on the phone, choose the TV and start a song. Run
   `./smarttube devices` to find the exact active device ID. If it has no ID or
   is not listed, the Spotify API cannot identify this receiver reliably.
4. Set `"spotify_source": "connect"` and
   `"spotify_connect_device_id": "YOUR_TV_DEVICE_ID"` in your private `config.json`.
   Leave `spotify_connect_autostart: true`. Restart the service.

The bridge then reads playback only for that exact device; music played on the
phone or another speaker will not take over the TV. SmartTube is still opened
by ADB, and the Mac must be running. This is a poll-based integration and can be
delayed by Spotify API limits. The receiver may be paused when SmartTube takes
audio focus; use the phone to select another song. Only the native TV source
supports the existing automatic clip-end Spotify next-track handoff.

For `spotify_source: web` (unfiltered listening, no auto-activation), only the
Spotify API login is needed; `connect` additionally requires the device ID.

## 5. Checks

```sh
./smarttube check
```

Prints: whether `config.json` exists, the resolved paths of `adb`, `ffmpeg`, `node`,
the TV probe presence, the yt-dlp version, the Spotify source and the track currently
playing (play something in the Spotify app of the TV first, in **audio** mode), and
confirms the TV is reachable with the target package installed.

```sh
./smarttube test
```

One dry run: reads Spotify, searches, ranks, verifies audio if needed, prints
`SELECTED …` and `DRY-RUN: no video launched`. Nothing is sent, nothing is cached.
The first resolution of a track can take tens of seconds.

## 6. Service

```sh
./smarttube start      # creates ~/Library/LaunchAgents/local.spotify-smarttube.plist for this checkout
./smarttube status
./smarttube logs       # Ctrl-C stops the tail only
```

The service starts disarmed. To activate it, select your TV as the Spotify Connect destination **from Spotify on the phone**, then play a song. A fresh playing Spotify TV media session automatically arms the bridge; opening Spotify on the TV is not required. You can still start a song in Spotify TV or explicitly run `./smarttube resume` while SmartTube plays. Switching to another app normally disarms sync; starting a new Spotify TV track (including via Connect) re-arms it. Details and
uninstallation: [docs/MACOS_SERVICE.md](MACOS_SERVICE.md).

## Upgrading

```sh
./smarttube stop
git pull
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests
./smarttube start
```

After an upgrade/start, select the TV with Spotify Connect and play a new song, pick one in Spotify TV, or resume while SmartTube plays.
A new `SCORING_VERSION` invalidates cached matching decisions but never the last sent track. If yt-dlp stops
working because YouTube changed, bump `yt-dlp` **and** `yt-dlp-ejs` together to the
versions yt-dlp declares compatible.

## Rebuilding the TV probe (optional)

Only if you edit `android/MediaProbe.java`. Needs a JDK (17 recommended) and the
Android SDK command-line tools with one platform and one build-tools package:

```sh
brew install --cask android-commandlinetools
brew install openjdk@17
sdkmanager "platforms;android-34" "build-tools;35.0.0"
.venv/bin/python android/build.py      # autodetects; override with JAVA_HOME, ANDROID_SDK_ROOT, ANDROID_PLATFORM, ANDROID_BUILD_TOOLS
```

The script writes `android/classes.dex`; commit it together with the Java change.
With JDK 17, platform `android-34` and build-tools `35.0.0` the output is byte-for-byte
identical to the committed file (verified locally and in CI); newer toolchains produce
an equivalent but different binary.
