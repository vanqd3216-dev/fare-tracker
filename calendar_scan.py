#!/usr/bin/env python3
"""
Cloud fare CALENDAR scanner (SHARDED) — real Google Flights data, free.

Instead of scanning the whole 12-month calendar in one burst (which Google
Flights would rate-limit), this runs once an hour and each run scans only a
small ROTATING SLICE of the calendar. Over 24 hours the entire
(routes × 3 airports × 365 dates) calendar gets refreshed on a rolling basis,
at a low, steady request rate that stays under the radar.

How the shard is chosen: dates are split into CAL_SHARDS buckets (default 24)
by interleaving (date index % CAL_SHARDS). Each run handles the bucket for the
current UTC hour, so consecutive runs cover dates spread across the whole year.

Outputs (committed back to the repo):
  calendar_latest.csv — rolling calendar; each run updates only its slice's rows
  calendar_prev.csv   — snapshot taken at the start of each day (shard 0) for diffs
"""
import os, re, csv, json, time, random, datetime, urllib.parse, shutil

from fast_flights import FlightData, Passengers, get_flights

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "flight-watchlist.json")
LATEST = os.path.join(HERE, "calendar_latest.csv")
PREV = os.path.join(HERE, "calendar_prev.csv")
HEADER = ["scanned_at", "route_id", "label", "dest", "origin",
          "depart_date", "price_usd", "airline", "stops", "booking_url"]

ORIGINS = ["SFO", "OAK", "SJC"]
HORIZON_DAYS = 365
START_OFFSET = 2
SEAT = {"M": "economy", "W": "premium-economy", "C": "business", "F": "first"}

# IATA code -> airline name, used to honor a route's "only" airline filter.
CODE2NAME = {
    "ZG": "ZIPAIR", "NH": "ANA", "JL": "Japan Airlines", "MM": "Peach", "GK": "Jetstar",
    "JX": "STARLUX", "CI": "China Airlines", "BR": "EVA", "VN": "Vietnam Airlines",
    "SQ": "Singapore", "TG": "Thai", "KE": "Korean Air", "OZ": "Asiana", "CX": "Cathay",
    "UA": "United", "AA": "American", "DL": "Delta", "AS": "Alaska", "HA": "Hawaiian",
    "B6": "JetBlue", "WN": "Southwest", "F9": "Frontier", "NK": "Spirit",
    "PR": "Philippine", "VJ": "VietJet", "5J": "Cebu Pacific", "CA": "Air China",
    "MU": "China Eastern", "CZ": "China Southern", "MH": "Malaysia", "GA": "Garuda",
}


def allowed_names(route):
    codes = route.get("only") or []
    return [CODE2NAME.get(c, c) for c in codes]


def price_to_int(p):
    if not p:
        return None
    digits = re.sub(r"[^\d]", "", str(p))
    return int(digits) if digits else None


def gflights_url(origin, dest, date):
    q = f"Flights from {origin} to {dest} on {date} one way"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def scan_one(route, origin, date, seat, allowed):
    try:
        time.sleep(random.uniform(0.2, 0.6))          # pace requests
        res = get_flights(
            flight_data=[FlightData(date=date, from_airport=origin, to_airport=route["to"])],
            trip="one-way", seat=seat, passengers=Passengers(adults=1),
            fetch_mode="fallback",
        )
    except Exception:
        return None
    best = None
    for fl in getattr(res, "flights", []) or []:
        name = getattr(fl, "name", "") or ""
        if allowed and not any(a.lower() in name.lower() for a in allowed):
            continue                                   # honor route's airline filter
        price = price_to_int(getattr(fl, "price", None))
        if price is None:
            continue
        if best is None or price < best[0]:
            best = (price, name or "?", getattr(fl, "stops", "?"))
    if best is None:
        return None
    return (route["id"], origin, date,
            [route["id"], route.get("label", route["to"]), route["to"], origin,
             date, best[0], best[1], best[2], gflights_url(origin, route["to"], date)])


def load_existing():
    rows = {}
    if not os.path.exists(LATEST):
        return rows
    with open(LATEST, newline="") as f:
        for r in csv.DictReader(f):
            key = (r["route_id"], r["origin"], r["depart_date"])
            rows[key] = [r.get(h, "") for h in HEADER]
    return rows


def main():
    with open(CONFIG) as f:
        cfg = json.load(f)
    routes = cfg.get("routes", [])
    origins = cfg.get("origins", ORIGINS)
    if not routes:
        raise SystemExit("No routes configured")

    shards = int(os.environ.get("CAL_SHARDS", "24"))
    shard = int(os.environ.get("CAL_SHARD", str(datetime.datetime.utcnow().hour % shards)))

    today = datetime.date.today()
    all_dates = [(today + datetime.timedelta(days=i)).isoformat()
                 for i in range(START_OFFSET, START_OFFSET + HORIZON_DAYS)]
    dates = [d for i, d in enumerate(all_dates) if i % shards == shard]

    # daily baseline snapshot for change detection
    if shard == 0 and os.path.exists(LATEST):
        shutil.copyfile(LATEST, PREV)

    tasks = []
    for rt in routes:
        seat = SEAT.get(rt.get("cabin", ""), "economy")
        allowed = allowed_names(rt)
        for o in origins:
            for d in dates:
                tasks.append((rt, o, d, seat, allowed))
    print(f"Shard {shard}/{shards}: scanning {len(tasks)} searches "
          f"({len(routes)} routes × {len(origins)} airports × {len(dates)} dates)")

    rows = load_existing()
    scanned_at = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    priced = 0
    # modest concurrency
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(scan_one, rt, o, d, seat, allowed) for (rt, o, d, seat, allowed) in tasks]
        for fut in as_completed(futs):
            res = fut.result()
            if res:
                rid, origin, date, row = res
                rows[(rid, origin, date)] = [scanned_at] + row
                priced += 1

    out = sorted(rows.values(), key=lambda r: (r[1], r[4], r[5]))
    with open(LATEST, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(out)
    print(f"Shard {shard}: priced {priced}/{len(tasks)}; calendar now holds {len(out)} rows")


if __name__ == "__main__":
    main()
