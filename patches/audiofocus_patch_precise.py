#!/usr/bin/env python3
"""
audiofocus_patch_robust.py

Robuster Patch für Brave / Chromium APKs:
Ersetzt AUDIOFOCUS_GAIN (1) → AUDIOFOCUS_GAIN_TRANSIENT (2)

Kein DEX-Parsing nötig → funktioniert auch bei obfuscated builds.
"""

import sys, struct, zlib, hashlib, zipfile
from pathlib import Path


# --------------------------------------------------
# DEX CHECKSUM FIX
# --------------------------------------------------

def fix_dex_checksum(data: bytearray):
    sha1 = hashlib.sha1(bytes(data[32:])).digest()
    data[12:32] = sha1
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)


# --------------------------------------------------
# CORE PATCH
# --------------------------------------------------

def patch_dex(data: bytes) -> tuple:
    """
    Patch strategy:
    const/4 vX, 0x1  → const/4 vX, 0x2

    Opcode:
    0x12 = const/4
    high nibble = literal
    low nibble  = register
    """
    d = bytearray(data)
    patches = 0

    for i in range(len(d) - 1):
        if d[i] != 0x12:
            continue

        literal = d[i+1] >> 4
        reg     = d[i+1] & 0x0F

        # Only patch literal 1
        if literal != 0x1:
            continue

        # --- HEURISTIC FILTERS ---
        # avoid patching super common patterns blindly

        # Check nearby instructions for AudioManager usage hint
        window = d[max(0, i-20): i+20]

        if b'Audio' not in window and b'audio' not in window:
            continue

        # Patch!
        old = d[i+1]
        new = (0x2 << 4) | reg

        print(f"    PATCH @ 0x{i:08x}: 0x{old:02x} → 0x{new:02x} (v{reg})")

        d[i+1] = new
        patches += 1

    if patches:
        fix_dex_checksum(d)

    return bytes(d), patches


# --------------------------------------------------
# APK HANDLING
# --------------------------------------------------

def patch_apk(input_apk: Path, output_apk: Path):
    total = 0

    with zipfile.ZipFile(input_apk, 'r') as zin, \
         zipfile.ZipFile(output_apk, 'w', allowZip64=True) as zout:

        for item in zin.infolist():
            data = zin.read(item.filename)

            if item.filename.startswith("classes") and item.filename.endswith(".dex"):
                print(f"\n  Checking {item.filename} ({len(data):,} bytes)...")
                data, n = patch_dex(data)

                if n:
                    print(f"  ✓ {n} patch(es)")
                    total += n

            zout.writestr(item, data, compress_type=item.compress_type)

    print(f"\nTotal patches: {total}")
    return total


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 audiofocus_patch_robust.py <input.apk> [output.apk]")
        sys.exit(1)

    input_apk  = Path(sys.argv[1])
    output_apk = Path(sys.argv[2]) if len(sys.argv) > 2 else \
        input_apk.with_stem(input_apk.stem + "_patched")

    print("=" * 60)
    print("AudioFocus Patch (robust mode)")
    print("GAIN (1) → TRANSIENT (2)")
    print("=" * 60)

    if not input_apk.exists():
        print("File not found")
        sys.exit(1)

    print(f"\nInput:  {input_apk}")
    print(f"Output: {output_apk}")

    total = patch_apk(input_apk, output_apk)

    if total == 0:
        print("\n⚠️ No patches applied")
        print("Possible reasons:")
        print("- Brave uses AudioFocusRequest.Builder")
        print("- Code is heavily optimized/inlined")
    else:
        print(f"\n✅ Done ({total} patches)")


if __name__ == "__main__":
    main()
