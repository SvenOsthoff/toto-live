#!/usr/bin/env python3
"""Liest den offiziellen TOTO-Spielplan von WestLotto und gleicht ihn gegen ESPN ab.

Die Seite ist serverseitig gerendert — die 13 Paarungen samt Wetttendenz stehen
direkt im HTML. Eine andere Wettrunde waehlt man ueber ?jahr=YYYY&datum=YYYY-MM-DD;
ohne Parameter liefert sie die aktuelle.
"""
import difflib
import json
import re
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SPIELPLAN = ("https://www.westlotto.de/toto/ergebniswette/spielplan/"
             "toto-ergebniswette-spielplan.html")
# WestLotto verlangt eine Browser-Kennung, ESPN lehnt genau die mit 403 ab.
UA_WEB = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")
UA_ESPN = "toto-prototyp"

# Ligen, aus denen TOTO ueblicherweise schoepft.
KANDIDATEN = [
    "uefa.nations", "fifa.worldq.uefa", "fifa.friendly",
    "uefa.champions", "uefa.europa", "uefa.europa.conf",
    "ger.1", "ger.2", "ger.3", "ger.dfb_pokal",
    "eng.1", "eng.2", "eng.fa",
    "esp.1", "esp.2", "ita.1", "ita.2", "fra.1", "fra.2",
    "ned.1", "por.1", "aut.1", "sui.1", "tur.1", "bel.1", "sco.1", "den.1",
]

# Deutsche Laendernamen -> englische Schreibweise bei ESPN.
LAENDER = {
    "deutschland": "germany", "griechenland": "greece", "slowenien": "slovenia",
    "schottland": "scotland", "bulgarien": "bulgaria", "luxemburg": "luxembourg",
    "spanien": "spain", "tschechien": "czechia", "kroatien": "croatia",
    "serbien": "serbia", "niederlande": "netherlands", "daenemark": "denmark",
    "norwegen": "norway", "irland": "ireland", "nordirland": "northern ireland",
    "italien": "italy", "frankreich": "france", "belgien": "belgium",
    "schweiz": "switzerland", "oesterreich": "austria", "tuerkei": "turkiye",
    "polen": "poland", "ungarn": "hungary", "rumaenien": "romania",
    "schweden": "sweden", "finnland": "finland", "island": "iceland",
    "estland": "estonia", "lettland": "latvia", "litauen": "lithuania",
    "moldau": "moldova", "weissrussland": "belarus", "belarus": "belarus",
    "ukraine": "ukraine", "georgien": "georgia", "armenien": "armenia",
    "aserbaidschan": "azerbaijan", "kasachstan": "kazakhstan",
    "zypern": "cyprus", "malta": "malta", "albanien": "albania",
    "montenegro": "montenegro", "nordmazedonien": "north macedonia",
    "bosnien-herzegowina": "bosnia-herzegovina", "kosovo": "kosovo",
    "slowakei": "slovakia", "faeroeer": "faroe islands", "israel": "israel",
    "portugal": "portugal", "england": "england", "wales": "wales",
    "gibraltar": "gibraltar", "andorra": "andorra", "san marino": "san marino",
}

# Lesbare deutsche Liga-Namen, wo ESPNs eigene Bezeichnung englisch ist.
LIGA_NAMEN = {
    "esp.1": "1. Liga Spanien", "esp.2": "2. Liga Spanien",
    "ger.1": "Bundesliga", "ger.2": "2. Bundesliga", "ger.3": "3. Liga",
    "ger.dfb_pokal": "DFB-Pokal", "ita.1": "1. Liga Italien",
    "ita.2": "2. Liga Italien", "fra.1": "1. Liga Frankreich",
    "fra.2": "2. Liga Frankreich", "eng.1": "Premier League",
    "eng.2": "2. Liga England", "ned.1": "1. Liga Niederlande",
    "por.1": "1. Liga Portugal", "aut.1": "1. Liga Oesterreich",
    "sui.1": "1. Liga Schweiz", "bel.1": "1. Liga Belgien",
    "sco.1": "1. Liga Schottland", "den.1": "1. Liga Daenemark",
    "tur.1": "1. Liga Tuerkei",
}

