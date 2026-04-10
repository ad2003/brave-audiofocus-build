#!/usr/bin/env python3
"""
apply_patch.py <decompiled_dir>

Patcht AudioFocusDelegate.smali - nur die AUDIOFOCUS_GAIN Konstante
im else-Zweig von requestAudioFocus(boolean transientFocus).

Aus Chromium Source (AudioFocusDelegate.java):
  mFocusType = transientFocus
      ? AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK  // 3 = 0x3
      : AudioManager.AUDIOFOCUS_GAIN;                    // 1 = 0x1 <- patchen

Smali-Struktur des kompilierten Ternary-Ausdrucks:
  if-eqz p1, :cond_X     # wenn transientFocus == false -> springe zu cond
  const/4 v0, 0x3         # true-Zweig: MAY_DUCK
  goto :goto_X
  :cond_X
  const/4 v0, 0x1         # false-Zweig: GAIN <- das patchen wir
  :goto_X
  iput v0, ...mFocusType  # speichere in mFocusType
"""

import sys
import re
from pathlib import Path


def find_smali_file(base_dir):
    results = list(Path(base_dir).rglob("AudioFocusDelegate.smali"))
    if results:
        print(f"  Gefunden: {results[0]}")
        return results[0]
    print("  FEHLER: AudioFocusDelegate.smali nicht gefunden!")
    return None


def patch_smali(smali_file):
    content = smali_file.read_text(encoding="utf-8")
    original = content

    # Bereits gepatcht?
    if "AudioFocus patched" in content:
        print("  Bereits gepatcht, ueberspringe.")
        return True

    # Extrahiere requestAudioFocus(Z)Z Methode
    method_match = re.search(
        r'(\.method[^\n]*requestAudioFocus\(Z\)Z\n.*?\.end method)',
        content, re.DOTALL
    )
    if not method_match:
        print("  FEHLER: Methode requestAudioFocus(Z)Z nicht gefunden!")
        print("  Vorhandene Methoden:")
        for line in content.splitlines():
            if ".method" in line:
                print(f"    {line.strip()}")
        return False

    method_body = method_match.group(1)
    print(f"  Methode gefunden ({len(method_body.splitlines())} Zeilen):")
    for line in method_body.splitlines():
        print(f"    {line}")

    # Gezieltes Pattern: const/4 vX, 0x1 gefolgt von einem Label und dann iput
    # Dies ist der false-Zweig des Ternary (AUDIOFOCUS_GAIN)
    # Wir suchen explizit nach:
    #   :cond_X
    #   const/4 vX, 0x1
    #   :goto_X
    #   iput vX, ... mFocusType
    pattern = re.compile(
        r'(:[a-z]+_\w+\n\s*)'          # :cond_X label
        r'(const/4\s+(\w+),\s*0x1)\n'  # const/4 vX, 0x1  <- patchen
        r'(\s*:[a-z]+_\w+\n)'          # :goto_X label
        r'(\s*iput\s+\3)',              # iput vX (gleiche Variable)
        re.MULTILINE
    )

    match = pattern.search(method_body)
    if match:
        old_const = match.group(2)
        var = match.group(3)
        new_const = f"const/4 {var}, 0x3"
        new_method = method_body.replace(old_const, new_const, 1)
        print(f"\n  Gezielter Patch: '{old_const}' -> '{new_const}'")
    else:
        # Fallback: suche nach dem letzten const/4 mit 0x1 vor iput mFocusType
        print("  Gezieltes Pattern nicht gefunden, versuche Fallback...")
        pattern2 = re.compile(
            r'(const/4\s+(\w+),\s*0x1)\n'
            r'((?:\s*:[^\n]+\n)*)'
            r'(\s*iput\s+\2[^\n]*mFocusType)',
            re.MULTILINE
        )
        match2 = pattern2.search(method_body)
        if match2:
            old_const = match2.group(1)
            var = match2.group(2)
            new_const = f"const/4 {var}, 0x3"
            new_method = method_body.replace(old_const, new_const, 1)
            print(f"  Fallback-Patch: '{old_const}' -> '{new_const}'")
        else:
            print("  FEHLER: Kein passendes Pattern in der Methode gefunden!")
            print("  Methodeninhalt:")
            for line in method_body.splitlines():
                print(f"    {line}")
            return False

    if new_method == method_body:
        print("  FEHLER: Ersetzung hatte keine Wirkung!")
        return False

    # Ergebnis anzeigen
    print("\n  Methode nach Patch:")
    for line in new_method.splitlines():
        print(f"    {line}")

    # Im Gesamtinhalt ersetzen
    new_content = content.replace(method_body, new_method)

    # Marker einfuegen damit wir wissen dass die Datei gepatcht ist
    new_content = new_content.replace(
        "# AudioFocus patched" , ""  # sicherstellen kein alter Marker
    )

    # Backup und speichern
    smali_file.with_suffix(".smali.orig").write_text(original, encoding="utf-8")
    smali_file.write_text(new_content, encoding="utf-8")
    print(f"\n  Gespeichert!")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply_patch.py <decompiled_dir>")
        sys.exit(1)

    print("=" * 60)
    print("AudioFocus Smali Patcher")
    print("=" * 60)

    smali_file = find_smali_file(sys.argv[1])
    if not smali_file:
        sys.exit(1)

    print("\nPatche...")
    if patch_smali(smali_file):
        print("\n" + "=" * 60)
        print("ERFOLG: 0x1 (AUDIOFOCUS_GAIN) -> 0x3 (MAY_DUCK)")
        print("Nur der false-Zweig wurde geaendert, keine anderen Werte.")
    else:
        print("\nFEHLER: Patch fehlgeschlagen!")
        sys.exit(1)


if __name__ == "__main__":
    main()
