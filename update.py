#!/usr/bin/env python3
"""Refresh docs/items.json from the links in links.txt.

- Poshmark listing links are checked one by one (title, photo, price, size, sold or not).
- thredUP shared-favorites links (/fv/...) are expanded into every item on the wishlist.

An item that's sold or unavailable is marked "gone" and hidden from the registry page.
If a site can't be reached, the item keeps its last known status, so a temporary
outage never wipes the registry.

Standard library only, so it runs anywhere with Python 3.9+.
"""
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LINKS = ROOT / "links.txt"
OUT = ROOT / "docs" / "items.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class NotFound(Exception):
    pass


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        try:
            # Keep headers minimal: thredUP's bot filter rejects some browser-like combos.
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.geturl(), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise NotFound(url)
            last = e
        except Exception as e:  # network hiccup, timeout, etc.
            last = e
        time.sleep(2 * (i + 1))
    raise last


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------- Poshmark ----------

def posh_id(url):
    m = re.search(r"([0-9a-f]{24})/?(?:[?#].*)?$", url)
    return m.group(1) if m else None


def title_from_slug(url):
    slug = url.rstrip("/").split("/")[-1]
    slug = re.sub(r"-?[0-9a-f]{24}$", "", slug)
    return slug.replace("-", " ").strip() or "Poshmark item"


def check_poshmark(url):
    lid = posh_id(url)
    try:
        final_url, page = fetch(url)
    except NotFound:
        return {"status": "gone"}
    m = re.search(r'data-vmid="ldjson-schema-listing"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("no listing data on page (blocked or layout changed?)")
    d = json.loads(m.group(1))
    if lid and d.get("productID") != lid:
        return {"status": "gone"}  # redirected somewhere else: listing removed
    offer = d.get("offers") or {}
    in_stock = "InStock" in (offer.get("availability") or "")
    # The listing's own size is the first one inside its "listingDetails" block of the page state.
    size = None
    inv = re.search(r'"listingDetails":\{"id":"%s".{0,8000}?"size_obj":\{[^}]*?"display":"([^"]*)"' % lid,
                    page, re.S)
    if inv:
        size = html.unescape(inv.group(1))
    image = d.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    price = offer.get("price")
    return {
        "status": "available" if in_stock else "gone",
        "title": html.unescape(d.get("name") or title_from_slug(url)),
        "brand": html.unescape((d.get("brand") or {}).get("name") or ""),
        "image": image,
        "price": float(price) if price else None,
        "size": size,
    }


# ---------- thredUP ----------

THREDUP_STATUS = {"InStock": "available", "Reserved": "reserved"}


def check_thredup_wishlist(url):
    """Returns {id: item} for every item on a shared-favorites page."""
    _, page = fetch(url)
    m = re.search(r'<script id="data-apollo"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("no wishlist data on page (blocked or layout changed?)")
    state = json.loads(m.group(1))
    root = state.get("ROOT_QUERY", {})
    conn = next((v for k, v in root.items() if k.startswith("sharedFavorites")), None)
    if conn is None:
        raise ValueError("wishlist not found on page")
    out = {}
    for ref in conn.get("nodes", []):
        it = state.get(ref.get("__ref", ""), {})
        num = it.get("itemNumber")
        if not num:
            continue
        photos = it.get("photoIds") or []
        price = it.get("price")
        path = re.search(r'href="(/product/[^"]+/%s)"' % num, page)
        out[f"thredup:{num}"] = {
            "source": "thredup",
            "url": "https://www.thredup.com" + (path.group(1) if path else f"/product/{num}"),
            "status": THREDUP_STATUS.get(it.get("availability"), "gone"),
            "title": it.get("title") or "thredUP item",
            "brand": it.get("brand") or "",
            "image": f"https://cf-assets-thredup.thredup.com/assets/{photos[0]}/large.jpg" if photos else None,
            "price": float(price) if price else None,
            "size": it.get("sizeDisplay"),
        }
    return out


# ---------- main ----------

def main():
    links = []
    for line in LINKS.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in links:
            links.append(line)

    prev = {}
    if OUT.exists():
        prev = {i["id"]: i for i in json.loads(OUT.read_text()).get("items", [])}

    ts = now()
    results = {}   # id -> fresh data (or None if the check failed)
    order = []     # ids in display order
    errors = []

    wishlists = [l for l in links if "thredup.com/fv/" in l]
    posh = [l for l in links if "poshmark.com/listing/" in l]
    other = [l for l in links if l not in wishlists and l not in posh]
    for l in other:
        errors.append(f"skipped (not a Poshmark listing or thredUP wishlist): {l}")

    for wl in wishlists:
        try:
            for k, v in check_thredup_wishlist(wl).items():
                v["from"] = wl
                results[k] = v
                order.append(k)
        except Exception as e:
            errors.append(f"thredUP wishlist {wl}: {e}")
            # Keep whatever we knew from this wishlist last time.
            for k, v in prev.items():
                if v.get("from") == wl:
                    results[k] = None
                    order.append(k)

    def run(url):
        try:
            return url, check_poshmark(url), None
        except Exception as e:
            return url, None, e

    with ThreadPoolExecutor(max_workers=4) as pool:
        for url, data, err in pool.map(run, posh):
            k = f"posh:{posh_id(url) or url}"
            order.append(k)
            if err:
                errors.append(f"{url}: {err}")
                results[k] = None
            else:
                data.update(source="poshmark", url=url)
                results[k] = data

    items = []
    for n, k in enumerate(order):
        old = prev.get(k, {})
        new = results.get(k)
        if new is None:  # check failed: keep last known data
            if not old:
                url = next((u for u in posh if k.endswith(posh_id(u) or u)), "")
                old = {"source": "poshmark", "url": url, "title": title_from_slug(url),
                       "status": "unknown"}
            item = dict(old)
        else:
            item = {**old, **{kk: vv for kk, vv in new.items() if vv is not None or kk == "price"}}
            item["checked"] = ts
        item["id"] = k
        item["order"] = n
        item.setdefault("added", ts)
        if item.get("status") != old.get("status"):
            item["status_since"] = ts
        items.append(item)

    OUT.write_text(json.dumps({"updated": ts, "items": items}, indent=1) + "\n")

    counts = {}
    for i in items:
        counts[i["status"]] = counts.get(i["status"], 0) + 1
    print(f"{len(items)} items: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    changed = [i for i in items if i.get("status_since") == ts and i["id"] in prev]
    for i in changed:
        print(f"  now {i['status']}: {i['title']}")
    for e in errors:
        print("WARN", e, file=sys.stderr)
    # Fail loudly only if nothing at all could be checked (likely blocked).
    if errors and all(results.get(k) is None for k in order):
        sys.exit(1)


if __name__ == "__main__":
    main()
