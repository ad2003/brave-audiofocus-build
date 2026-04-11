#!/usr/bin/env python3
"""
audiofocus_patch_precise.py <input.apk> [output.apk]

Patches all AudioManager.requestAudioFocus() calls in the Brave DEX to no-ops.
Works directly inside the APK ZIP — no extract/repack needed.

How it works:
  Parses the DEX string pool and method table to find every method_id
  named 'requestAudioFocus', then scans the bytecode for invoke-virtual
  instructions referencing those method_ids and replaces them with:
    const/4 vX, 0x1  (= AUDIOFOCUS_REQUEST_GRANTED)
    nop nop nop

  Result: Brave thinks it has audio focus and plays audio normally,
  but never actually notifies Android — so Tidal/Spotify keep playing.
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
    """Return all strings from the DEX string pool."""
    size = struct.unpack_from('<I', data, 56)[0]
    off  = struct.unpack_from('<I', data, 60)[0]
    strings = []
    for i in range(size):
        str_off = struct.unpack_from('<I', data, off + i*4)[0]
        length, start = read_uleb128(data, str_off)
        strings.append(data[start:start+length].decode('utf-8', errors='replace'))
    return strings


def parse_type_ids(data):
    """Return all type descriptor string indices."""
    size = struct.unpack_from('<I', data, 64)[0]
    off  = struct.unpack_from('<I', data, 68)[0]
    return [struct.unpack_from('<I', data, off + i*4)[0] for i in range(size)]


def parse_method_ids(data):
    """Return all method_ids as (class_idx, proto_idx, name_idx) tuples."""
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
    Find all method_id indices where the method name is 'requestAudioFocus'.
    Returns a list of indices (usually one per class that has this method).
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
    Find and patch all invoke-virtual calls to requestAudioFocus() in this DEX.
    Returns (patched_bytes, number_of_patches_applied).

    DEX invoke-virtual format (35c): 6 bytes
      0x6e [arg_count] [method_idx_lo] [method_idx_hi] [regs] [regs]
    Followed by move-result vX: 2 bytes
      0x0a [register]

    Replacement (8 bytes total):
      const/4 vX, 0x1  →  0x12 (0x10|reg)   = AUDIOFOCUS_REQUEST_GRANTED
      nop              →  0x00 0x00
      nop              →  0x00 0x00
      nop              →  0x00 0x00  (replaces move-result)
    """
    data = bytearray(dex_data)

    if b'requestAudioFocus' not in data:
        return bytes(data), 0

    method_ids = find_all_audiofocus_method_ids(bytes(data))
    if not method_ids:
        return bytes(data), 0

    total = 0
    for method_idx in method_ids:
        lo = method_idx & 0xFF
        hi = (method_idx >> 8) & 0xFF
        i = 0
        while i < len(data) - 7:
            if (data[i]   == 0x6e and   # invoke-virtual opcode
                data[i+2] == lo    and   # method_idx low byte
                data[i+3] == hi    and   # method_idx high byte
                data[i+6] == 0x0a):      # move-result directly after

                reg = data[i+7] & 0xF
                print(f"    PATCH @ 0x{i:08x}: invoke-virtual → const/4 v{reg}, 0x1 + nops")

                # Replace invoke-virtual (6 bytes) with const/4 vX, 0x1 + nops
                data[i:i+6] = bytes([0x12, (0x1 << 4) | reg, 0x00, 0x00, 0x00, 0x00])
                # Replace move-result (2 bytes) with nop
                data[i+6:i+8] = b'\x00\x00'

                total += 1
                i += 8
            else:
                i += 1

    if total:
        fix_dex_checksum(data)

    return bytes(data), total


def patch_apk(input_apk: Path, output_apk: Path) -> bool:
    """
    Open the APK as a ZIP, patch each DEX file in-place,
    and write the result preserving original compression for all entries.
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
                    print(f"  ✓ {n} patch(es) applied")
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
    print("AudioFocus Patcher — disable all requestAudioFocus() calls")
    print("Tidal/Spotify will keep playing when a video starts in Brave")
    print("=" * 60)

    if not input_apk.exists():
        print(f"Error: file not found: {input_apk}")
        sys.exit(1)

    print(f"\n  Input:  {input_apk} ({input_apk.stat().st_size/1024/1024:.1f} MB)")
    print(f"  Output: {output_apk}")

    if patch_apk(input_apk, output_apk):
        print(f"\n✅ Done: {output_apk}")
    else:
        print("\n❌ No patches applied — AudioFocusDelegate not found in any DEX.")
        sys.exit(1)


if __name__ == "__main__":
    main()
