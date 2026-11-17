#!/usr/bin/env python3
"""Check your Reverb feed and push a phone alert (ntfy.sh) when a listing is at/below your max price.

Env:    REVERB_TOKEN, NTFY_TOPIC
Usage:  python3 watch.py            check feed, alert, update seen.json
        python3 watch.py --test     self-check
"""
import json, os, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SEEN = HERE / "seen.json"           # listing id -> last price alerted at
PAGES = 3                           # 50 listings/page, newest first


def load_thresholds(text):
    """'keyword = price' lines; '#' comments. Longest matching keyword wins."""
    out = {}
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if line:
            k, p = line.rsplit("=", 1)
            out[k.strip().lower()] = float(p)
    return out


def threshold_for(title, thresholds):
    t = " ".join(title.lower().split())  # collapse double spaces in titles
    hits = [k for k in thresholds if k in t]
    return thresholds[max(hits, key=len)] if hits else None


def api(path, token):
    req = urllib.request.Request("https://api.reverb.com/api/" + path, headers={
        "Authorization": f"Bearer {token}", "Accept-Version": "3.0", "Accept": "application/hal+json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def fetch_feed(token):
    out = []
    for page in range(1, PAGES + 1):
        batch = api(f"my/feed?per_page=50&page={page}", token).get("listings", [])
        out += batch
        if not batch:
            break
    return out


def deals(listings, thresholds, seen):
    for l in listings:
        limit = threshold_for(l["title"], thresholds)
        price = float(l["price"]["amount"])
        lid = str(l["id"])
        # alert once per listing, again only if it drops further
        if limit is not None and price <= limit and price < seen.get(lid, float("inf")):
            seen[lid] = price
            yield l, price, limit


def notify(topic, l, price, limit):
    drop = l.get("price_drop") or {}
    body = f"{l['price']['display']} (your max ${limit:,.0f}) · {l['condition']['display_name']}"
    if drop:
        body += f" · {drop['display']}"
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode(), headers={
        "Title": l["title"][:100].encode("ascii", "ignore").decode(),
        "Click": l["_links"]["web"]["href"],
        "Tags": "moneybag",
    })
    urllib.request.urlopen(req, timeout=30)
    print("ALERT", l["title"], body)


def main():
    token, topic = os.environ.get("REVERB_TOKEN"), os.environ.get("NTFY_TOPIC")
    if not (token and topic):
        sys.exit("set REVERB_TOKEN and NTFY_TOPIC")
    thresholds = load_thresholds((HERE / "thresholds.txt").read_text())
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    feed = fetch_feed(token)
    print(f"{len(thresholds)} thresholds, {len(seen)} already alerted, {len(feed)} listings in feed")

    rows = [(float(l["price"]["amount"]), threshold_for(l["title"], thresholds), l) for l in feed]
    matched = sorted((r for r in rows if r[1] is not None), key=lambda r: r[0] / r[1])
    print(f"\n{len(matched)} matched a threshold, {len(rows) - len(matched)} didn't. Closest to your max:")
    for price, limit, l in matched[:15]:
        print(f"  {price:>8,.0f} / {limit:>6,.0f}  ({price / limit:4.0%})  {l['title'][:60]}")
    unmatched = [l["title"][:60] for p, lim, l in rows if lim is None]
    if unmatched:
        print("\nNo threshold for:", *unmatched[:10], sep="\n  ")

    alerts = 0
    for l, price, limit in deals(feed, thresholds, seen):
        notify(topic, l, price, limit)
        alerts += 1
    print(f"\n{alerts} alert(s) sent")
    SEEN.write_text(json.dumps(seen, indent=0, sort_keys=True))


def test():
    th = load_thresholds("# c\ndigitone = 400\ndigitone ii = 800  # specific\n")
    assert th == {"digitone": 400, "digitone ii": 800}
    assert threshold_for("Elektron Digitone II black", th) == 800
    assert threshold_for("Moog Grandmother", th) is None
    mk = lambda i, t, p: {"id": i, "title": t, "price": {"amount": str(p)}}
    seen = {}
    feed = [mk(1, "Digitone", 390), mk(2, "Digitone", 450), mk(3, "Digitone II", 700), mk(4, "Moog", 1)]
    assert [l["id"] for l, *_ in deals(feed, th, seen)] == [1, 3]
    assert list(deals(feed, th, seen)) == []                                  # no repeats
    assert [l["id"] for l, *_ in deals([mk(1, "Digitone", 380)], th, seen)] == [1]  # dropped further
    print("ok")


if __name__ == "__main__":
    test() if "--test" in sys.argv else main()
