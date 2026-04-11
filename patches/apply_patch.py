#!/usr/bin/env python3
"""
audiofocus_patch_precise.py <apk_extracted_dir_oder_dex_datei>

Präziser Binary-Patch auf DEX-Datei für Brave AudioFocus Fix.

PROBLEM mit dem alten Script:
  - Suchte const/4 vX, 0x1 im Umkreis eines Strings
  - 0x1 ist extrem häufig (booleans, indices, flags) → falsche Treffer → Crash

DIESE LÖSUNG:
  - Sucht das EXAKTE strukturelle Bytecode-Pattern der if/else-Verzweigung:
      const/4 vX, 0x3   ← AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (richtig)
      goto :skip
      const/4 vX, 0x1   ← AUDIOFOCUS_GAIN (Problem) → wird zu 0x3 gepatcht
  - Nur 1 Byte wird verändert
  - Kein false-positive möglich durch dieses spezifische 3-Instruktionen-Muster
"""

import sys
import struct
import zlib
import hashlib
from pathlib import Path


def fix_dex_checksum(data: bytearray) -> bytearray:
    sha1 = hashlib.sha1(bytes(data[32:])).digest()
    data[12:32] = sha1
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)
    return data


def patch_dex(dex_path: Path, dry_run: bool = False) -> bool:
    data = bytearray(dex_path.read_bytes())

    print(f"\n  DEX: {dex_path.name} ({len(data):,} bytes)")

    if b"AudioFocusDelegate" not in data:
        print("  → AudioFocusDelegate nicht in dieser DEX, überspringe.")
        return False

    print("  ✓ AudioFocusDelegate gefunden")

    # ────────────────────────────────────────────────────────────────
    # Exaktes Pattern:
    #
    #   0x12  [0x3X]   = const/4 vX, 0x3  (GAIN_TRANSIENT_MAY_DUCK)
    #   0x28  [offset] = goto :label       (1 oder 2 bytes für offset)
    #   0x12  [0x1X]   = const/4 vX, 0x1  (AUDIOFOCUS_GAIN) ← PATCHEN
    #
    # Der goto-Offset ist fast immer 0x01 (springe 1 Instruktion weiter),
    # kann aber auch andere kleine Werte haben.
    # Wir matchen: 0x12 [0x3_] 0x28 [beliebig] 0x12 [0x1_]
    # und prüfen zusätzlich: Register X muss in beiden const/4 gleich sein.
    # ────────────────────────────────────────────────────────────────

    found_patches = []

    for i in range(len(data) - 5):
        # Byte 0: const/4 opcode
        if data[i] != 0x12:
            continue
        # Byte 1: (value=3 << 4) | register → muss 0x30..0x3F sein
        if (data[i+1] >> 4) != 0x3:
            continue
        reg = data[i+1] & 0x0F  # Register aus unterem Nibble

        # Byte 2: goto opcode (0x28 = goto/16, oder 0x29 = goto/32 selten)
        if data[i+2] != 0x28:
            continue

        # Byte 3: goto-Offset (signed, kleiner positiver Wert erwartet)
        goto_offset = data[i+3]
        if goto_offset == 0 or goto_offset > 10:
            # Offset zu groß → kein strukturelles Match
            continue

        # Byte 4+5: const/4 mit value=1, gleiches Register
        if data[i+4] != 0x12:
            continue
        expected_gain_byte = (0x1 << 4) | reg
        if data[i+5] != expected_gain_byte:
            continue

        # MATCH! Das ist unser Pattern.
        found_patches.append(i)
        print(f"\n  ✓ PATTERN GEFUNDEN @ offset {i} (0x{i:08x}):")
        print(f"    {i+0:08x}: 0x12 0x{data[i+1]:02x}  = const/4 v{reg}, 0x3  (GAIN_TRANSIENT_MAY_DUCK)")
        print(f"    {i+2:08x}: 0x28 0x{data[i+3]:02x}  = goto +{goto_offset}")
        print(f"    {i+4:08x}: 0x12 0x{data[i+5]:02x}  = const/4 v{reg}, 0x1  (AUDIOFOCUS_GAIN) ← PATCH")

    if not found_patches:
        print("\n  ✗ Exaktes Pattern nicht gefunden!")
        print("  → Mögliche Ursachen:")
        print("    1. Brave nutzt einen anderen goto-Offset als 1-10")
        print("    2. R8/ProGuard hat den Code anders optimiert (Register verschoben)")
        print("    3. Chromium-Version hat anderen Code-Generator verwendet")
        print()
        print("  → Starte Fallback-Suche mit weiterem Pattern...")
        return fallback_patch(data, dex_path, dry_run)

    if len(found_patches) > 1:
        print(f"\n  ⚠ {len(found_patches)} Matches gefunden – nehme nur den ersten")
        print("    (falls mehr als 1 existiert, ist das ungewöhnlich)")

    patch_offset = found_patches[0]

    # Nur das eine Byte ändern: index i+5, Nibble 0x1X → 0x3X
    reg = data[patch_offset+1] & 0x0F
    old_byte = data[patch_offset+5]
    new_byte = (0x3 << 4) | reg  # 0x3X

    print(f"\n  PATCH: offset 0x{patch_offset+5:08x}: 0x{old_byte:02x} → 0x{new_byte:02x}")
    print(f"  (const/4 v{reg}, 0x1 → const/4 v{reg}, 0x3)")

    if dry_run:
        print("\n  [DRY RUN] Keine Änderungen gespeichert.")
        return True

    data[patch_offset+5] = new_byte
    data = fix_dex_checksum(data)

    dex_path.with_suffix('.dex.bak').write_bytes(dex_path.read_bytes() if not dex_path.with_suffix('.dex.bak').exists() else open(dex_path.with_suffix('.dex.bak'), 'rb').read())
    dex_path.write_bytes(bytes(data))
    print(f"  ✓ Gespeichert. Backup: {dex_path.stem}.dex.bak")
    return True


