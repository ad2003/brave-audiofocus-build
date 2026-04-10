#!/usr/bin/env python3
"""
apply_patch.py <apk_extracted_dir>

Neuer Ansatz: Patcht DEX direkt mit baksmali/smali.
- Kein apktool recompile
- .so Dateien werden nicht angeruehrt
- Nur die eine DEX-Datei die AudioFocusDelegate enthaelt wird ersetzt
"""

import sys
import re
import os
import subprocess
from pathlib import Path


def run(cmd, check=True):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if check and result.returncode != 0:
        print(f"  FEHLER: Exit code {result.returncode}")
        sys.exit(1)
    return result


def find_dex_with_class(apk_dir):
    """Findet welche DEX-Datei AudioFocusDelegate enthaelt."""
    apk = Path(apk_dir)
    dex_files = sorted(apk.glob("*.dex"))
    print(f"  DEX-Dateien: {[d.name for d in dex_files]}")

    for dex in dex_files:
        # Suche nach dem Klassennamen im Binaerinhalt
        content = dex.read_bytes()
        if b"AudioFocusDelegate" in content:
            print(f"  AudioFocusDelegate gefunden in: {dex.name}")
            return dex

    print("  FEHLER: AudioFocusDelegate in keiner DEX-Datei gefunden!")
    return None


def patch_smali(smali_file):
    """Patcht die requestAudioFocus Methode."""
    content = smali_file.read_text(encoding="utf-8")
    original = content

    print(f"\n  Patche: {smali_file}")

    # Extrahiere requestAudioFocus(Z)Z Methode
    method_match = re.search(
        r'(\.method[^\n]*requestAudioFocus\(Z\)Z\n.*?\.end method)',
        content, re.DOTALL
    )
    if not method_match:
        print("  FEHLER: Methode nicht gefunden!")
        return False

    method_body = method_match.group(1)
    print("\n  Methode:")
    for line in method_body.splitlines():
        print(f"    {line}")

    # Ersetze ALLE const/4 vX, 0x1 in der Methode -> 0x3
    # (sicher weil 0x1 hier nur AUDIOFOCUS_GAIN sein kann)
    new_method = re.sub(
        r'(const/4\s+\w+,\s*)0x1\b',
        r'\g<1>0x3',
        method_body
    )

    if new_method == method_body:
        print("  Kein 0x1 gefunden - versuche andere Konstanten-Formate...")
        new_method = re.sub(
            r'(const\s+\w+,\s*)0x1\b',
            r'\g<1>0x3',
            method_body
        )

    if new_method == method_body:
        print("  FEHLER: Kein passendes Pattern!")
        return False

    print("\n  Nach Patch:")
    for line in new_method.splitlines():
        print(f"    {line}")

    new_content = content.replace(method_body, new_method)
    smali_file.write_text(new_content, encoding="utf-8")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply_patch.py <apk_extracted_dir>")
        sys.exit(1)

    apk_dir = Path(sys.argv[1])
    work_dir = Path("/tmp/audiofocus_patch")
    work_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("AudioFocus DEX Patcher")
    print("=" * 60)

    # 1. Finde DEX mit AudioFocusDelegate
    print("\n[1] Suche DEX-Datei...")
    dex_file = find_dex_with_class(apk_dir)
    if not dex_file:
        sys.exit(1)

    # 2. Dekompiliere DEX mit baksmali
    print(f"\n[2] Dekompiliere {dex_file.name} mit baksmali...")
    smali_out = work_dir / "smali_out"
    smali_out.mkdir(exist_ok=True)
    run(["java", "-jar", "baksmali.jar", "d",
         str(dex_file), "-o", str(smali_out)])

    # 3. Finde und patche AudioFocusDelegate.smali
    print("\n[3] Suche AudioFocusDelegate.smali...")
    results = list(smali_out.rglob("AudioFocusDelegate.smali"))
    if not results:
        print("  FEHLER: AudioFocusDelegate.smali nicht gefunden!")
        sys.exit(1)

    smali_file = results[0]
    print(f"  Gefunden: {smali_file.relative_to(smali_out)}")

    if not patch_smali(smali_file):
        sys.exit(1)

    # 4. Rekompiliere DEX mit smali
    print(f"\n[4] Rekompiliere zu DEX...")
    new_dex = work_dir / dex_file.name
    run(["java", "-jar", "smali.jar", "a",
         str(smali_out), "-o", str(new_dex)])

    # 5. Ersetze originale DEX in APK-Verzeichnis
    print(f"\n[5] Ersetze {dex_file.name}...")
    import shutil
    shutil.copy2(new_dex, dex_file)
    print(f"  {dex_file.name} ersetzt!")

    print("\n" + "=" * 60)
    print("ERFOLG: AudioFocus Patch angewendet!")
    print("AUDIOFOCUS_GAIN (0x1) -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (0x3)")


if __name__ == "__main__":
    main()
