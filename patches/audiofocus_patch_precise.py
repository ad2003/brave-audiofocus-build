#!/usr/bin/env python3
"""
audiofocus_patch_precise.py [--mode noop|duck] <input.apk> [output.apk]

Patches Brave's audio focus behaviour so music apps are not stopped when a
video starts playing in Brave.

MODES
-----
noop  (default, original behaviour)
      Replaces every AudioManager.requestAudioFocus() invoke with a no-op that
      returns AUDIOFOCUS_REQUEST_GRANTED. Brave never notifies Android, so
      Tidal/Spotify keep playing at full volume.
      Side effect: hardware media keys may no longer control Brave.

duck  (new)
      Leaves the focus request fully intact but forces the requested focus type
      to AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (3) instead of AUDIOFOCUS_GAIN (1).
      Other apps receive AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK and (if they honour
      it) fade down instead of stopping; when the video ends Brave abandons
      focus normally and the music fades back up.
      Media keys keep working because a real focus request still happens.

      Whether a given music app ducks rather than pauses is that app's decision.
      Tidal is observed to duck on transient requests; Spotify may still pause.

HOW THE DUCK PATCH WORKS
------------------------
In org.chromium.content.browser.AudioFocusDelegate.requestAudioFocus(boolean)
Chromium already contains both focus types:

    const/4 v0, 1        # AUDIOFOCUS_GAIN
    const/4 v1, 3        # AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK
    if-eqz  v8, +4       # if (!transient) jump
    move    v8, v1       # transient path  -> 3
    goto    +2
    move    v8, v0       # normal path     -> 1   <-- patched to v1
    iput    v8, v7, AudioFocusDelegate->a I

Patching the second move to source from the register already holding 3 makes
every request transient/duckable. This is a single byte and does not change any
instruction length, so no offsets shift and the method stays verifiable.

Note we deliberately do NOT patch 'const/4 v0, 1' even though that looks
simpler: v0 is reused further down as AudioAttributes.setUsage(1) = USAGE_MEDIA.
Changing it would rewrite Brave's audio attributes to USAGE_VOICE_COMMUNICATION
and route playback to the earpiece/call stream.
"""

import sys, struct, zlib, hashlib, zipfile
from pathlib import Path

DELEGATE = 'Lorg/chromium/content/browser/AudioFocusDelegate;'
AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK = 3
AUDIOFOCUS_GAIN = 1


# ---------------------------------------------------------------- DEX helpers

def fix_dex_checksum(data: bytearray):
    """Update SHA1 signature and Adler32 checksum in the DEX header."""
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
    out = []
    for i in range(size):
        so = struct.unpack_from('<I', data, off + i*4)[0]
        ln, st = read_uleb128(data, so)
        out.append(data[st:st+ln].decode('utf-8', 'replace'))
    return out


def parse_type_ids(data):
    size = struct.unpack_from('<I', data, 64)[0]
    off  = struct.unpack_from('<I', data, 68)[0]
    return [struct.unpack_from('<I', data, off + i*4)[0] for i in range(size)]


def parse_field_ids(data):
    """field_id_item: class_idx(u2), type_idx(u2), name_idx(u4)"""
    size = struct.unpack_from('<I', data, 80)[0]
    off  = struct.unpack_from('<I', data, 84)[0]
    out = []
    for i in range(size):
        o = off + i*8
        out.append((struct.unpack_from('<H', data, o)[0],
                    struct.unpack_from('<H', data, o+2)[0],
                    struct.unpack_from('<I', data, o+4)[0]))
    return out


def parse_method_ids(data):
    size = struct.unpack_from('<I', data, 88)[0]
    off  = struct.unpack_from('<I', data, 92)[0]
    out = []
    for i in range(size):
        o = off + i*8
        out.append((struct.unpack_from('<H', data, o)[0],
                    struct.unpack_from('<H', data, o+2)[0],
                    struct.unpack_from('<H', data, o+4)[0]))
    return out


def parse_class_defs(data):
    size = struct.unpack_from('<I', data, 96)[0]
    off  = struct.unpack_from('<I', data, 100)[0]
    out = []
    for i in range(size):
        o = off + i*32
        out.append((struct.unpack_from('<I', data, o)[0],       # class_idx
                    struct.unpack_from('<I', data, o+24)[0]))   # class_data_off
    return out


