Brave AudioFocus Patcher
Patches the Brave Android APK so that Spotify, Tidal, and other music apps keep playing when a video starts in Brave.
The Problem
Brave requests AUDIOFOCUS_GAIN whenever a video starts playing (including autoplay and inline videos while scrolling). This forces other audio apps to stop completely — not duck, not pause temporarily, just stop.
The Fix
A single byte patch in the DEX disables all AudioManager.requestAudioFocus() calls:
BEFORE: video starts in Brave → AUDIOFOCUS_GAIN → Spotify/Tidal STOP

AFTER:  video starts in Brave → no focus request → Spotify/Tidal keep playing
Brave still plays audio normally. Android does not enforce audio focus — it's a cooperative system. By not requesting focus, Brave never sends an AUDIOFOCUS_LOSS event to other apps.

Note: Simply switching to AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK is not enough. Apps like Tidal and Spotify use setPauseWhenDucked(true) internally and will pause regardless.

Usage
Option A — GitHub Actions (recommended, no setup needed)

Fork this repo
Go to Actions → Brave AudioFocus APK Patcher → Run workflow
Leave the version field empty (= latest stable) or enter a specific version like v1.89.135
Download the APK from the Artifacts section after ~2 minutes

Option B — Run locally
bash# Patch the APK
python3 patches/audiofocus_patch_precise.py BraveAndroid.apk brave_patched.apk

# Align and sign
zipalign -p -f 4 brave_patched.apk brave_aligned.apk
apksigner sign --ks your.jks --out brave_signed.apk brave_aligned.apk
Installation

⚠️ Brave must be fully uninstalled before installing the patched APK.
The patched APK uses a different signing key, so Play Store updates won't work.
Back up your Brave data with Brave Sync first!

bashadb uninstall com.brave.browser
adb install brave_signed.apk
Or copy the APK to your device and open it directly (requires "Install unknown apps" enabled).
How It Works
The patcher opens the APK as a ZIP, finds every invoke-virtual AudioManager->requestAudioFocus() instruction in the DEX bytecode, and replaces it with a no-op (const/4 vX, 0x1 = AUDIOFOCUS_REQUEST_GRANTED + nops). All other files in the APK are copied with their original compression settings — no repackaging.
Caveats

Play Store auto-updates won't work (different signing key) — re-run the Action after each Brave update
Hardware media keys (headphone play/pause) may no longer control Brave video playback
Only tested on arm64 devices
