#!/usr/bin/env python3
"""Card factory off-by-one + duplicate-content detector.
Standalone hardening tool. Run after EVERY batch card deploy.

Catches:
  · Pages shifted by 1 (the Canva export sometimes prepends the cover monogram)
  · Duplicate-content groups (last card lost, gap card holds wrong image)
  · A monogram image sitting in a product slot (the shift-start fingerprint)

Usage:
  python3 tools/check_card_shift.py <house_prefix>
  examples:
    python3 tools/check_card_shift.py "Dua "
    python3 tools/check_card_shift.py "Local Niche "
    python3 tools/check_card_shift.py "Aventus "

Exits 1 (CI-friendly) if any suspect file is found.
"""
import sys, os, glob, hashlib, json
from collections import defaultdict

# Known monogram hashes (CURATED ARCHIVE textless cover). Add new ones here as caught.
MONOGRAM_HASHES = {
    "0001337c90f6469cba25b43aceece3fe",  # original Dua MOD batch monogram
}

def md5(path):
    h=hashlib.md5()
    with open(path,'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''): h.update(chunk)
    return h.hexdigest()

def main():
    if len(sys.argv) < 2:
        print("Usage: check_card_shift.py <house_prefix>", file=sys.stderr); sys.exit(2)
    prefix = sys.argv[1]
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pat = os.path.join(repo, f"{prefix}*.jpg")
    files = sorted(glob.glob(pat))
    if not files:
        print(f"No files matched: {pat}"); sys.exit(2)
    print(f"Scanning {len(files)} files matching {prefix}*.jpg")
    hashes = {f: md5(f) for f in files}
    # 1. Monogram in product slot
    monogram_hits = [(os.path.basename(f), h) for f,h in hashes.items() if h in MONOGRAM_HASHES]
    # 2. Duplicate content groups (>=2 different filenames sharing one hash)
    by_hash = defaultdict(list)
    for f,h in hashes.items(): by_hash[h].append(os.path.basename(f))
    dupes = {h: names for h,names in by_hash.items() if len(names) > 1}
    fail = False
    if monogram_hits:
        fail = True
        print(f"\n[FAIL] MONOGRAM IN PRODUCT SLOT ({len(monogram_hits)}):")
        for name,h in monogram_hits: print(f"  {name}  (md5 {h})")
        print("  -> the export shifted, the monogram cover landed where a card should be")
    if dupes:
        fail = True
        print(f"\n[FAIL] DUPLICATE-CONTENT GROUPS ({len(dupes)}):")
        for h,names in dupes.items():
            print(f"  md5 {h}:")
            for n in names: print(f"    {n}")
        print("  -> two filenames hold the same image, the last card is likely lost")
    if not fail:
        print(f"\n[ OK ] {len(files)} cards scanned, no monogram leaks, no content duplicates")
        sys.exit(0)
    print(f"\n[FAIL] Batch is unsafe to ship. Fix the shift before deploying.")
    sys.exit(1)

if __name__ == "__main__": main()
