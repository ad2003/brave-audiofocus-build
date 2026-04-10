#!/usr/bin/env python3
"""
apply_patch.py
Sucht die AudioFocus-relevanten Dateien in Chromium/Brave Source
und patcht AUDIOFOCUS_GAIN -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK

Zieldateien (eine oder mehrere davon existieren je nach Chromium-Version):
  - content/public/android/java/src/org/chromium/content/browser/MediaSessionImpl.java
  - media/base/android/java/src/org/chromium/media/AudioManagerAndroid.java
  - components/media_router/... (falls vorhanden)
"""

import os
import re
import sys
from pathlib import Path

BASE = Path.home() / "brave-browser" / "src"

# Kandidaten-Dateien die AudioFocus-Aufrufe enthalten koennen
CANDIDATE_PATHS = [
    "content/public/android/java/src/org/chromium/content/browser/MediaSessionImpl.java",
    "media/base/android/java/src/org/chromium/media/AudioManagerAndroid.java",
    "content/public/android/java/src/org/chromium/content/browser/AudioFocusDelegate.java",
    "media/base/android/java/src/org/chromium/media/MediaCodecBridge.java",
    "third_party/blink/renderer/modules/mediasession/media_session.cc",
    "content/browser/media/session/audio_focus_manager.cc",
    "content/browser/media/session/media_session_impl.cc",
]

# Brute-force Suche in diesen Verzeichnissen falls Kandidaten nicht gefunden
SEARCH_DIRS = [
    "content/public/android",
    "media/base/android",
    "content/browser/media",
]

SEARCH_KEYWORDS = [
    "AUDIOFOCUS_GAIN",
    "requestAudioFocus",
    "AudioFocusRequest",
]

PATCH_REPLACEMENTS = [
    # Java: AudioManager.AUDIOFOCUS_GAIN -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
    (
        r'AudioManager\.AUDIOFOCUS_GAIN(?!_TRANSIENT)',
        'AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK',
        "AudioManager.AUDIOFOCUS_GAIN"
    ),
    # Java: AUDIOFOCUS_GAIN als Konstante (ohne AudioManager. prefix)
    (
        r'(?<!\w)AUDIOFOCUS_GAIN(?!_TRANSIENT)(?!\w)',
        'AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK',
        "AUDIOFOCUS_GAIN (bare)"
    ),
    # C++: AudioManager::AUDIOFOCUS_GAIN
    (
        r'AUDIOFOCUS_GAIN(?!_TRANSIENT)(?!\w)',
        'AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK',
        "AUDIOFOCUS_GAIN (C++)"
    ),
]


def find_files_with_keyword(directory, keywords):
    """Durchsucht ein Verzeichnis nach Dateien die Keywords enthalten."""
    found = []
    search_path = BASE / directory
    if not search_path.exists():
        return found

    for ext in [".java", ".cc", ".cpp", ".h"]:
        for f in search_path.rglob(f"*{ext}"):
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                if any(kw in content for kw in keywords):
                    found.append(f)
            except Exception:
                pass
    return found


def patch_file(filepath):
    """Patcht eine einzelne Datei. Gibt Anzahl der Aenderungen zurueck."""
    try:
        original = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"  FEHLER beim Lesen: {e}")
        return 0

    content = original
    total_changes = 0

    for pattern, replacement, description in PATCH_REPLACEMENTS:
        new_content, count = re.subn(pattern, replacement, content)
        if count > 0:
            content = new_content
            total_changes += count
            print(f"  Patch '{description}': {count} Ersetzung(en)")

    if total_changes > 0:
        # Backup
        backup = filepath.with_suffix(filepath.suffix + ".orig")
        backup.write_text(original, encoding="utf-8")
        filepath.write_text(content, encoding="utf-8")
        print(f"  Gespeichert. Backup: {backup.name}")

    return total_changes


def main():
    print("=" * 60)
    print("AudioFocus Patch")
    print(f"Brave Source: {BASE}")
    print("=" * 60)

    if not BASE.exists():
        print(f"FEHLER: Source-Verzeichnis nicht gefunden: {BASE}")
        sys.exit(1)

    all_files = set()

    # 1. Bekannte Kandidaten pruefen
    print("\n[1] Pruefe bekannte Kandidaten...")
    for rel_path in CANDIDATE_PATHS:
        full_path = BASE / rel_path
        if full_path.exists():
            content = full_path.read_text(encoding="utf-8", errors="replace")
            if any(kw in content for kw in SEARCH_KEYWORDS):
                all_files.add(full_path)
                print(f"  Gefunden: {rel_path}")

    # 2. Brute-force Suche in relevanten Verzeichnissen
    print("\n[2] Suche in relevanten Verzeichnissen...")
    for search_dir in SEARCH_DIRS:
        files = find_files_with_keyword(search_dir, SEARCH_KEYWORDS)
        for f in files:
            if f not in all_files:
                all_files.add(f)
                print(f"  Gefunden: {f.relative_to(BASE)}")

    if not all_files:
        print("\nKeine relevanten Dateien gefunden!")
        print("Moegliche Ursachen:")
        print("  - Source wurde noch nicht vollstaendig synchronisiert")
        print("  - Pfade haben sich in dieser Chromium-Version geaendert")
        sys.exit(1)

    # 3. Patchen
    print(f"\n[3] Patche {len(all_files)} Datei(en)...")
    total_patches = 0

    for filepath in sorted(all_files):
        print(f"\n  Datei: {filepath.relative_to(BASE)}")
        changes = patch_file(filepath)
        total_patches += changes

    # 4. Ergebnis
    print("\n" + "=" * 60)
    if total_patches > 0:
        print(f"ERFOLG: {total_patches} Patch(es) angewendet in {len(all_files)} Datei(en)")
        print("AUDIOFOCUS_GAIN -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK")
    else:
        print("WARNUNG: Keine Patches angewendet.")
        print("Entweder sind die Dateien bereits gepatcht oder")
        print("der AudioFocus-Code befindet sich an anderer Stelle.")
        sys.exit(1)


if __name__ == "__main__":
    main()
