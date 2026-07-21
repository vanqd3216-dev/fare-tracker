#!/usr/bin/env python3
"""
Bay Area cloud fare tracker  —  real Google Flights data, free.

Runs on GitHub Actions (hourly). Reads flight-watchlist.json, queries Google
Flights via the free `fast-flights` library for each route from each origin,
keeps the cheapest, appends to fares_log.csv, and emails on price drops /
target hits.

Data source: fast-flights (reads Google Flights' internal feed; no API key).

Optional env vars (set as GitHub repo Secrets) for email alerts:
  EMAIL_USER  - Gmail address to send FROM
  EMAIL_PASS  - Gmail App Password (not your normal password)
  EMAIL_TO    - address to send alerts TO (defaults to EMAIL_USER)
If the email secrets are absent the tracker still logs prices; it just won't email.
"""
import os, re, csv, json, sys, smtplib, datetime, urllib.parse
from email.mime.text import MIMEText

from fast_flights import FlightData, Passengers, get_flights

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "flight-watchlist.json")
LOG = os.path.join(HERE, "fares_log.csv")
HEADER = ["timestamp_iso", "route_id", "label", "origin", "dest",
          "price_usd", "airline", "stops", "depart_date", "booking_url"]

SEAT = {"M": "economy", "W": "premium-economy", "C": "business", "F": "first"}


def price_to_int(p):
    """'$224' / '224 US dollars' -> 224 ; unavailable -> None."""
    if not p:
        return None
    digits = re.sub(r"[^\d]", "", str(p))
    return int(digits) if digits else None


def gflights_url(origin, dest, date):
    q = f"Flights from {origin} to {dest} on {date} one way"
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def cheapest_for(origin, dest, date, seat):
    """Return (price_int, airline, stops, url) for the cheapest one-way, or None."""
    try:
        res = get_flights(
            flight_data=[FlightData(date=date, from_airport=origin, to_airport=dest)],
            trip="one-way",
            seat=seat,
            passengers=Passengers(adults=1),
            fetch_mode="fallback",
        )
    except Exception as e:
        print(f"  ! {origin}->{dest} lookup failed: {e}")
        return None
    best = None
    for fl in getattr(res, "flights", []) or []:
        price = price_to_int(getattr(fl, "price", None))
        if price is None:
            continue
        if best is None or price < best[0]:
            best = (price, getattr(fl, "name", "?"), getattr(fl, "stops", "?"),
                    gflights_url(origin, dest, date))
    return best


def last_prices():
    out = {}
    if not os.path.exists(LOG):
        return out
    with open(LOG, newline="") as f:
        for row in csv.DictReader(f):
            try:
                out[row["route_id"]] = float(row["price_usd"])
            except (ValueError, KeyError):
                pass
    return out


def send_email(subject, body):
    user, pw = os.environ.get("EMAIL_USER"), os.environ.get("EMAIL_PASS")
    to = os.environ.get("EMAIL_TO") or user
    if not (user and pw and to):
        print("  (email not configured — skipping send)")
        return
    msg = MIMEText(body)
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        print(f"  email sent to {to}")
    except Exception as e:
        print(f"  ! email failed: {e}")


def main():
    with open(CONFIG) as f:
        cfg = json.load(f)
    origins = cfg.get("origins", ["SFO"])
    depart = cfg.get("departureDate", "")
    drop_pct = float(cfg.get("alertOnDropPct", 10))
    routes = cfg.get("routes", [])
    if not routes:
        sys.exit("No routes configured")

    prev = last_prices()
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    new_header = not os.path.exists(LOG)
    alerts, summary = [], []

    with open(LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new_header:
            w.writerow(HEADER)
        for rt in routes:
            dest, label = rt["to"], rt.get("label", rt["to"])
            date = rt.get("date") or depart
            seat = SEAT.get(rt.get("cabin", ""), "economy")
            best = None
            for o in origins:
                res = cheapest_for(o, dest, date, seat)
                if res and (best is None or res[0] < best[0]):
                    best = (res[0], o, res[1], res[2], res[3])
            if best is None:
                print(f"  {label}: no result")
                continue
            price, origin, airline, stops, url = best
            w.writerow([now, rt["id"], label, origin, dest, price, airline, stops, date, url])
            summary.append(f"{label} ${price}")

            old = prev.get(rt["id"])
            target = rt.get("target")
            if target is not None and price <= float(target):
                alerts.append(f"TARGET HIT: {label} ${price} <= target ${int(target)} "
                              f"from {origin}. {url}")
            elif old is not None and price <= old * (1 - drop_pct / 100.0):
                pct = round((1 - price / old) * 100)
                alerts.append(f"PRICE DROP: {label} ${price} from {origin} "
                              f"(was ${int(round(old))}, -{pct}%). {url}")

    print("Summary:", " | ".join(summary) if summary else "no data")
    if alerts:
        body = "\n".join(alerts) + "\n\nAll routes this run:\n" + "\n".join(summary)
        send_email("Bay Area fare alert", body)
        for a in alerts:
            print("ALERT:", a)
    else:
        print("No alerts this run.")


if __name__ == "__main__":
    main()