# Wortbestandteile, die bei Vereinsnamen nichts zur Unterscheidung beitragen.
FUELL = {"fc", "cf", "sc", "sd", "ud", "cd", "ce", "rc", "rcd", "ac", "as", "ss",
         "afc", "bsc", "vfb", "vfl", "tsg", "fsv", "sv", "spvgg", "borussia",
         "real", "club", "de", "ii", "b", "atletico", "athletic", "deportivo"}


def _hole(url, ua=UA_WEB):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def normalisiere(name):
    n = name.lower().replace("ß", "ss")
    n = n.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = LAENDER.get(n.strip(), n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    worte = [w for w in n.split() if w and w not in FUELL]
    return " ".join(worte) if worte else n.strip()


def hole_spielplan(datum=None):
    """-> {'zeitraum': '26.09.2026 - 27.09.2026', 'tage': [...], 'spiele': [...]}"""
    url = SPIELPLAN + (f"?jahr={datum[:4]}&datum={datum}" if datum else "")
    h = _hole(url)

    m = re.search(r"SPIELPLAN VOM\s*<span>([^<]*)</span>", h)
    if not m:
        raise SystemExit("Spielplan-Kopfzeile nicht gefunden — Seitenaufbau geaendert?")
    zeitraum = m.group(1).strip()
    tage = [f"{t[6:10]}{t[3:5]}{t[0:2]}"
            for t in re.findall(r"\d{2}\.\d{2}\.\d{4}", zeitraum)]

    tbody = h.split('class="table table--toto', 1)[1]
    spiele = []
    for roh in tbody.split("<tr>")[1:]:
        nr = re.search(r'<td class="amount">(\d{1,2})</td>', roh)
        namen = re.findall(r'visible-print">([^<]+)</span>', roh)
        kurz = re.findall(r'hidden-print">([^<]+)</span>', roh)
        tendenz = re.search(r'<td class="amount">(\d+)-(\d+)-(\d+)</td>', roh)
        if not (nr and len(namen) >= 2 and tendenz):
            continue
        spiele.append({
            "nr": int(nr.group(1)),
            "heim": namen[0].strip(),
            "gast": namen[1].strip(),
            "kurz": [k.strip() for k in kurz[:2]],
            "tendenz": [int(g) for g in tendenz.groups()],
        })
    if len(spiele) != 13:
        raise SystemExit(f"{len(spiele)} statt 13 Paarungen gelesen — Seitenaufbau geaendert?")
    return {"zeitraum": zeitraum, "tage": tage, "spiele": spiele}


def hole_espn_pool(tage, ligen=KANDIDATEN):
    """Alle ESPN-Spiele der Tage aus allen Kandidatenligen einsammeln."""
    auftraege = [(l, t) for l in ligen for t in tage]

    def eines(auftrag):
        liga, tag = auftrag
        url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
               f"{liga}/scoreboard?dates={tag}")
        try:
            daten = json.loads(_hole(url, UA_ESPN))
        except Exception:
            return []
        treffer = []
        for e in daten.get("events", []):
            c = e["competitions"][0]
            try:
                heim = next(x for x in c["competitors"] if x["homeAway"] == "home")
                gast = next(x for x in c["competitors"] if x["homeAway"] == "away")
            except StopIteration:
                continue
            treffer.append({
                "id": e["id"], "liga": liga,
                "liga_name": daten.get("leagues", [{}])[0].get("name", liga),
                "anstoss": e["date"],
                "heim": heim["team"]["displayName"],
                "gast": gast["team"]["displayName"],
            })
        return treffer

    with ThreadPoolExecutor(max_workers=12) as pool:
        return [e for teil in pool.map(eines, auftraege) for e in teil]


def _aehnlich(a, b):
    return difflib.SequenceMatcher(None, normalisiere(a), normalisiere(b)).ratio()


def ordne_zu(spiel, pool, schwelle=0.60):
    """Bestes ESPN-Spiel zu einer Paarung finden. -> (treffer, guete) oder (None, guete)"""
    bester, beste = None, 0.0
    for e in pool:
        g = (_aehnlich(spiel["heim"], e["heim"]) + _aehnlich(spiel["gast"], e["gast"])) / 2
        if g > beste:
            bester, beste = e, g
    return (bester, beste) if beste >= schwelle else (None, beste)