def fallback_patch(data: bytearray, dex_path: Path, dry_run: bool) -> bool:
    """
    Fallback: Suche Pattern mit größerem goto-Offset oder ohne Register-Prüfung.
    Wenn goto-Offset > 10 aber < 50, und Register stimmen überein.
    """
    print("\n  Fallback-Suche (goto-Offset bis 50)...")
    found = []

    for i in range(len(data) - 5):
        if data[i] != 0x12:
            continue
        if (data[i+1] >> 4) != 0x3:
            continue
        reg = data[i+1] & 0x0F
        if data[i+2] != 0x28:
            continue
        goto_offset = data[i+3]
        if goto_offset == 0 or goto_offset > 50:
            continue

        # Nach dem goto: skip goto_offset*2 bytes (DEX instructions sind 2-byte-aligned)
        # und prüfe ob dort ein const/4 v<reg>, 0x1 steht
        target_pos = i + 4 + (goto_offset * 2)
        if target_pos + 1 >= len(data):
            continue
        if data[target_pos] != 0x12:
            continue
        expected = (0x1 << 4) | reg
        if data[target_pos+1] != expected:
            continue

        found.append((i, target_pos, reg, goto_offset))
        print(f"  FALLBACK MATCH @ 0x{i:08x}: const/4 v{reg}, 0x3 → goto+{goto_offset} → const/4 v{reg}, 0x1 @ 0x{target_pos:08x}")

    if not found:
        print("  ✗ Auch Fallback hat nichts gefunden.")
        print()
        print("  → Manual-Analyse nötig. Führe aus:")
        print("    python3 audiofocus_patch_precise.py <dir> --analyze")
        return False

    patch_offset, target_pos, reg, _ = found[0]
    old_byte = data[target_pos+1]
    new_byte = (0x3 << 4) | reg

    print(f"\n  FALLBACK PATCH: 0x{target_pos+1:08x}: 0x{old_byte:02x} → 0x{new_byte:02x}")

    if dry_run:
        print("  [DRY RUN] Keine Änderungen.")
        return True

    data[target_pos+1] = new_byte
    data = fix_dex_checksum(data)
    dex_path.write_bytes(bytes(data))
    print(f"  ✓ Gespeichert.")
    return True


