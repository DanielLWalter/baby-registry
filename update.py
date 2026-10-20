#!/usr/bin/env python3
"""Refresh docs/items.json from the links in links.txt.

- Poshmark listing links are checked one by one (title, photo, price, size, sold or not).
- thredUP shared-favorites links (/fv/...) are expanded into every item on the wishlist.

An item that's sold or unavailable is marked "gone" and hidden from the registry page.
If a site can't be reached, the item keeps its last known status, so a temporary
outage never wipes the registry.

Exits non-zero (so GitHub emails a failure) when something needs a human: a link it
can't read, a wishlist too big to check, or an item that hasn't been checked
successfully for STALE_HOURS. items.json is still written first, so the page stays fresh.

Standard library only, so it runs anywhere with Python 3.9+.
"""
import html
import json
import os
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
    # Poshmark's backend intermittently times out but still serves a normal-looking page
    # with an error record instead of the listing, so retry those a few times.
    for attempt in range(4):
        try:
            _, page = fetch(url)
        except NotFound:
            return {"status": "gone"}
        ld = poshmark_state_listing(page) or {}
        err = ld.get("error") or {}
        if posh_complete(ld):
            break
        if err.get("statusCode") in (404, 410):
            return {"status": "gone"}
        time.sleep(3 * (attempt + 1))
    else:
        if not err and "ldjson-schema-listing" not in page:
            raise ValueError("no listing data on page (blocked or layout changed?)")
        if err:
            raise ValueError(f"Poshmark error page: {err.get('statusCode')} {err.get('errorMessage')}")

    # Primary source: the full listing record in the page's app state. Poshmark sometimes
    # leaves out the smaller schema.org block, so that's only a fallback.
    if posh_complete(ld):
        if lid and ld["id"] != lid:
            return {"status": "gone"}  # redirected somewhere else: listing removed
        inv = ld.get("inventory") or {}
        # Multi-size listings list every size; show the ones still in stock.
        sizes = [(q.get("size_obj") or {}).get("display") for q in inv.get("size_quantities") or []
                 if q.get("quantity_available", 1) > 0]
        size = " / ".join(s for s in sizes if s) or (ld.get("size_obj") or {}).get("display") or ld.get("size")
        price = (ld.get("price_amount") or {}).get("val")
        return {
            "status": "available" if ld.get("status") == "published" and inv.get("status") == "available" else "gone",
            "title": html.unescape(ld.get("title") or title_from_slug(url)),
            "brand": html.unescape(ld.get("brand") or ""),
            "image": ld.get("picture_url"),
            "price": float(price) if price else None,
            "size": html.unescape(size) if size else None,
        }

    m = re.search(r'data-vmid="ldjson-schema-listing"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("no listing data on page (blocked or layout changed?)")
    d = json.loads(m.group(1))
    if lid and d.get("productID") != lid:
        return {"status": "gone"}
    offer = d.get("offers") or {}
    image = d.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    price = offer.get("price")
    return {
        "status": "available" if "InStock" in (offer.get("availability") or "") else "gone",
        "title": html.unescape(d.get("name") or title_from_slug(url)),
        "brand": html.unescape((d.get("brand") or {}).get("name") or ""),
        "image": image,
        "price": float(price) if price else None,
    }


def posh_complete(ld):
    """A listing record we can trust for a sold/available decision."""
    return bool(ld.get("id") and not ld.get("error") and ld.get("status")
                and (ld.get("inventory") or {}).get("status"))


def poshmark_state_listing(page):
    marker = "window.__INITIAL_STATE__="
    i = page.find(marker)
    if i < 0:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(page, i + len(marker))
    except ValueError:
        return None
    return (state.get("$_listing_details") or {}).get("listingDetails")


# ---------- thredUP ----------

THREDUP_STATUS = {"InStock": "available", "Reserved": "reserved"}
THREDUP_PAGE_SIZE = 120  # the shared-favorites page server-renders up to this many items
STALE_HOURS = 6          # complain when a shown item hasn't been checked successfully for this long


def check_thredup_wishlist(url):
    """Returns ({id: item}, complete) for the items on a shared-favorites page.

    complete is False when the wishlist has more items than the page shows, so items
    missing from this snapshot must not be treated as removed."""
    _, page = fetch(url)
    m = re.search(r'<script id="data-apollo"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("no wishlist data on page (blocked or layout changed?)")
    state = json.loads(m.group(1))
    root = state.get("ROOT_QUERY", {})
    conn = next((v for k, v in root.items() if k.startswith("sharedFavorites")), None)
    nodes = conn.get("nodes") if conn else None
    if not isinstance(nodes, list):
        raise ValueError("wishlist not found on page")
    total = conn.get("totalCount")
    complete = not (conn.get("pageInfo") or {}).get("hasNextPage")
    if complete and total is not None and total != len(nodes):
        raise ValueError(f"wishlist page shows {len(nodes)} of {total} items")
    out = {}
    for ref in nodes:
        it = state.get((ref or {}).get("__ref", ""))
        num = (it or {}).get("itemNumber")
        if not num:
            raise ValueError("wishlist item data missing from page")
        photos = it.get("photoIds") or []
        price = it.get("price")
        path = re.search(r'href="(/product/[^"]+/%s)"' % num, page)
        out[f"thredup:{num}"] = {
            "source": "thredup",
            "url": "https://www.thredup.com" + (path.group(1) if path else f"/product/{num}"),
            # Missing availability = incomplete data: keep the last known status.
            "status": THREDUP_STATUS.get(it["availability"], "gone") if it.get("availability") else None,
            "title": it.get("title") or "thredUP item",
            "brand": it.get("brand") or "",
            "image": f"https://cf-assets-thredup.thredup.com/assets/{photos[0]}/large.jpg" if photos else None,
            "price": float(price) if price else None,
            "size": it.get("sizeDisplay"),
        }
    return out, complete


# ---------- short links ----------

def known(link):
    return "thredup.com/fv/" in link or ("poshmark.com/listing/" in link and posh_id(link))


def resolve(link):
    """Follow a share link (e.g. posh.mk/...) to the Poshmark listing it points to, or None."""
    # Only trust where the link redirects to. Listing links found in the page could be
    # anything (a closet page links to dozens of other listings).
    final, _ = fetch(link)
    final = re.split(r"[?#]", final)[0]
    return final if known(final) else None


def expand_short_links(problems):
    """Replace share links in links.txt with the full listing links they point to."""
    lines = LINKS.read_text().splitlines()
    changed = False
    for n, line in enumerate(lines):
        link = line.strip()
        if not link or link.startswith("#") or known(link):
            continue
        try:
            full = resolve(link)
        except NotFound:
            full, why = None, "that page doesn't exist"
        except Exception as e:
            full, why = None, e
        else:
            why = "it doesn't lead to a Poshmark listing"
        if full:
            print(f"expanded {link} -> {full}")
            lines[n] = full
            changed = True
        else:
            problems.append(f"links.txt: can't use {link} ({why}). "
                            "Paste the full poshmark.com/listing/... link instead.")
    if changed:
        LINKS.write_text("\n".join(lines) + "\n")


# ---------- main ----------

def main():
    problems = []  # things a human needs to fix; any of these fails the run
    expand_short_links(problems)

    links = []
    for line in LINKS.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and known(line) and line not in links:
            links.append(line)

    prev = {}
    if OUT.exists():
        prev = {i["id"]: i for i in json.loads(OUT.read_text()).get("items", [])}

    ts = now()
    results = {}   # id -> fresh data (or None if the check failed)
    order = []     # ids in display order
    errors = []

    wishlists = [l for l in links if "thredup.com/fv/" in l]
    posh = [l for l in links if l not in wishlists]

    for wl in wishlists:
        try:
            found, complete = check_thredup_wishlist(wl)
            for k, v in found.items():
                v["from"] = wl
                results[k] = v
                order.append(k)
            if not complete:
                problems.append(f"thredUP wishlist has more than {THREDUP_PAGE_SIZE} items; "
                                f"only the first {THREDUP_PAGE_SIZE} are checked, so new favorites won't show up")
                for k, v in prev.items():
                    if v.get("from") == wl and k not in found:
                        results[k] = None
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
            item.setdefault("status", "unknown")
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
    # One failed check is usually a hiccup; hours of them means a site is blocking us,
    # changed its layout, or a link went bad. (The page hides these after a day.)
    cutoff = datetime.fromisoformat(ts).timestamp() - STALE_HOURS * 3600
    stale = [i for i in items if i["status"] != "gone"
             and datetime.fromisoformat(i.get("checked") or i["added"]).timestamp() < cutoff]
    if stale:
        problems.append(f"{len(stale)} item(s) haven't been checked successfully in over {STALE_HOURS} hours "
                        "(the WARN lines say why): " + " ".join(i["url"] for i in stale[:5])
                        + (" ..." if len(stale) > 5 else ""))

    for e in errors:
        print("WARN", e, file=sys.stderr)
    for p in problems:
        # ::error:: shows the message on the run's summary page on GitHub.
        print(("::error::" if os.environ.get("GITHUB_ACTIONS") else "PROBLEM: ") + p, file=sys.stderr)
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
