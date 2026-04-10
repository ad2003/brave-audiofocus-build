#!/usr/bin/env python3
"""
apply_patch.py <apk_extracted_dir>

Direkter Binary-Patch auf DEX-Datei.
Kein baksmali/smali noetig - nur Python!

DEX Bytecode:
  const/4 vX, 0x1 = [0x12, (0x10 | X)]  X=Register, 1=Wert
  const/4 vX, 0x3 = [0x12, (0x30 | X)]  X=Register, 3=Wert

Wir suchen in der requestAudioFocus Methode von AudioFocusDelegate
nach const/4 vX, 0x1 und aendern es zu const/4 vX, 0x3.
"""

import sys
import struct
import zlib
from pathlib import Path


def fix_dex_checksum(data: bytearray) -> bytearray:
    """Aktualisiert SHA1 Signature und Adler32 Checksum in DEX Header."""
    import hashlib
    # SHA1 ueber bytes ab offset 32 (nach magic + checksum + signature)
    sha1 = hashlib.sha1(data[32:]).digest()
    data[12:32] = sha1
    # Adler32 ueber bytes ab offset 12 (nach magic + checksum)
    adler = zlib.adler32(bytes(data[12:])) & 0xFFFFFFFF
    struct.pack_into('<I', data, 8, adler)
    return data


def find_string_offset(dex_data: bytes, target: str) -> list:
    """Findet alle Vorkommen eines Strings in DEX."""
    encoded = target.encode('utf-8')
    offsets = []
    start = 0
    while True:
        pos = dex_data.find(encoded, start)
        if pos == -1:
            break
        offsets.append(pos)
        start = pos + 1
    return offsets


def patch_dex(dex_path: Path) -> bool:
    """Patcht const/4 vX, 0x1 -> 0x3 in requestAudioFocus Methode."""
    data = bytearray(dex_path.read_bytes())
    original = bytes(data)

    print(f"\n  DEX: {dex_path.name} ({len(data):,} bytes)")

    # Prüfe ob AudioFocusDelegate ueberhaupt in dieser DEX ist
    if b"AudioFocusDelegate" not in data:
        print("  AudioFocusDelegate nicht in dieser DEX")
        return False

    print("  AudioFocusDelegate gefunden!")

    # Finde "requestAudioFocus" String-Referenz in DEX
    offsets = find_string_offset(data, "requestAudioFocus")
    if not offsets:
        print("  'requestAudioFocus' String nicht gefunden!")
        return False

    print(f"  'requestAudioFocus' gefunden an {len(offsets)} Stelle(n)")

    # Suche im Bereich um den String nach const/4 vX, 0x1
    # const/4 Opcode = 0x12, dann ein Byte mit (value<<4 | register)
    # 0x1 als value: zweites Byte hat Form 0x1X (upper nibble = 1)
    
    patches_applied = 0
    search_radius = 2000  # Bytes um den String herum suchen

    for str_offset in offsets:
        # Suche in einem Bereich um den String
        search_start = max(0, str_offset - search_radius)
        search_end = min(len(data), str_offset + search_radius)
        region = data[search_start:search_end]

        # Finde alle const/4 vX, 0x1 Instruktionen (0x12 gefolgt von 0x1X)
        i = 0
        while i < len(region) - 1:
            if region[i] == 0x12:  # const/4 opcode
                second_byte = region[i + 1]
                value_nibble = (second_byte >> 4) & 0xF   # oberes Nibble = Wert
                reg_nibble = second_byte & 0xF             # unteres Nibble = Register

                if value_nibble == 0x1:  # AUDIOFOCUS_GAIN = 1
                    abs_offset = search_start + i
                    print(f"  const/4 v{reg_nibble}, 0x1 gefunden @ offset {abs_offset} (0x{abs_offset:x})")

                    # Aendere zu const/4 vX, 0x3 (AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                    new_byte = (0x3 << 4) | reg_nibble
                    data[abs_offset + 1] = new_byte
                    patches_applied += 1
                    print(f"  -> const/4 v{reg_nibble}, 0x3 (gepatcht!)")
            i += 1

    if patches_applied == 0:
        print("  Keine const/4 vX, 0x1 Instruktionen in der Naehe gefunden!")
        print("  Versuche breiteren Suchradius (5000 bytes)...")
        
        for str_offset in offsets:
            search_start = max(0, str_offset - 5000)
            search_end = min(len(data), str_offset + 5000)
            region = data[search_start:search_end]
            i = 0
            while i < len(region) - 1:
                if region[i] == 0x12:
                    second_byte = region[i + 1]
                    value_nibble = (second_byte >> 4) & 0xF
                    reg_nibble = second_byte & 0xF
                    if value_nibble == 0x1:
                        abs_offset = search_start + i
                        new_byte = (0x3 << 4) | reg_nibble
                        data[abs_offset + 1] = new_byte
                        patches_applied += 1
                        print(f"  const/4 v{reg_nibble}, 0x1 @ {abs_offset} -> 0x3")
                i += 1

    if patches_applied == 0:
        print("  FEHLER: Keine Patches angewendet!")
        return False

    # DEX Checksum aktualisieren
    print(f"\n  {patches_applied} Patch(es) angewendet. Aktualisiere Checksum...")
    data = fix_dex_checksum(data)

    # Speichern
    dex_path.with_suffix(".dex.orig").write_bytes(original)
    dex_path.write_bytes(data)
    print(f"  Gespeichert! (Backup: {dex_path.stem}.dex.orig)")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 apply_patch.py <apk_extracted_dir>")
        sys.exit(1)

    apk_dir = Path(sys.argv[1])
    print("=" * 60)
    print("AudioFocus DEX Binary Patcher")
    print("=" * 60)

    # Finde alle DEX Dateien
    dex_files = sorted(apk_dir.glob("*.dex"))
    if not dex_files:
        # Auch in Unterordnern suchen
        dex_files = sorted(apk_dir.rglob("*.dex"))

    print(f"\nDEX Dateien: {[d.name for d in dex_files]}")

    patched = False
    for dex in dex_files:
        if patch_dex(dex):
            patched = True
            break  # Nur eine DEX muss gepatcht werden

    print("\n" + "=" * 60)
    if patched:
        print("ERFOLG!")
        print("AUDIOFOCUS_GAIN (0x1) -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (0x3)")
    else:
        print("FEHLER: Patch nicht angewendet!")
        sys.exit(1)


if __name__ == "__main__":
    main()
