#!/usr/bin/env python3
"""
audiofocus_patch_precise.py <input.apk> [output.apk]

Patcht Brave so dass KEIN AudioFocus mehr requestet wird.
-> Tidal/Spotify bekommen KEIN AUDIOFOCUS_LOSS Event -> laufen weiter.

Strategie:
  requestAudioFocusInternal() ruft am.requestAudioFocus(mFocusRequest) auf.
  Wir finden diesen invoke-virtual Call im DEX und ersetzen ihn + move-result
  mit const/4 v0, 0x1 (= AUDIOFOCUS_REQUEST_GRANTED) + nops.
  Brave denkt es hat Focus, spielt Audio ab, aber Tidal wird NIE unterbrochen.

DEX Parsing:
  Wir parsen Header -> string_ids -> method_ids um den exakten
  invoke-virtual zu AudioManager.requestAudioFocus zu finden.
"""

import sys
import struct
import zlib
import hashlib
import zipfile
from pathlib import Path


# ── DEX Parser ────────────────────────────────────────────────

def read_uleb128(data: bytes, offset: int) -> tuple:
    """Liest ULEB128 Integer, gibt (wert, neuer_offset) zurück."""
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result, offset


def parse_dex_strings(data: bytes) -> list:
    """Gibt alle Strings aus dem DEX String Pool zurück."""
    if data[:4] != b'dex\n':
        return []
    string_ids_size = struct.unpack_from('<I', data, 56)[0]
    string_ids_off  = struct.unpack_from('<I', data, 60)[0]
    strings = []
    for i in range(string_ids_size):
        str_data_off = struct.unpack_from('<I', data, string_ids_off + i * 4)[0]
        length, str_start = read_uleb128(data, str_data_off)
        s = data[str_start:str_start + length].decode('utf-8', errors='replace')
        strings.append(s)
    return strings


def parse_dex_method_ids(data: bytes) -> list:
    """Gibt alle method_ids als (class_idx, proto_idx, name_idx) zurück."""
    method_ids_size = struct.unpack_from('<I', data, 88)[0]
    method_ids_off  = struct.unpack_from('<I', data, 92)[0]
    methods = []
    for i in range(method_ids_size):
        off = method_ids_off + i * 8
        class_idx = struct.unpack_from('<H', data, off)[0]
        proto_idx = struct.unpack_from('<H', data, off + 2)[0]
        name_idx  = struct.unpack_from('<H', data, off + 4)[0]
        methods.append((class_idx, proto_idx, name_idx))
    return methods


def parse_dex_type_ids(data: bytes) -> list:
    """Gibt alle type_ids (descriptor_idx) zurück."""
    type_ids_size = struct.unpack_from('<I', data, 64)[0]
    type_ids_off  = struct.unpack_from('<I', data, 68)[0]
    types = []
    for i in range(type_ids_size):
        desc_idx = struct.unpack_from('<I', data, type_ids_off + i * 4)[0]
        types.append(desc_idx)
    return types


def find_audiomanager_requestaudiofocus_method_idx(data: bytes) -> int:
    """
    Findet den method_id Index für AudioManager.requestAudioFocus(AudioFocusRequest).
    Gibt -1 zurück wenn nicht gefunden.
    """
    strings  = parse_dex_strings(data)
    type_ids = parse_dex_type_ids(data)
    methods  = parse_dex_method_ids(data)

    # Finde "requestAudioFocus" String Index
    req_af_name_idx = -1
    for i, s in enumerate(strings):
        if s == 'requestAudioFocus':
            req_af_name_idx = i
            break

    if req_af_name_idx == -1:
        print("    'requestAudioFocus' String nicht im String Pool gefunden!")
        return -1

    print(f"    'requestAudioFocus' String @ index {req_af_name_idx}")

    # Finde AudioManager Type Index
    audio_manager_type_idx = -1
    for i, desc_idx in enumerate(type_ids):
        if strings[desc_idx] == 'Landroid/media/AudioManager;':
            audio_manager_type_idx = i
            break

    if audio_manager_type_idx == -1:
        print("    AudioManager Type nicht gefunden!")
        return -1

    print(f"    AudioManager type @ index {audio_manager_type_idx}")

    # Finde method_id: class=AudioManager, name=requestAudioFocus
    for i, (class_idx, proto_idx, name_idx) in enumerate(methods):
        if class_idx == audio_manager_type_idx and name_idx == req_af_name_idx:
            print(f"    AudioManager.requestAudioFocus method_id @ index {i}")
            return i

    print("    AudioManager.requestAudioFocus method_id nicht gefunden!")
    return -1


