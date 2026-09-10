#!/usr/bin/env python3
"""
Regenerates feed/google.xml (Google Merchant Center) and feed/meta.csv
(Meta Commerce Catalog) from the live Curated Archive catalog endpoint.

Read only: fetches https://curated-archive.com/... static site and the
live ?action=catalog endpoint on the Apps Script backend. Never writes to
the Google Sheet or the Apps Script backend. Re-runnable on demand:

    python3 tools/build_product_feeds.py

Modeling decision:
  - Each SIZE VARIANT of a product is its own feed item (g:id like
    "aventus-10j02-5ml"), grouped under g:item_group_id = the product
    slug ("aventus-10j02").
  - All variants in a group share the same landing page link
    (https://curated-archive.com/p/<house>/<product>/) because that page
    server renders a visible price table with ALL size offers (confirmed
    live, see report), so a shared landing page across the group is fine
    per Google's item_group_id spec. No query param anchor is added.

Stock / availability logic mirrors the storefront JS exactly (index.html,
sizeFits/mlLeft functions): a size s is orderable only if the product's
total stock (ml on hand) is >= s. stock 0 or "0" means every size is
sold out. This is NOT a per-size unit count, it is ml on hand.

The ?action=catalog endpoint already reflects only Active rows (inactive
rows are excluded server side by buildCatalog_()), so no separate Active
filter is applied here beyond what the endpoint already returns.
"""

import json
import math
import re
import subprocess
import sys
import xml.sax.saxutils as sx
from collections import defaultdict
from datetime import datetime, timezone

CATALOG_URL = "https://script.google.com/macros/s/AKfycbyMqvlROnEtvZ3pOjy7S8PoOdbryVmtFxzeqmDVn-dkzdz-b1mq-vhrIDxTGsuSLZ-f/exec?action=catalog"
SITE = "https://curated-archive.com"
FEED_DIR = "feed"

SIZE_LIST = [1, 2, 5, 10]


def slugify(s):
    s = s.lower()
    s = s.replace("&", "-")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def fetch_catalog():
    url = CATALOG_URL + f"&v={int(datetime.now().timestamp())}"
    # curl (via subprocess) follows the Apps Script 302 redirect reliably;
    # plain urllib has been observed to hang/timeout on this endpoint.
    out = subprocess.run(
        ["curl", "-sL", "--max-time", "45", url],
        capture_output=True, check=True,
    )
    return json.loads(out.stdout)


def ml_left(stock):
    if stock == "" or stock is None:
        return float("inf")
    try:
        n = float(stock)
    except (TypeError, ValueError):
        return float("inf")
    return n if n == n else float("inf")  # NaN guard


def build_items(catalog):
    """Returns (items, skipped) where items is a list of dicts per size
    variant and skipped is a list of (house, name, reason) tuples."""
    items = []
    skipped = []

    for house, products in catalog.items():
        house_slug = slugify(house)
        for it in products:
            name = it.get("name", "")
            prices = it.get("prices", {}) or {}
            image = it.get("image", "")
            stock = it.get("stock", None)
            desc = (it.get("description") or "").strip()

            if not name:
                skipped.append((house, "(unnamed)", "missing name"))
                continue
            if not image:
                skipped.append((house, name, "missing image"))
                continue
            if not prices:
                skipped.append((house, name, "missing price"))
                continue

            avail_ml = ml_left(stock)
            if avail_ml <= 0:
                skipped.append((house, name, "zero stock (sold out)"))
                continue

            product_slug = slugify(name)
            group_id = f"{house_slug}-{product_slug}"
            link = f"{SITE}/p/{house_slug}/{product_slug}/"
            img_name = image.rsplit(".", 1)[0] + ".webp"
            image_link = f"{SITE}/{urllib.parse.quote(img_name)}"

            if not desc:
                desc = f"{name} fragrance decant from Curated Archive, {house} house. Available in 1ml, 2ml, 5ml and 10ml sizes."

            any_variant = False
            for size in SIZE_LIST:
                price = prices.get(str(size))
                if price is None or price == "" or float(price) <= 0:
                    continue  # size not sold for this product, not an error
                in_stock = size <= avail_ml
                # The storefront's peso() formatter renders Math.ceil(price),
                # never the raw decimal (index.html: peso = n => "₱" +
                # Math.ceil(Number(n)||0)...). The feed price must match
                # that rendered number exactly, so ceil here too.
                shown_price = math.ceil(float(price))
                items.append({
                    "id": f"{group_id}-{size}ml",
                    "group_id": group_id,
                    "title": f"{house} {name} {size}ml Decant",
                    "description": desc,
                    "link": link,
                    "image_link": image_link,
                    "price": f"{shown_price:.2f} PHP",
                    "price_num": shown_price,
                    "availability": "in stock" if in_stock else "out of stock",
                    "brand": house,
                    "size_ml": size,
                })
                any_variant = True

            if not any_variant:
                skipped.append((house, name, "no priced sizes"))

    return items, skipped