def parse_class_methods(data, class_data_off):
    """Return list of (method_idx, code_off) for direct + virtual methods."""
    if class_data_off == 0:
        return []
    p = class_data_off
    sf, p  = read_uleb128(data, p)
    inf, p = read_uleb128(data, p)
    dm, p  = read_uleb128(data, p)
    vm, p  = read_uleb128(data, p)
    for _ in range(sf + inf):                 # skip encoded_fields
        _d, p = read_uleb128(data, p)
        _a, p = read_uleb128(data, p)
    methods = []
    for count in (dm, vm):
        idx = 0
        for _ in range(count):
            d, p  = read_uleb128(data, p); idx += d
            _a, p = read_uleb128(data, p)
            co, p = read_uleb128(data, p)
            methods.append((idx, co))
    return methods


def code_insns_span(data, code_off):
    """code_item: registers(u2) ins(u2) outs(u2) tries(u2) debug(u4) insns_size(u4)"""
    insns_size = struct.unpack_from('<I', data, code_off + 12)[0]
    return code_off + 16, insns_size * 2


# ------------------------------------------------------------------ noop mode

def find_all_audiofocus_method_ids(data: bytes) -> list:
    strings  = parse_strings(data)
    type_ids = parse_type_ids(data)
    methods  = parse_method_ids(data)

    raf = {i for i, s in enumerate(strings) if s == 'requestAudioFocus'}
    if not raf:
        return []
    result = []
    for i, (class_idx, _proto, name_idx) in enumerate(methods):
        if name_idx in raf:
            cls = strings[type_ids[class_idx]] if class_idx < len(type_ids) else '?'
            print(f"    method_id {i}: {cls}->requestAudioFocus")
            result.append(i)
    return result


def patch_dex_noop(dex_data: bytes) -> tuple:
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
            if (data[i] == 0x6e and data[i+2] == lo and
                data[i+3] == hi and data[i+6] == 0x0a):
                reg = data[i+7] & 0xF
                print(f"    PATCH @ 0x{i:08x}: invoke-virtual -> const/4 v{reg}, 0x1 + nops")
                data[i:i+6] = bytes([0x12, (0x1 << 4) | reg, 0, 0, 0, 0])
                data[i+6:i+8] = b'\x00\x00'
                total += 1
                i += 8
            else:
                i += 1
    if total:
        fix_dex_checksum(data)
    return bytes(data), total


# ------------------------------------------------------------------ duck mode

