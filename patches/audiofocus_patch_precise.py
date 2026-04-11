#!/usr/bin/env python3
"""
audiofocus_patch_precise.py <apk_file> [output_apk]

Patcht die DEX direkt INNERHALB des APK-ZIPs.
Kein Entpacken/Neupacken noetig -> keine Kompression/Alignment-Probleme.
"""

import sys
import struct
import zlib
import hashlib
import zipfile
from pathlib import Path


def fix_dex_checksum(data: bytearray) -> bytearray:
    sha1 = hashlib.sha1(bytes(data[32:])).digest()
    data[12:32] = sha1
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)
    return data


def find_and_patch(dex_data: bytes) -> tuple:
    data = bytearray(dex_data)

    if b"AudioFocusDelegate" not in data:
        return bytes(data), False

    print("    AudioFocusDelegate gefunden")

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
        if data[i+4] != 0x12:
            continue
        if data[i+5] != ((0x1 << 4) | reg):
            continue
        found.append((i, reg))

    if not found:
        # Fallback mit groesserem Offset
        for i in range(len(data) - 8):
            if data[i] != 0x12 or (data[i+1] >> 4) != 0x3:
                continue
            reg = data[i+1] & 0x0F
            if data[i+2] != 0x28:
                continue
            offset = data[i+3]
            if offset == 0 or offset > 200:
                continue
            target = i + 4 + (offset * 2)
            if target + 1 >= len(data):
                continue
            if data[target] != 0x12 or data[target+1] != ((0x1 << 4) | reg):
                continue
            old = data[target+1]
            data[target+1] = (0x3 << 4) | reg
            print(f"    FALLBACK PATCH @ 0x{target+1:08x}: 0x{old:02x} -> 0x{data[target+1]:02x}")
            return bytes(fix_dex_checksum(data)), True
        return bytes(data), False

    i, reg = found[0]
    old = data[i+5]
    data[i+5] = (0x3 << 4) | reg
    print(f"    PATCH @ 0x{i+5:08x}: 0x{old:02x} -> 0x{data[i+5]:02x}")
    return bytes(fix_dex_checksum(data)), True


def patch_apk(input_apk: Path, output_apk: Path) -> bool:
    print(f"  Input:  {input_apk} ({input_apk.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  Output: {output_apk}")

    patched = False

    with zipfile.ZipFile(input_apk, 'r') as zin, \
         zipfile.ZipFile(output_apk, 'w', allowZip64=True) as zout:

        for item in zin.infolist():
            data = zin.read(item.filename)

            if item.filename.endswith('.dex') and not patched:
                print(f"\n  Pruefe {item.filename} ({len(data):,} bytes)...")
                new_data, success = find_and_patch(data)
                if success:
                    patched = True
                    data = new_data
                    print(f"  Gepatcht!")

            # EXAKT gleiche Kompression wie Original
            zout.writestr(item, data, compress_type=item.compress_type)

    if not patched:
        output_apk.unlink(missing_ok=True)
        return False

    print(f"\n  Output: {output_apk.stat().st_size / 1024 / 1024:.1f} MB")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 audiofocus_patch_precise.py <input.apk> [output.apk]")
        sys.exit(1)

    input_apk = Path(sys.argv[1])
    output_apk = Path(sys.argv[2]) if len(sys.argv) > 2 else \
                 input_apk.with_stem(input_apk.stem + "_patched")

    print("=" * 60)
    print("AudioFocus DEX Patcher (In-Place ZIP)")
    print("AUDIOFOCUS_GAIN -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK")
    print("=" * 60)

    if patch_apk(input_apk, output_apk):
        print("\nFERTIG:", output_apk)
    else:
        print("\nFEHLER: AudioFocusDelegate nicht gefunden!")
        sys.exit(1)


if __name__ == "__main__":
    main()
