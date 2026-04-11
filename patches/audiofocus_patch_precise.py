#!/usr/bin/env python3
"""
audiofocus_patch_precise.py <input.apk> [output.apk]

Patcht ALLE Aufrufe von AudioManager.requestAudioFocus() im DEX zu No-Ops.
-> Tidal/Spotify bekommen kein AUDIOFOCUS_LOSS -> laufen weiter.
"""

import sys, struct, zlib, hashlib, zipfile
from pathlib import Path


def fix_dex_checksum(data: bytearray):
    sha1 = hashlib.sha1(bytes(data[32:])).digest()
    data[12:32] = sha1
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)


def read_uleb128(data, offset):
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
            struct.unpack_from('<H', data, o)[0],    # class_idx
            struct.unpack_from('<H', data, o+2)[0],  # proto_idx
            struct.unpack_from('<H', data, o+4)[0],  # name_idx
        ))
    return methods


def find_all_audiofocus_method_ids(data: bytes) -> list:
    """
    Findet ALLE method_ids die 'requestAudioFocus' heissen
    und zu Android AudioManager oder anderen Audio-Klassen gehören.
    Gibt Liste von method_id Indizes zurück.
    """
    strings  = parse_strings(data)
    type_ids = parse_type_ids(data)
    methods  = parse_method_ids(data)

    # Alle String-Indices die 'requestAudioFocus' heissen
    raf_name_indices = {i for i, s in enumerate(strings) if s == 'requestAudioFocus'}
    if not raf_name_indices:
        print("    'requestAudioFocus' nicht im String Pool!")
        return []

    print(f"    'requestAudioFocus' Strings: indices {raf_name_indices}")

    # Alle method_ids mit diesem Namen finden (egal welche Klasse)
    result = []
    for i, (class_idx, proto_idx, name_idx) in enumerate(methods):
        if name_idx in raf_name_indices:
            class_str = strings[type_ids[class_idx]] if class_idx < len(type_ids) else "?"
            print(f"    method_id {i}: {class_str}->requestAudioFocus")
            result.append(i)

    return result


def patch_dex(dex_data: bytes) -> tuple:
    data = bytearray(dex_data)

    if b'AudioFocusDelegate' not in data and b'requestAudioFocus' not in data:
        return bytes(data), 0

    if b'AudioFocusDelegate' in data:
        print("    ✓ AudioFocusDelegate gefunden")

    method_ids = find_all_audiofocus_method_ids(bytes(data))
    if not method_ids:
        return bytes(data), 0

    total_patches = 0

    for method_idx in method_ids:
        method_idx_lo = method_idx & 0xFF
        method_idx_hi = (method_idx >> 8) & 0xFF

        # Finde ALLE invoke-virtual Calls zu diesem method_idx
        i = 0
        while i < len(data) - 7:
            if data[i] == 0x6e and \
               data[i+2] == method_idx_lo and \
               data[i+3] == method_idx_hi and \
               data[i+6] == 0x0a:  # move-result direkt danach

                reg = data[i+7] & 0xF
                const_byte = (0x1 << 4) | reg

                print(f"    PATCH @ 0x{i:08x}: invoke-virtual(method {method_idx}) → const/4 v{reg}, 0x1 + nops")

                # invoke-virtual (6 bytes) → const/4 vX, 0x1 + nop + nop
                data[i+0] = 0x12
                data[i+1] = const_byte
                data[i+2] = 0x00
                data[i+3] = 0x00
                data[i+4] = 0x00
                data[i+5] = 0x00
                # move-result → nop
                data[i+6] = 0x00
                data[i+7] = 0x00

                total_patches += 1
                i += 8
            else:
                i += 1

    if total_patches == 0:
        return bytes(data), 0

    fix_dex_checksum(data)
    return bytes(data), total_patches


def patch_apk(input_apk: Path, output_apk: Path) -> bool:
    print(f"  Input:  {input_apk} ({input_apk.stat().st_size/1024/1024:.1f} MB)")

    total = 0
    with zipfile.ZipFile(input_apk, 'r') as zin, \
         zipfile.ZipFile(output_apk, 'w', allowZip64=True) as zout:

        for item in zin.infolist():
            data = zin.read(item.filename)

            if item.filename.endswith('.dex'):
                print(f"\n  Prüfe {item.filename} ({len(data):,} bytes)...")
                new_data, n = patch_dex(data)
                if n > 0:
                    data = new_data
                    total += n
                    print(f"  ✓ {n} Patch(es) in {item.filename}")

            zout.writestr(item, data, compress_type=item.compress_type)

    print(f"\n  Gesamt: {total} Patch(es)")
    return total > 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 audiofocus_patch_precise.py <input.apk> [output.apk]")
        sys.exit(1)

    input_apk  = Path(sys.argv[1])
    output_apk = Path(sys.argv[2]) if len(sys.argv) > 2 else \
                 input_apk.with_stem(input_apk.stem + "_patched")

    print("=" * 60)
    print("AudioFocus Patcher - ALLE requestAudioFocus Calls deaktivieren")
    print("=" * 60)

    if patch_apk(input_apk, output_apk):
        print("\n✅ FERTIG:", output_apk)
    else:
        print("\n❌ Keine Patches angewendet!")
        sys.exit(1)


if __name__ == "__main__":
    main()