def alter_schein(a):
    """Altes Format (Tipp je Spiel, Scheindaten unter runde) -> ein Schein.

    Nur fuer den einmaligen Uebergang; neue Dateien tragen "scheine" direkt."""
    tipps = {str(s["nr"]): s["tipp"] for s in a.get("spiele", []) if s.get("tipp")}
    r = a.get("runde", {})
    if not tipps or not r.get("los"):
        return []
    return [{"id": "s1", "los": r["los"], "quittung": r.get("quittung", ""),
             "einsatz": r.get("einsatz", ""), "reihen": [{"tipps": tipps}]}]


def schreibe_spiele_json(datum=None, ziel="spiele.json"):
    import os
    import sys

    ordner = os.path.dirname(os.path.abspath(__file__))
    ziel = ziel if os.path.isabs(ziel) else os.path.join(ordner, ziel)

    plan = hole_spielplan(datum)
    pool = hole_espn_pool(plan["tage"])
    print(f"Spielplan {plan['zeitraum']} — {len(pool)} ESPN-Spiele an diesen Tagen\n")

    # Rundendaten und Scheine nur uebernehmen, wenn es dieselbe Wettrunde ist.
    alt_runde, alt_scheine = {}, []
    if os.path.exists(ziel):
        with open(ziel, encoding="utf-8") as f:
            a = json.load(f)
        if a.get("tage") == plan["tage"]:
            alt_runde = a.get("runde", {})
            alt_scheine = a.get("scheine") or alter_schein(a)

    ligen, spiele, fehlend = {}, [], []
    for s in plan["spiele"]:
        e, guete = ordne_zu(s, pool)
        if e is None:
            fehlend.append(s)
            print(f"{s['nr']:2d}  ??  {s['heim']} : {s['gast']}  — kein ESPN-Spiel "
                  f"(beste Guete {guete:.2f})")
            continue
        schluessel = e["liga"].replace(".", "_")
        ligen[schluessel] = {"slug": e["liga"],
                             "name": LIGA_NAMEN.get(e["liga"], e["liga_name"])}
        spiele.append({
            "nr": s["nr"], "heim": s["heim"], "gast": s["gast"], "id": e["id"],
            "liga": schluessel, "anstoss": e["anstoss"], "tendenz": s["tendenz"],
        })
        warn = "  << PRUEFEN" if guete < 0.85 else ""
        print(f"{s['nr']:2d}  {guete:.2f}  {s['heim']:<15s}:{s['gast']:<15s} -> "
              f"{e['heim']:<20s}:{e['gast']:<20s} {e['id']} {e['liga']}{warn}")

    if fehlend:
        sys.exit(f"\n{len(fehlend)} Paarung(en) ohne ESPN-Spiel — Liga fehlt in "
                 f"KANDIDATEN oder die Namen weichen zu stark ab. Nichts geschrieben.")

    teile = [x.strip() for x in plan["zeitraum"].split("-")]
    if len(teile) == 2 and teile[0][2:] == teile[1][2:]:
        tage_txt = f"{teile[0][:3]}/{teile[1]}"          # 26./27.09.2026
    else:
        tage_txt = "/".join(teile)
    daten = {
        "runde": {
            "runde": alt_runde.get("runde", ""),
            "tage": "Spieltage " + tage_txt,
        },
        "ligen": ligen,
        "tage": plan["tage"],
        "spiele": spiele,
        "scheine": alt_scheine,
    }
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=1, ensure_ascii=False)
        f.write("\n")

    print(f"\n-> {ziel}  ({len(spiele)}/13 Spiele, {len(ligen)} Liga(en), "
          f"{len(alt_scheine)} Schein(e) uebernommen)")
    if not daten["runde"]["runde"]:
        print("   Rundennummer unter \"runde\" ergaenzen.")
    if not alt_scheine:
        print("   Die Scheine traegt Sven selbst in der Seite ein (\"Neuer Schein\").")


if __name__ == "__main__":
    import sys
    schreibe_spiele_json(sys.argv[1] if len(sys.argv) > 1 else None)