def patch_dex_no_audiofocus(dex_data: bytes) -> tuple:
    """
    Findet den invoke-virtual Call zu AudioManager.requestAudioFocus()
    und ersetzt ihn so dass kein echter Focus Request gemacht wird.

    invoke-virtual Format (35c): 6 Bytes
      0x6e [arg_count|0x20] [method_idx_lo] [method_idx_hi] [regs] [regs]
    move-result vX: 2 Bytes
      0x0a [register]

    Ersatz (8 Bytes total):
      const/4 v0, 0x1   (2 Bytes: 0x12 0x10) = AUDIOFOCUS_REQUEST_GRANTED
      nop               (2 Bytes: 0x00 0x00)
      nop               (2 Bytes: 0x00 0x00)
      nop               (2 Bytes: 0x00 0x00)
    -> Und move-result wird zu nop da v0 schon gesetzt ist

    Ergebnis: Brave denkt es hat Focus (return true), ruft aber AudioManager NIE an.
    -> Tidal/Spotify bekommen kein AUDIOFOCUS_LOSS -> spielen weiter!
    """
    data = bytearray(dex_data)

    if b'AudioFocusDelegate' not in data:
        return bytes(data), False

    print("    ✓ AudioFocusDelegate gefunden")

    method_idx = find_audiomanager_requestaudiofocus_method_idx(bytes(data))
    if method_idx == -1:
        return fallback_patch_no_focus(data)

    # Suche invoke-virtual (0x6e) mit diesem method_idx
    method_idx_lo = method_idx & 0xFF
    method_idx_hi = (method_idx >> 8) & 0xFF

    found_at = -1
    for i in range(len(data) - 7):
        if data[i] != 0x6e:
            continue
        if data[i+2] != method_idx_lo or data[i+3] != method_idx_hi:
            continue

        # Gefunden! Prüfe ob danach move-result kommt (innerhalb 2 bytes)
        if data[i+6] == 0x0a:
            move_result_reg = data[i+7]
            found_at = i
            print(f"    invoke-virtual AudioManager.requestAudioFocus @ 0x{i:08x}")
            print(f"    move-result v{move_result_reg} @ 0x{i+6:08x}")
            break

    if found_at == -1:
        print("    invoke-virtual nicht gefunden, versuche Fallback...")
        return fallback_patch_no_focus(data)

    move_result_reg = data[found_at + 7]

    # Patch: invoke-virtual (6 bytes) → const/4 v{reg}, 0x1 + nop + nop
    # const/4 vX, 0x1 = 0x12 (0x10 | reg)
    const_byte = (0x1 << 4) | (move_result_reg & 0xF)
    data[found_at + 0] = 0x12  # const/4
    data[found_at + 1] = const_byte  # v{reg} = 1 (AUDIOFOCUS_REQUEST_GRANTED)
    data[found_at + 2] = 0x00  # nop
    data[found_at + 3] = 0x00
    data[found_at + 4] = 0x00  # nop
    data[found_at + 5] = 0x00

    # move-result → nop (v{reg} ist schon durch const/4 gesetzt)
    data[found_at + 6] = 0x00  # nop
    data[found_at + 7] = 0x00

    print(f"    ✓ PATCH: invoke-virtual → const/4 v{move_result_reg}, 0x1 + nops")
    print(f"      Brave spielt Audio ohne AudioFocus Request → Tidal ungestört!")

    fix_dex_checksum(data)
    return bytes(data), True


def fallback_patch_no_focus(data: bytearray) -> tuple:
    """
    Fallback: Sucht invoke-virtual (0x6e) gefolgt von move-result (0x0a)
    im Bereich um AudioFocusDelegate, nimmt den wahrscheinlichsten Treffer.
    """
    print("    Fallback: Suche invoke-virtual+move-result Pattern...")

    # Finde AudioFocusDelegate Positionen
    positions = []
    idx = 0
    while True:
        pos = bytes(data).find(b'AudioFocusDelegate', idx)
        if pos == -1:
            break
        positions.append(pos)
        idx = pos + 1

    candidates = []
    for str_pos in positions:
        search_start = max(0, str_pos - 3000)
        search_end   = min(len(data), str_pos + 3000)
        for i in range(search_start, search_end - 7):
            if data[i] == 0x6e and data[i+6] == 0x0a:
                candidates.append(i)

    if not candidates:
        print("    ✗ Kein invoke-virtual+move-result gefunden!")
        return bytes(data), False

    # Nehme den letzten Kandidaten (requestAudioFocus ist am Ende der Methode)
    i = candidates[-1]
    reg = data[i+7] & 0xF
    const_byte = (0x1 << 4) | reg

    data[i+0] = 0x12
    data[i+1] = const_byte
    data[i+2] = 0x00
    data[i+3] = 0x00
    data[i+4] = 0x00
    data[i+5] = 0x00
    data[i+6] = 0x00
    data[i+7] = 0x00

    print(f"    FALLBACK PATCH @ 0x{i:08x}: invoke-virtual → const/4 v{reg}, 0x1 + nops")
    fix_dex_checksum(data)
    return bytes(data), True


def fix_dex_checksum(data: bytearray):
    sha1 = hashlib.sha1(bytes(data[32:])).digest()
    data[12:32] = sha1
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)


def patch_apk(input_apk: Path, output_apk: Path) -> bool:
    print(f"  Input:  {input_apk} ({input_apk.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  Output: {output_apk}")

    patched = False

    with zipfile.ZipFile(input_apk, 'r') as zin, \
         zipfile.ZipFile(output_apk, 'w', allowZip64=True) as zout:

        for item in zin.infolist():
            data = zin.read(item.filename)

            if item.filename.endswith('.dex') and not patched:
                print(f"\n  Prüfe {item.filename} ({len(data):,} bytes)...")
                new_data, success = patch_dex_no_audiofocus(data)
                if success:
                    patched = True
                    data = new_data
                    print(f"  ✓ Gepatcht!")

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
    print("AudioFocus DEX Patcher v3 - KEIN AudioFocus Request")
    print("Tidal/Spotify laufen weiter wenn Brave Video startet")
    print("=" * 60)

    if patch_apk(input_apk, output_apk):
        print("\n✅ FERTIG:", output_apk)
    else:
        print("\n❌ FEHLER: AudioFocusDelegate nicht gefunden!")
        sys.exit(1)


if __name__ == "__main__":
    main()