def analyze_mode(dex_path: Path):
    """Zeigt alle const/4 vX, 0x1 im Umfeld von AudioFocusDelegate für manuelle Analyse."""
    data = dex_path.read_bytes()
    if b"AudioFocusDelegate" not in data:
        print("AudioFocusDelegate nicht gefunden.")
        return

    # Finde alle Positionen von "AudioFocusDelegate" im DEX
    positions = []
    idx = 0
    while True:
        pos = data.find(b"AudioFocusDelegate", idx)
        if pos == -1:
            break
        positions.append(pos)
        idx = pos + 1

    print(f"AudioFocusDelegate an {len(positions)} Stellen: {[hex(p) for p in positions]}")

    for str_pos in positions:
        print(f"\n--- Bytecode um 0x{str_pos:08x} ---")
        # Zeige 200 bytes davor und danach als Hex + Disassembly
        start = max(0, str_pos - 200)
        end = min(len(data), str_pos + 200)
        region = data[start:end]
        for j in range(0, len(region)-1, 2):
            opcode = region[j]
            operand = region[j+1]
            abs_off = start + j
            desc = ""
            if opcode == 0x12:
                val = (operand >> 4) & 0xF
                reg = operand & 0xF
                desc = f"const/4 v{reg}, 0x{val}"
            elif opcode == 0x28:
                desc = f"goto {operand}"
            elif opcode == 0x38:
                desc = f"if-eqz v{operand}, ..."
            elif opcode == 0x39:
                desc = f"if-nez v{operand}, ..."
            if desc:
                print(f"  0x{abs_off:08x}: {opcode:02x} {operand:02x}  {desc}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 audiofocus_patch_precise.py <apk_dir>           # Patch anwenden")
        print("  python3 audiofocus_patch_precise.py <apk_dir> --dry-run # Nur simulieren")
        print("  python3 audiofocus_patch_precise.py <dex_datei> --analyze # Analyse")
        sys.exit(1)

    target = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    analyze = "--analyze" in sys.argv

    print("=" * 60)
    print("AudioFocus PRÄZISER DEX Patcher v2")
    print("Patcht AUDIOFOCUS_GAIN → AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK")
    print("=" * 60)

    # DEX-Dateien finden
    if target.suffix == ".dex":
        dex_files = [target]
    else:
        dex_files = sorted(target.glob("*.dex"))
        if not dex_files:
            dex_files = sorted(target.rglob("*.dex"))

    if not dex_files:
        print(f"Keine .dex Dateien in {target} gefunden!")
        sys.exit(1)

    print(f"\nGefundene DEX: {[d.name for d in dex_files]}")

    if analyze:
        for dex in dex_files:
            if b"AudioFocusDelegate" in dex.read_bytes():
                analyze_mode(dex)
        return

    patched = False
    for dex in dex_files:
        if patch_dex(dex, dry_run=dry_run):
            patched = True
            break

    print("\n" + "=" * 60)
    if patched:
        print("✅ PATCH ERFOLGREICH!")
        print()
        print("Was geändert wurde:")
        print("  VORHER:  requestAudioFocus(false) → AUDIOFOCUS_GAIN (1)")
        print("           → Spotify/Tidal STOPPEN komplett")
        print()
        print("  NACHHER: requestAudioFocus(false) → AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (3)")
        print("           → Spotify/Tidal ducken nur (oder laufen weiter)")
        print()
        print("Nächste Schritte:")
        print("  1. APK neu packen: java -jar uber-apk-signer.jar --apks <dir>")
        print("     ODER zipalign + apksigner (siehe ANLEITUNG.md)")
        print("  2. adb uninstall com.brave.browser")
        print("  3. adb install Brave_Patched.apk")
    else:
        print("❌ PATCH FEHLGESCHLAGEN")
        print()
        print("Analysiere die DEX-Datei manuell:")
        for dex in dex_files:
            if b"AudioFocusDelegate" in dex.read_bytes():
                print(f"  python3 audiofocus_patch_precise.py {dex} --analyze")
        sys.exit(1)


if __name__ == "__main__":
    main()