import urllib.parse  # noqa: E402 (kept near use above for clarity)


def write_google_xml(items, path):
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append('<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">')
    lines.append("<channel>")
    lines.append("<title>Curated Archive Product Feed</title>")
    lines.append(f"<link>{SITE}/</link>")
    lines.append("<description>Google Merchant Center product feed for Curated Archive fragrance decants.</description>")
    lines.append(f"<pubDate>{now}</pubDate>")
    for it in items:
        lines.append("<item>")
        lines.append(f"<g:id>{sx.escape(it['id'])}</g:id>")
        lines.append(f"<title>{sx.escape(it['title'])}</title>")
        lines.append(f"<description>{sx.escape(it['description'])}</description>")
        lines.append(f"<link>{sx.escape(it['link'])}</link>")
        lines.append(f"<g:image_link>{sx.escape(it['image_link'])}</g:image_link>")
        lines.append(f"<g:price>{sx.escape(it['price'])}</g:price>")
        lines.append(f"<g:availability>{sx.escape(it['availability'])}</g:availability>")
        lines.append("<g:condition>new</g:condition>")
        lines.append(f"<g:brand>{sx.escape(it['brand'])}</g:brand>")
        lines.append(f"<g:item_group_id>{sx.escape(it['group_id'])}</g:item_group_id>")
        lines.append("<g:identifier_exists>false</g:identifier_exists>")
        lines.append("</item>")
    lines.append("</channel>")
    lines.append("</rss>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_meta_csv(items, path):
    import csv
    cols = ["id", "title", "description", "availability", "condition",
            "price", "link", "image_link", "brand", "item_group_id"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for it in items:
            w.writerow([
                it["id"], it["title"], it["description"], it["availability"],
                "new", it["price"], it["link"], it["image_link"], it["brand"],
                it["group_id"],
            ])


def main():
    print(f"Fetching live catalog from {CATALOG_URL} ...")
    payload = fetch_catalog()
    if not payload.get("ok"):
        print("Catalog endpoint did not return ok:true, aborting.", file=sys.stderr)
        sys.exit(1)
    catalog = payload["catalog"]

    items, skipped = build_items(catalog)

    import os
    os.makedirs(FEED_DIR, exist_ok=True)
    write_google_xml(items, f"{FEED_DIR}/google.xml")
    write_meta_csv(items, f"{FEED_DIR}/meta.csv")

    in_stock = sum(1 for i in items if i["availability"] == "in stock")
    out_stock = sum(1 for i in items if i["availability"] == "out of stock")
    groups = len(set(i["group_id"] for i in items))

    print("\n=== BUILD SUMMARY ===")
    print(f"Total feed items (variants): {len(items)}  across {groups} products")
    print(f"  in stock:     {in_stock}")
    print(f"  out of stock: {out_stock}  (still listed per Google spec, availability=out of stock)")
    print(f"Products skipped entirely: {len(skipped)}")
    reasons = defaultdict(list)
    for house, name, reason in skipped:
        reasons[reason].append(f"{house} / {name}")
    for reason, names in reasons.items():
        print(f"  [{reason}] x{len(names)}")
        for n in names:
            print(f"      - {n}")
    print(f"\nWrote {FEED_DIR}/google.xml and {FEED_DIR}/meta.csv")


if __name__ == "__main__":
    main()
