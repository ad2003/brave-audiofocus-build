#!/usr/bin/env python3
"""
audiofocus_patch_precise.py <input.apk> [output.apk]

Patches all AudioManager.requestAudioFocus() calls in Brave:
Changes AUDIOFOCUS_GAIN (1) → AUDIOFOCUS_GAIN_TRANSIENT (2)

Why GAIN_TRANSIENT works:
- Android 8+ performs automatic ducking when GAIN_TRANSIENT is requested
- Tidal/Spotify never receive an onAudioFocusChange callback
- They keep playing at reduced volume (~20%) automatically
- Volume is restored when Brave releases focus (video ends/pauses)

This mirrors how Signal handles audio for voice messages.
"""

import sys, struct, zlib, hashlib, zipfile
from pathlib import Path


def fix_dex_checksum(data: bytearray):
    """Update SHA1 signature and Adler32 checksum in the DEX header."""
    sha1 = hashlib.sha1(bytes(data[32:])).digest()
    data[12:32] = sha1
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)


def read_uleb128(data, offset):
    """Read a ULEB128-encoded integer, return (value, new_offset)."""
    result, shift = 0, 0
    while True:
        b = data[offset]; offset += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, offset


def parse_strings(data):
    size = struct.unpack_from('<I', data, 56)[0]
    off  = struct.unpack_from('<I', data, 60)[0]
    strings = []
    for i in range(size):
        str_off = struct.unpack_from('<I', data, off + i*4)[0]
        length, start = read_uleb128(data, str_off)
        strings.append(data[start:start+length].decode('utf-8', errors='replace'))
    return strings


def parse_type_ids(data):
    size = struct.unpack_from('<I', data, 64)[0]
    off  = struct.unpack_from('<I', data, 68)[0]
    return [struct.unpack_from('<I', data, off + i*4)[0] for i in range(size)]


def parse_method_ids(data):
    size = struct.unpack_from('<I', data, 88)[0]
    off  = struct.unpack_from('<I', data, 92)[0]
    methods = []
    for i in range(size):
        o = off + i*8
        methods.append((
            struct.unpack_from('<H', data, o)[0],
            struct.unpack_from('<H', data, o+2)[0],
            struct.unpack_from('<H', data, o+4)[0],
        ))
    return methods


def find_all_audiofocus_method_ids(data: bytes) -> list:
    """
    Find all method_ids named 'requestAudioFocus'.
    Returns list of method_id indices.
    """
    strings  = parse_strings(data)
    type_ids = parse_type_ids(data)
    methods  = parse_method_ids(data)

    raf_indices = {i for i, s in enumerate(strings) if s == 'requestAudioFocus'}
    if not raf_indices:
        return []

    result = []
    for i, (class_idx, proto_idx, name_idx) in enumerate(methods):
        if name_idx in raf_indices:
            class_str = strings[type_ids[class_idx]] if class_idx < len(type_ids) else "?"
            print(f"    method_id {i}: {class_str}->requestAudioFocus")
            result.append(i)
    return result


def patch_dex(dex_data: bytes) -> tuple:
    """
    Find the AudioFocusDelegate.requestAudioFocus(boolean) method and patch it:

    The method contains this branch:
      if-eqz p1, :full_gain
      const/4 v0, 0x3   ← AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (when transientFocus=true)
      goto :set
      :full_gain
      const/4 v0, 0x1   ← AUDIOFOCUS_GAIN (when transientFocus=false) ← PATCH THIS

    We change 0x1 (AUDIOFOCUS_GAIN) → 0x2 (AUDIOFOCUS_GAIN_TRANSIENT)
    so Android performs automatic ducking instead of stopping other apps.

    Pattern to match:
      0x12 0x3X  = const/4 vX, 0x3  (MAY_DUCK branch — already correct)
      0x28 0xXX  = goto
      0x12 0x1X  = const/4 vX, 0x1  ← change to 0x2X (GAIN_TRANSIENT)
    """
    data = bytearray(dex_data)

    if b'AudioFocusDelegate' not in data:
        return bytes(data), 0

    print("    ✓ AudioFocusDelegate found")

    total = 0

    # Primary pattern: const/4 vX, 0x3 → goto → const/4 vX, 0x1
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

        # Found AUDIOFOCUS_GAIN (0x1) — patch to AUDIOFOCUS_GAIN_TRANSIENT (0x2)
        old_byte = data[i+5]
        new_byte = (0x2 << 4) | reg  # 0x2X
        print(f"    PATCH @ 0x{i+5:08x}: 0x{old_byte:02x} → 0x{new_byte:02x}")
        print(f"    (const/4 v{reg}, 0x1 [GAIN] → const/4 v{reg}, 0x2 [GAIN_TRANSIENT])")
        print(f"    Android will now auto-duck Tidal/Spotify instead of stopping them")
        data[i+5] = new_byte
        total += 1

    if total == 0:
        # Fallback: larger goto offset range
        print("    Primary pattern not found, trying fallback...")
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
            data[target+1] = (0x2 << 4) | reg
            print(f"    FALLBACK PATCH @ 0x{target+1:08x}: 0x{old:02x} → 0x{data[target+1]:02x}")
            total += 1

    if total:
        fix_dex_checksum(data)

    return bytes(data), total


def patch_apk(input_apk: Path, output_apk: Path) -> bool:
    """
    Open the APK as a ZIP, patch each DEX file in-place,
    preserving original compression for all entries.
    """
    total = 0

    with zipfile.ZipFile(input_apk, 'r') as zin, \
         zipfile.ZipFile(output_apk, 'w', allowZip64=True) as zout:

        for item in zin.infolist():
            data = zin.read(item.filename)

            if item.filename.endswith('.dex'):
                print(f"\n  Checking {item.filename} ({len(data):,} bytes)...")
                data, n = patch_dex(data)
                if n:
                    print(f"  ✓ {n} patch(es) applied in {item.filename}")
                    total += n

            # Preserve original compression (STORED or DEFLATED)
            zout.writestr(item, data, compress_type=item.compress_type)

    print(f"\n  Total patches: {total}")
    return total > 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 audiofocus_patch_precise.py <input.apk> [output.apk]")
        sys.exit(1)

    input_apk  = Path(sys.argv[1])
    output_apk = Path(sys.argv[2]) if len(sys.argv) > 2 else \
                 input_apk.with_stem(input_apk.stem + "_patched")

    print("=" * 60)
    print("AudioFocus Patcher — GAIN → GAIN_TRANSIENT (auto-duck)")
    print("Tidal/Spotify will duck (play quieter) instead of stopping")
    print("=" * 60)

    if not input_apk.exists():
        print(f"Error: file not found: {input_apk}")
        sys.exit(1)

    print(f"\n  Input:  {input_apk} ({input_apk.stat().st_size/1024/1024:.1f} MB)")
    print(f"  Output: {output_apk}")

    if patch_apk(input_apk, output_apk):
        print(f"\n✅ Done: {output_apk}")
    else:
        print("\n❌ No patches applied — AudioFocusDelegate not found!")
        sys.exit(1)


if __name__ == "__main__":
    main()
