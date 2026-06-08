# Brave for Android AudioFocus Patcher

Patches the Brave Android APK so that Spotify, Tidal, and other music apps keep playing when a video starts in Brave.

## The Problem

Brave requests AUDIOFOCUS_GAIN whenever a video starts playing (including autoplay and inline videos while scrolling). This forces other audio apps to stop completely — not duck, not pause temporarily, just stop.

## The Fix

A single byte patch in the DEX disables all AudioManager.requestAudioFocus() calls:

BEFORE: video starts in Brave → AUDIOFOCUS_GAIN → Spotify/Tidal STOP
AFTER:  video starts in Brave → no focus request → Spotify/Tidal keep playing

Brave still plays audio normally. Android does not enforce audio focus — it's a cooperative system. By not requesting focus, Brave never sends an AUDIOFOCUS_LOSS event to other apps.

Note: Simply switching to AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK is not enough. Apps like Tidal and Spotify use setPauseWhenDucked(true) internally and will pause regardless.

## Download

[![Latest Release](https://img.shields.io/github/v/release/ad2003/brave-audiofocus-build?label=Latest%20Patched%20APK)](https://github.com/ad2003/brave-audiofocus-build/releases/latest)

[⬇️ Download latest patched APK](https://github.com/ad2003/brave-audiofocus-build/releases/latest/download/brave_signed.apk)

The patched APK is built automatically whenever a new Brave stable release is available. No manual steps needed.

## Installation via Obtainium (recommended)

The easiest way to stay updated is via Obtainium (https://github.com/ImranR98/Obtainium):

1. Add this repo URL: https://github.com/ad2003/brave-audiofocus-build
2. Obtainium will notify you and install updates automatically

## Manual Installation

⚠️ Brave must be fully uninstalled before installing the patched APK — the patched APK uses a different signing key, so Play Store/Aurora Store updates won't work. Back up your Brave data with Brave Sync first!

adb uninstall com.brave.browser
adb install brave_signed.apk

Or copy the APK to your device and open it directly (requires "Install unknown apps" enabled).

## Manual Build via GitHub Actions

Go to Actions → Brave AudioFocus APK Patcher → Run workflow

Leave the version field empty for the latest stable, or enter a specific version like v1.91.169.

## Run Locally

python3 patches/audiofocus_patch_precise.py BraveAndroid.apk brave_patched.apk
zipalign -p -f 4 brave_patched.apk brave_aligned.apk
apksigner sign --ks your.jks --out brave_signed.apk brave_aligned.apk

## How It Works

The patcher opens the APK as a ZIP, finds every invoke-virtual AudioManager->requestAudioFocus() instruction in the DEX bytecode, and replaces it with a no-op (const/4 vX, 0x1 = AUDIOFOCUS_REQUEST_GRANTED + nops). All other files in the APK are copied with their original compression settings — no repackaging.

## Caveats

- Play Store/Aurora Store auto-updates won't work (different signing key) — the GitHub Action handles this automatically
- Hardware media keys (headphone play/pause) may no longer control Brave video playback
- Only tested on arm64 devices

## Disclaimer

This project is provided as-is, without any warranty or guarantee of any kind. Use at your own risk.

- This is an unofficial, third-party modification of the Brave Browser APK
- The patched APK is not affiliated with, endorsed by, or supported by Brave Software, Inc.
- Installing a modified APK may void your warranty and violates Brave's terms of service
- The different signing key means you will not receive official Brave updates via Play Store or Aurora Store
- Security updates from Brave will not be automatically applied — you are responsible for keeping up with new releases
- The author(s) of this project accept no responsibility for any damage, data loss, security vulnerabilities, or other issues arising from the use of this software

By downloading and installing this APK you acknowledge that you understand and accept these risks.
