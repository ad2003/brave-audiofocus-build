#!/usr/bin/env python3
"""
apply_patch.py <decompiled_dir>

Patcht AudioFocusDelegate.smali in der dekompilierten Brave APK.

Aus Chromium Source verifiziert (AudioFocusDelegate.java):
  private boolean requestAudioFocus(boolean transientFocus) {
      mFocusType =
          transientFocus
          ? AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK  // = 3
          : AudioManager.AUDIOFOCUS_GAIN;                    // = 1 <-- Problem
      return requestAudioFocusInternal();
  }

Smali-Konstanten:
  AUDIOFOCUS_GAIN                    = 1 = 0x1
  AUDIOFOCUS_GAIN_TRANSIENT          = 2 = 0x2
  AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK = 3 = 0x3
"""

import sys
import re
from pathlib import Path


def find_smali_file(base_dir):
    """Sucht AudioFocusDelegate.smali in allen smali Ordnern."""
    base = Path(base_dir)
    results = list(base.rglob("AudioFocusDelegate.smali"))
    if results:
        print(f"  Gefunden: {results[0].relative_to(base)}")
        return results[0]

    # Fallback: zeige alle Audio* Smali Dateien
    print("  AudioFocusDelegate.smali nicht gefunden!")
    print("  Verfuegbare Audio* Smali-Dateien:")
    for f in base.rglob("*Audio*.smali"):
        print(f"    {f.relative_to(base)}")
    return None


def patch_smali(smali_file):
    """Patcht die requestAudioFocus Methode in der Smali-Datei."""
    content = smali_file.read_text(encoding="utf-8")
    original = content

    # Pruefe ob Methode vorhanden
    if "requestAudioFocus" not in content:
        print("  FEHLER: requestAudioFocus nicht in der Datei gefunden!")
        return False

    # Bereits gepatcht?
    if "# AudioFocus patched" in content:
        print("  Datei ist bereits gepatcht!")
        return True

    # Extrahiere die requestAudioFocus(Z)Z Methode
    # Z = boolean Parameter, Z = boolean Rueckgabe
    method_match = re.search(
        r'(\.method[^\n]*requestAudioFocus\(Z\)Z\n.*?\.end method)',
        content,
        re.DOTALL
    )

    if not method_match:
        # Fallback: suche ohne Signatur
        method_match = re.search(
            r'(\.method[^\n]*requestAudioFocus[^\n]*\n.*?\.end method)',
            content,
            re.DOTALL
        )

    if not method_match:
        print("  FEHLER: requestAudioFocus Methode nicht gefunden!")
        print("  Methoden in der Datei:")
        for line in content.splitlines():
            if ".method" in line:
                print(f"    {line.strip()}")
        return False

    method_body = method_match.group(1)
    print(f"  Methode gefunden ({len(method_body.splitlines())} Zeilen)")
    print("  Methoden-Inhalt:")
    for line in method_body.splitlines():
        print(f"    {line}")

    # Strategie 1: ersetze const/4 vX, 0x1 -> 0x3 in der Methode
    new_method = re.sub(
        r'(const/4\s+\w+,\s*)0x1\b',
        r'\g<1>0x3    # AudioFocus patched: GAIN -> GAIN_TRANSIENT_MAY_DUCK',
        method_body
    )

    if new_method == method_body:
        # Strategie 2: const vX, 0x1
        new_method = re.sub(
            r'(const\s+\w+,\s*)0x1\b',
            r'\g<1>0x3    # AudioFocus patched: GAIN -> GAIN_TRANSIENT_MAY_DUCK',
            method_body
        )

    if new_method == method_body:
        # Strategie 3: 0x1 als letzter Wert vor iput
        new_method = re.sub(
            r'((?:const(?:/4|/16)?)\s+(\w+),\s*0x1\b)(\s*\n\s*iput\s+\2)',
            r'const/4 \2, 0x3    # AudioFocus patched\3',
            method_body
        )

    if new_method == method_body:
        print("  WARNUNG: Standard-Strategien fehlgeschlagen.")
        print("  Versuche aggressiveren Ansatz: alle 0x1 in Methode ersetzen...")
        # Letzter Ausweg: alle 0x1 Werte in der Methode ersetzen
        new_method = method_body.replace(", 0x1", ", 0x3  # patched")
        if new_method == method_body:
            print("  FEHLER: Kein 0x1 in der Methode gefunden!")
            return False

    # Zaehle Aenderungen
    orig_count = method_body.count("0x1")
    new_count = new_method.count("0x1")
    changes = orig_count - new_count
    print(f"  {changes} Ersetzung(en) vorgenommen")

    # Ersetze Methode im Gesamtinhalt
    new_content = content.replace(method_body, new_method)

    if new_content == content:
        print("  FEHLER: Konnte Methode im Gesamtinhalt nicht ersetzen!")
        return False

    # Backup und Speichern
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

    if not Path(base_dir).exists():
        print(f"FEHLER: Verzeichnis nicht gefunden: {base_dir}")
        sys.exit(1)

    print("\n[1] Suche AudioFocusDelegate.smali...")
    smali_file = find_smali_file(base_dir)

    if not smali_file:
        sys.exit(1)

    print("\n[2] Patche Smali-Datei...")
    success = patch_smali(smali_file)

    print("\n" + "=" * 60)
    if success:
        print("ERFOLG!")
        print("  AUDIOFOCUS_GAIN -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK")
        print("  Tidal/Spotify laeuft weiter wenn Videos in Brave abgespielt werden.")
    else:
        print("FEHLER: Patch nicht angewendet!")
        sys.exit(1)


if __name__ == "__main__":
    main()
