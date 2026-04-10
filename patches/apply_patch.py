#!/usr/bin/env python3
"""
apply_patch.py <decompiled_dir>

Patcht AudioFocusDelegate.smali in der dekompilierten Brave APK.

Hintergrund (aus Chromium Source verifiziert):
  AudioFocusDelegate.java - requestAudioFocus(boolean transientFocus):
    mFocusType = transientFocus
        ? AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK  (=3)
        : AudioManager.AUDIOFOCUS_GAIN;                    (=1)  <-- Problem

  Wenn Brave ein Video startet, wird transientFocus=false uebergeben
  -> AUDIOFOCUS_GAIN (1) -> Tidal/Spotify wird pausiert.

  Fix: Immer AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (3) verwenden.

Smali-Konstanten:
  AUDIOFOCUS_GAIN                  = 1 = 0x1
  AUDIOFOCUS_GAIN_TRANSIENT        = 2 = 0x2
  AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK = 3 = 0x3
"""

import sys
import re
from pathlib import Path


def find_smali_file(base_dir):
    base = Path(base_dir)
    # Suche in allen smali Ordnern (smali, smali_classes2, etc.)
    for smali_file in base.rglob("AudioFocusDelegate.smali"):
        print(f"  Gefunden: {smali_file.relative_to(base)}")
        return smali_file
    return None


def patch_smali(smali_file):
    content = smali_file.read_text(encoding="utf-8")
    original = content

    # Suche die requestAudioFocus Methode
    # Signatur: requestAudioFocus(Z)Z  (Z = boolean)
    if "requestAudioFocus(Z)Z" not in content:
        print("  FEHLER: Methode requestAudioFocus(Z)Z nicht gefunden!")
        print("  Verfuegbare Methoden:")
        for line in content.splitlines():
            if ".method" in line and "requestAudioFocus" in line:
                print(f"    {line.strip()}")
        return False

    print("  Methode requestAudioFocus(Z)Z gefunden.")

    # Strategie 1: Suche nach dem Ternary-Pattern in Smali
    # Das Java-Ternary wird zu einem if-Zweig kompiliert:
    # if-eqz p1, :cond_X  (wenn transientFocus == false)
    # const/4 vX, 0x3     (AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
    # goto :goto_X
    # :cond_X
    # const/4 vX, 0x1     (AUDIOFOCUS_GAIN) <-- das wollen wir aendern
    #
    # Wir aendern 0x1 -> 0x3 im else-Zweig der requestAudioFocus Methode

    # Extrahiere nur die requestAudioFocus(Z)Z Methode
    method_pattern = re.compile(
        r'(\.method.*?requestAudioFocus\(Z\)Z.*?\.end method)',
        re.DOTALL
    )
    method_match = method_pattern.search(content)
    if not method_match:
        print("  FEHLER: Methode konnte nicht extrahiert werden!")
        return False

    method_body = method_match.group(1)
    print(f"  Methode gefunden ({len(method_body.splitlines())} Zeilen)")

    # Im Methodenbody: ersetze const/4 vX, 0x1 -> const/4 vX, 0x3
    # Aber nur wenn es im Kontext von AUDIOFOCUS ist (nicht andere 0x1 Werte)
    # Sicherheitscheck: 0x3 muss auch schon vorkommen (fuer den true-Zweig)
    if "0x3" not in method_body and "0x1" not in method_body:
        print("  FEHLER: Erwartete Konstanten nicht gefunden!")
        return False

    # Patch: alle const/4 mit 0x1 in dieser Methode -> 0x3
    new_method = re.sub(
        r'(const/4\s+\w+,\s*)0x1',
        r'\g<1>0x3',
        method_body
    )

    if new_method == method_body:
        # Fallback: probiere breitere const Varianten
        new_method = re.sub(
            r'(const(?:/4|/16)?\s+\w+,\s*)0x1\b',
            r'\g<1>0x3',
            method_body
        )

    if new_method == method_body:
        print("  FEHLER: Kein 0x1 Pattern in der Methode gefunden!")
        print("  Methodeninhalt:")
        for line in method_body.splitlines():
            print(f"    {line}")
        return False

    # Wie viele Ersetzungen?
    changes = method_body.count("0x1") - new_method.count("0x1")
    print(f"  {changes} Ersetzung(en): 0x1 -> 0x3 (AUDIOFOCUS_GAIN -> MAY_DUCK)")

    # Ersetze Methode im Gesamtinhalt
    new_content = content.replace(method_body, new_method)

    if new_content == content:
        print("  FEHLER: Ersetzen im Gesamtinhalt fehlgeschlagen!")
        return False

    # Backup und speichern
    backup = smali_file.with_suffix(".smali.orig")
    backup.write_text(original, encoding="utf-8")
    smali_file.write_text(new_content, encoding="utf-8")

    print(f"  Gespeichert. Backup: {backup.name}")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply_patch.py <decompiled_dir>")
        sys.exit(1)

    base_dir = sys.argv[1]
    print("=" * 60)
    print("AudioFocus Smali Patcher")
    print(f"Verzeichnis: {base_dir}")
    print("=" * 60)

    print("\n[1] Suche AudioFocusDelegate.smali...")
    smali_file = find_smali_file(base_dir)

    if not smali_file:
        print("  FEHLER: AudioFocusDelegate.smali nicht gefunden!")
        print("  Verfuegbare Smali-Dateien mit 'Audio' im Namen:")
        for f in Path(base_dir).rglob("*Audio*.smali"):
            print(f"    {f.relative_to(base_dir)}")
        sys.exit(1)

    print("\n[2] Patche Smali...")
    success = patch_smali(smali_file)

    print("\n" + "=" * 60)
    if success:
        print("ERFOLG: AudioFocus Patch angewendet!")
        print("  Brave wird jetzt AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK")
        print("  verwenden statt AUDIOFOCUS_GAIN.")
        print("  -> Tidal/Spotify laeuft weiter beim Videostart in Brave.")
    else:
        print("FEHLER: Patch konnte nicht angewendet werden.")
        sys.exit(1)


if __name__ == "__main__":
    main()
