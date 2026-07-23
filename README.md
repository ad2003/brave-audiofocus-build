# Brave for Android AudioFocus Patcher

Patches the Brave Android APK so that Spotify, Tidal, and other music apps are no longer stopped when a video starts in Brave.

## The Problem

Brave requests `AUDIOFOCUS_GAIN` whenever a video starts playing (including autoplay and inline videos while scrolling). This forces other audio apps to stop completely — not duck, not pause temporarily, just stop. They do not resume when the video ends.

Upstream tracking issue: [brave-browser#54386](https://github.com/brave/brave-browser/issues/54386)

## Two Patch Modes

The patcher offers two different approaches. Pick one.

### `noop` — never request focus (default)

Replaces every `AudioManager.requestAudioFocus()` call with a no-op that returns `AUDIOFOCUS_REQUEST_GRANTED`.

```
video starts in Brave → no focus request → music keeps playing at full volume
```

Android does not enforce audio focus — it's a cooperative system. By not requesting focus at all, Brave never sends an `AUDIOFOCUS_LOSS` event to other apps.

Works with every music app, because it doesn't depend on the other app cooperating. Downside: Brave no longer participates in the audio focus system at all, so hardware media keys may stop controlling Brave playback, and Brave audio won't pause for incoming calls.

### `duck` — request duckable focus

Leaves the focus request fully intact but changes the requested type from `AUDIOFOCUS_GAIN` to `AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK`.

```
video starts in Brave → transient focus request → music fades down
video ends            → focus abandoned          → music fades back up
```

This is the behaviour you get from messaging apps playing voice notes, or from navigation prompts. Media keys keep working, because a real focus request still happens, and `abandonAudioFocusRequest()` still fires normally when playback ends.

Whether a given music app actually ducks rather than pauses is that app's own decision. **Verified working with Tidal.** Spotify is untested and may still pause — if so, use `noop`.

### Which one?

| | `noop` | `duck` |
|---|---|---|
| Music keeps playing | yes, at full volume | yes, at reduced volume |
| Works with any music app | yes | depends on the app |
| Hardware media keys | may stop working | keep working |
| Brave pauses for calls | no | see caveats |

If you want guaranteed uninterrupted music and don't care about media keys, use `noop`. If you want the more polite behaviour and your music app cooperates, use `duck`.

## Download

[![Latest Release](https://img.shields.io/github/v/release/ad2003/brave-audiofocus-build?label=Latest%20Patched%20APK)](https://github.com/ad2003/brave-audiofocus-build/releases/latest)

[⬇️ Download latest patched APK](https://github.com/ad2003/brave-audiofocus-build/releases/latest/download/brave_signed.apk)

The released APK is built with duck mode and is rebuilt automatically whenever a new Brave stable release is available. No manual steps needed.

If you need noop instead — for example if your music app pauses rather than ducks — build it yourself, see below.

## Installation via Obtainium (recommended)

The easiest way to stay updated is via [Obtainium](https://github.com/ImranR98/Obtainium):

1. Add this repo URL: `https://github.com/ad2003/brave-audiofocus-build`
2. Obtainium will notify you and install updates automatically

## Manual Installation

⚠️ Official Brave must be fully uninstalled first — the patched APK uses a different signing key, so it cannot update an installation that came from the Play Store or Aurora Store. Back up your Brave data with Brave Sync first!

```
adb uninstall com.brave.browser
adb install brave_signed.apk
```

Or copy the APK to your device and open it directly (requires "Install unknown apps" enabled).

Once you're running a patched build, switching between `noop` and `duck` needs no uninstall, since both are signed with the same key:

```
adb install -r brave_signed_duck.apk
```

## Build via GitHub Actions

Go to **Actions → Brave AudioFocus APK Patcher → Run workflow**.

Leave the version field empty for the latest stable, or enter a specific version like `v1.93.125`.

The released build uses duck mode. For noop, fork the repo and remove --mode duck from the patch step in build.yml.

You will need to supply your own signing key as repository secrets: `ANDROID_KEYSTORE` (base64-encoded), `ANDROID_KEY_ALIAS`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_PASSWORD`.

## Run Locally

```
# noop mode (default)
python3 patches/audiofocus_patch_precise.py BraveAndroid.apk brave_patched.apk

# duck mode
python3 patches/audiofocus_patch_precise.py --mode duck BraveAndroid.apk brave_patched.apk

zipalign -p -f 4 brave_patched.apk brave_aligned.apk
apksigner sign --ks your.jks --out brave_signed.apk brave_aligned.apk
```

## How It Works

The patcher opens the APK as a ZIP and edits the DEX bytecode in place. All other files are copied with their original compression settings — no repackaging, no reassembly. DEX checksums are recalculated afterwards.

### noop mode

Parses the DEX string pool and method table to find every `method_id` named `requestAudioFocus`, then scans the bytecode for `invoke-virtual` instructions referencing them. Each is replaced with `const/4 vX, 0x1` (`AUDIOFOCUS_REQUEST_GRANTED`) plus padding, and the following `move-result` becomes a `nop`. Instruction lengths are preserved exactly, so no offsets shift.

Typically applies 3 patches.

### duck mode

Targets `org.chromium.content.browser.AudioFocusDelegate.requestAudioFocus()`. Chromium already contains both focus types there — the transient path just isn't taken for regular media:

```
const/4 v0, 1        # AUDIOFOCUS_GAIN
const/4 v1, 3        # AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
if-eqz  v8, +4       # if (!transient) jump
move    v8, v1       # transient path  → 3
goto    +2
move    v8, v0       # regular media   → 1   ← patched to v1
iput    v8, v7, AudioFocusDelegate->a I
```

The patch repoints the second `move` to source from the register already holding `3`. That's a single byte (`0x08` → `0x18`), no instruction length changes.

Note that patching `const/4 v0, 1` directly would be wrong: `v0` is reused further down as `AudioAttributes.setUsage(1)` = `USAGE_MEDIA`. Changing it would reroute Brave's audio to `USAGE_VOICE_COMMUNICATION` and send playback to the earpiece.

The delegate is located structurally — class by type descriptor, method via class_data, then the `iput` to the int field, then the `move` before it, with source registers derived from the surrounding `const/4` instructions. If a future Brave build allocates registers differently, the patcher reports the mismatch and aborts rather than writing a bad byte.

Applies 1 patch.

Verified on Brave 1.93.125, both `BraveMonoarm64.apk` and `Bravearm64Universal.apk`.

## Caveats

- Play Store/Aurora Store auto-updates won't work (different signing key) — the GitHub Action handles rebuilds automatically
- Only tested on arm64 devices
- **`noop`:** hardware media keys (headphone play/pause) may no longer control Brave video playback
- **`duck`:** `AudioFocusDelegate.isFocusTransient()` checks whether the stored focus type equals `MAY_DUCK`, and Chromium uses that to decide how to handle focus *loss*. Since duck mode makes this always true, Brave video may behave differently when another app takes focus — for example resuming automatically after an incoming call instead of staying paused.
- **`duck`:** verified with Tidal. Spotify is untested and may still pause instead of ducking.

## A note on MAY_DUCK

Earlier versions of this README claimed that switching to `AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK` wouldn't help, because Tidal and Spotify set `setWillPauseWhenDucked(true)` internally.

That turned out to be wrong. Disassembly shows Brave itself calls `setWillPauseWhenDucked(false)`, and Tidal ducks correctly when it receives a transient request — as it already does for Signal voice messages and navigation prompts. The problem was never the receiving side; it was that Brave never sent a duckable request in the first place.

## Disclaimer

This project is provided as-is, without any warranty or guarantee of any kind. Use at your own risk.

- This is an unofficial, third-party modification of the Brave Browser APK
- The patched APK is not affiliated with, endorsed by, or supported by Brave Software, Inc.
- Installing a modified APK may void your warranty and violates Brave's terms of service
- The different signing key means you will not receive official Brave updates via Play Store or Aurora Store
- Security updates from Brave will not be automatically applied — you are responsible for keeping up with new releases
- The author(s) of this project accept no responsibility for any damage, data loss, security vulnerabilities, or other issues arising from the use of this software

By downloading and installing this APK you acknowledge that you understand and accept these risks.