def patch_dex_duck(dex_data: bytes) -> tuple:
    """
    Force AudioFocusDelegate's focus type field to MAY_DUCK by repointing the
    'normal video' move to the register that already holds 3.
    """
    data = bytearray(dex_data)
    if DELEGATE.encode() not in data:
        return bytes(data), 0

    strings   = parse_strings(bytes(data))
    type_ids  = parse_type_ids(bytes(data))
    fields    = parse_field_ids(bytes(data))
    methods   = parse_method_ids(bytes(data))
    classdefs = parse_class_defs(bytes(data))

    tidx = next((i for i, t in enumerate(type_ids)
                 if strings[t] == DELEGATE), None)
    if tidx is None:
        return bytes(data), 0
    print(f"    found {DELEGATE} (type_idx {tidx})")

    # int field that stores the focus type (Chromium names it 'a' after R8)
    field_candidates = [i for i, (c, t, _n) in enumerate(fields)
                        if c == tidx and strings[type_ids[t]] == 'I']
    if not field_candidates:
        print("    ! no int field on delegate — aborting duck patch")
        return bytes(data), 0

    cd = next((c for c in classdefs if c[0] == tidx), None)
    if cd is None:
        return bytes(data), 0

    total = 0
    for method_idx, code_off in parse_class_methods(bytes(data), cd[1]):
        if code_off == 0:
            continue
        if strings[methods[method_idx][2]] != 'requestAudioFocus':
            continue

        start, length = code_insns_span(bytes(data), code_off)
        b = data[start:start+length]
        print(f"    requestAudioFocus code @ 0x{code_off:x} ({length} insn bytes)")

        # locate: iput vA, vB, <int field of delegate>   (opcode 0x59)
        target = None
        for fi in field_candidates:
            lo, hi = fi & 0xFF, (fi >> 8) & 0xFF
            for i in range(len(b) - 3):
                if b[i] == 0x59 and b[i+2] == lo and b[i+3] == hi:
                    target = (i, fi)
                    break
            if target:
                break
        if not target:
            print("    ! no iput to delegate int field found — aborting")
            continue

        pos, fi = target
        a_reg = b[pos+1] & 0xF                 # value register of the iput
        print(f"    iput v{a_reg}, v{(b[pos+1]>>4)&0xF}, field#{fi} @insn+{pos}")

        # the instruction right before must be 'move vA, vSrc' (opcode 0x01)
        if pos < 2 or b[pos-2] != 0x01:
            print("    ! expected 'move' before iput, found "
                  f"0x{b[pos-2]:02x} — layout changed, aborting")
            continue
        mv_a = b[pos-1] & 0xF
        mv_b = (b[pos-1] >> 4) & 0xF
        if mv_a != a_reg:
            print(f"    ! move target v{mv_a} != iput source v{a_reg} — aborting")
            continue

        # find registers preloaded with const/4 1 and const/4 3
        reg_with = {}
        for i in range(0, pos, 2):
            if b[i] == 0x12:
                val = (b[i+1] >> 4) & 0xF
                reg = b[i+1] & 0xF
                reg_with.setdefault(val, reg)
        reg3 = reg_with.get(AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
        reg1 = reg_with.get(AUDIOFOCUS_GAIN)
        print(f"    const/4 registers: 1->v{reg1}  3->v{reg3}")

        if reg3 is None:
            print("    ! no register holding 3 — aborting")
            continue
        if mv_b == reg3:
            print("    already sources MAY_DUCK — nothing to do")
            continue
        if reg1 is not None and mv_b != reg1:
            print(f"    ! move sources v{mv_b}, expected GAIN reg v{reg1} — aborting")
            continue

        newbyte = (reg3 << 4) | mv_a
        print(f"    PATCH @ 0x{start+pos-1:08x}: move v{mv_a}, v{mv_b} "
              f"-> move v{mv_a}, v{reg3}   (0x{b[pos-1]:02x} -> 0x{newbyte:02x})")
        data[start + pos - 1] = newbyte
        total += 1

    if total:
        fix_dex_checksum(data)
    return bytes(data), total


# ---------------------------------------------------------------------- apk

def patch_apk(input_apk: Path, output_apk: Path, mode: str) -> bool:
    total = 0
    patch_dex = patch_dex_duck if mode == 'duck' else patch_dex_noop

    with zipfile.ZipFile(input_apk, 'r') as zin, \
         zipfile.ZipFile(output_apk, 'w', allowZip64=True) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith('.dex'):
                print(f"\n  Checking {item.filename} ({len(data):,} bytes)...")
                data, n = patch_dex(data)
                if n:
                    print(f"  OK {n} patch(es) applied")
                    total += n
            zout.writestr(item, data, compress_type=item.compress_type)

    print(f"\n  Total patches: {total}")
    return total > 0


def main():
    args = sys.argv[1:]
    mode = 'noop'
    if args and args[0] in ('--mode', '-m'):
        if len(args) < 2 or args[1] not in ('noop', 'duck'):
            print("Usage: audiofocus_patch_precise.py [--mode noop|duck] <in.apk> [out.apk]")
            sys.exit(1)
        mode = args[1]; args = args[2:]

    if not args:
        print("Usage: audiofocus_patch_precise.py [--mode noop|duck] <in.apk> [out.apk]")
        sys.exit(1)

    input_apk  = Path(args[0])
    output_apk = Path(args[1]) if len(args) > 1 else \
                 input_apk.with_stem(input_apk.stem + '_patched')

    print("=" * 66)
    print(f"AudioFocus Patcher  --  mode: {mode}")
    if mode == 'duck':
        print("Force focus type -> AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK (3)")
        print("Music apps should fade down instead of stopping")
    else:
        print("Disable all requestAudioFocus() calls")
        print("Music apps keep playing at full volume")
    print("=" * 66)

    if not input_apk.exists():
        print(f"Error: file not found: {input_apk}")
        sys.exit(1)

    print(f"\n  Input:  {input_apk} ({input_apk.stat().st_size/1024/1024:.1f} MB)")
    print(f"  Output: {output_apk}")

    if patch_apk(input_apk, output_apk, mode):
        print(f"\nDone: {output_apk}")
    else:
        print("\nNo patches applied.")
        sys.exit(1)


if __name__ == '__main__':
    main()
