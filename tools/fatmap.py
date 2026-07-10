#!/usr/bin/env python3
"""Read-only FAT32 forensics: map every file's cluster chain on the SD card."""
import struct, sys

DEV = sys.argv[1] if len(sys.argv) > 1 else "/dev/rdisk4s1"
f = open(DEV, "rb")

bpb = f.read(512)
bps = struct.unpack_from("<H", bpb, 11)[0]          # bytes/sector
spc = bpb[13]                                        # sectors/cluster
reserved = struct.unpack_from("<H", bpb, 14)[0]
nfats = bpb[16]
fatsz = struct.unpack_from("<I", bpb, 36)[0]         # sectors per FAT
root_clus = struct.unpack_from("<I", bpb, 44)[0]
data_start = (reserved + nfats * fatsz) * bps        # byte offset of cluster 2
cluster_bytes = spc * bps
print(f"bytes/sector={bps} sectors/cluster={spc} cluster={cluster_bytes}B "
      f"reserved={reserved} fats={nfats} fatsz={fatsz} root_clus={root_clus}")

f.seek(reserved * bps)
fat = f.read(fatsz * bps)
def next_clus(c):
    return struct.unpack_from("<I", fat, c * 4)[0] & 0x0FFFFFFF

def read_cluster(c):
    f.seek(data_start + (c - 2) * cluster_bytes)
    return f.read(cluster_bytes)

def chain(first):
    out = []
    c = first
    while 2 <= c < 0x0FFFFFF8 and len(out) < 100000:
        out.append(c)
        c = next_clus(c)
    return out

def runs(ch):
    if not ch:
        return []
    r = [[ch[0], ch[0]]]
    for c in ch[1:]:
        if c == r[-1][1] + 1:
            r[-1][1] = c
        else:
            r.append([c, c])
    return r

# parse a directory cluster chain: collect (longname, shortname, first_cluster, size, is_dir)
def parse_dir(first):
    entries = []
    lfn = {}
    for c in chain(first):
        data = read_cluster(c)
        for i in range(0, len(data), 32):
            e = data[i:i+32]
            if e[0] == 0x00:
                return entries
            if e[0] == 0xE5:
                lfn.clear(); continue
            attr = e[11]
            if attr == 0x0F:  # LFN entry
                seq = e[0] & 0x1F
                part = e[1:11] + e[14:26] + e[28:32]
                lfn[seq] = part.decode("utf-16-le", "replace")
                continue
            short = (e[0:8].decode("ascii","replace").rstrip() + "." +
                     e[8:11].decode("ascii","replace").rstrip()).rstrip(".")
            name = "".join(lfn[k] for k in sorted(lfn)) if lfn else short
            name = name.split("\x00")[0].rstrip("￿")
            lfn.clear()
            first_c = (struct.unpack_from("<H", e, 20)[0] << 16) | struct.unpack_from("<H", e, 26)[0]
            size = struct.unpack_from("<I", e, 28)[0]
            entries.append((name, short, first_c, size, bool(attr & 0x10)))
    return entries

for name, short, first_c, size, is_dir in parse_dir(root_clus):
    if is_dir or name in (".", ".."):
        print(f"[dir ] {name} @clus {first_c}")
        continue
    ch = chain(first_c) if first_c else []
    rr = runs(ch)
    tag = "CONTIGUOUS" if len(rr) <= 1 else f"FRAGMENTED x{len(rr)}"
    print(f"[file] {name} ({size}B, {len(ch)} clusters) {tag}")
    for a, b in rr:
        print(f"        clusters {a}..{b} ({b-a+1})")
f.close()
