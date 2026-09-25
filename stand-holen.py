#!/usr/bin/env python3
"""Werkzeuge zum Toto-Schein.

  python3 stand-holen.py [zieldatei]   Spielstaende von ESPN holen und als
                                       JSON-Dokument fuer den Schein-Speicher
                                       schreiben (Vorgabe: stand.json)
  python3 stand-holen.py serve [port]  Projektordner lokal ausliefern und den
                                       Schein im Browser oeffnen (Vorgabe: 8000)

Paarungen, Ligen und Spieltage stehen in spiele.json — derselben Datei, aus der
auch toto-live.html liest. Nur dort werden sie gepflegt.
"""
import http.server
import json
import os
import socketserver
import sys
import urllib.request
import webbrowser
from datetime import datetime, timezone

ORDNER = os.path.dirname(os.path.abspath(__file__))
RUNDE_DATEI = os.path.join(ORDNER, "spiele.json")


def lade_runde():
    with open(RUNDE_DATEI, encoding="utf-8") as f:
        daten = json.load(f)
    ligen = sorted({s["liga"] for s in daten["spiele"]})
    unbekannt = [l for l in ligen if l not in daten["ligen"]]
    if unbekannt:
        sys.exit(f"spiele.json: Liga-Schluessel ohne Eintrag in 'ligen': {unbekannt}")
    return daten


def scoreboard(slug, tag):
    url = ("https://site.web.api.espn.com/apis/site/v2/sports/soccer/"
           f"{slug}/scoreboard?dates={tag}")
    req = urllib.request.Request(url, headers={"User-Agent": "toto-prototyp"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def hole_stand(ziel):
    daten = lade_runde()
    gesucht = {s["id"]: s for s in daten["spiele"]}

    spiele = {}
    for liga in daten["ligen"].values():
        for tag in daten["tage"]:
            for e in scoreboard(liga["slug"], tag).get("events", []):
                if e["id"] not in gesucht:
                    continue
                c = e["competitions"][0]
                heim = next(x for x in c["competitors"] if x["homeAway"] == "home")
                gast = next(x for x in c["competitors"] if x["homeAway"] == "away")
                t = c["status"]["type"]
                spiele[e["id"]] = {
                    "state": t["state"],
                    "detail": t.get("shortDetail") or t.get("detail") or "",
                    "clock": c["status"].get("displayClock") or "",
                    "heim": int(heim.get("score") or 0),
                    "gast": int(gast.get("score") or 0),
                }

    doc = {
        "aktualisiert": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spiele": spiele,
    }
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)

    for sp in daten["spiele"]:
        name = f"{sp['nr']:2d} {sp['heim']} - {sp['gast']}"
        s = spiele.get(sp["id"])
        if not s:
            print(f"{name:36.36s} NICHT GEFUNDEN")
            continue
        ergebnis = f"{s['heim']}:{s['gast']}" if s["state"] != "pre" else "  -  "
        print(f"{name:36.36s} {s['state']:5s} {ergebnis:6s} {s['detail']}")

    gefunden = len(spiele)
    print(f"\n-> {ziel} ({gefunden}/{len(daten['spiele'])} Spiele)")
    if gefunden < len(daten["spiele"]):
        sys.exit("Nicht alle Spiele gefunden — Event-ID falsch oder Spiel verlegt.")


def serve(port):
    os.chdir(ORDNER)

    class Leise(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Leise) as srv:
        url = f"http://127.0.0.1:{port}/toto-live.html"
        print(f"Schein laeuft auf {url}   (Beenden mit Strg+C)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nbeendet")


def main():
    args = sys.argv[1:]
    if args and args[0] == "serve":
        serve(int(args[1]) if len(args) > 1 else 8000)
    else:
        hole_stand(args[0] if args else "stand.json")


if __name__ == "__main__":
    main()
