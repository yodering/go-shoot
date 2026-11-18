"""Builds beys.json from the Beyblade Wiki (beyblade.fandom.com). Run: python3 scripts/fetch.py
Raw wikitext is cached in .cache/raw.json; delete it to refetch."""
import json, os, re, sys, urllib.parse, urllib.request

API = "https://beyblade.fandom.com/api.php"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache", "raw.json")


def get(**params):
    params.update(format="json", formatversion=2)
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "bey-archive-script/0.1"})
    return json.load(urllib.request.urlopen(req, timeout=60))


def fetch_raw():
    titles, cont = [], {}
    while True:
        r = get(action="query", list="embeddedin", eititle="Template:Beyblade Infobox", einamespace=0,
                eilimit=500, eifilterredir="nonredirects", **cont)
        titles += [x["title"] for x in r["query"]["embeddedin"]]
        if "continue" not in r:
            break
        cont = r["continue"]
    # /fr, /it ... are translations of the same page
    titles = [t for t in titles if not re.search(r"/[a-z]{2}$", t)]
    pages = {}
    for i in range(0, len(titles), 50):
        cont = {}
        while True:
            r = get(action="query", titles="|".join(titles[i:i + 50]), prop="revisions|pageimages", rvprop="content",
                    rvslots="main", rvsection=0, piprop="thumbnail|original", pithumbsize=400, pilimit=50, **cont)
            for p in r["query"]["pages"]:
                page = pages.setdefault(p["title"], {})
                if "revisions" in p:
                    page["text"] = p["revisions"][0]["slots"]["main"]["content"]
                if "thumbnail" in p:
                    page["thumb"], page["image"] = p["thumbnail"]["source"], p["original"]["source"]
            if "continue" not in r:
                break
            cont = r["continue"]
        print(f"\r{min(i + 50, len(titles))}/{len(titles)}", end="", file=sys.stderr)
    print(file=sys.stderr)
    return pages


def infobox(text):
    """Fields of the first {{Beyblade Infobox}}, split on top-level pipes."""
    start = text.find("{{Beyblade Infobox")
    if start < 0:
        return {}
    fields, depth, buf, i = [], 0, "", start + 2
    while i < len(text):
        two = text[i:i + 2]
        if two in ("{{", "[["):
            depth += 1; buf += two; i += 2
        elif two in ("}}", "]]"):
            if depth == 0:
                break
            depth -= 1; buf += two; i += 2
        elif text[i] == "|" and depth == 0:
            fields.append(buf); buf = ""; i += 1
        else:
            buf += text[i]; i += 1
    fields.append(buf)
    out = {}
    for f in fields[1:]:
        k, _, v = f.partition("=")
        if v.strip():
            out[k.strip()] = v.strip()
    return out


def clean(v):
    """Wikitext value -> list of plain strings (one per <br> line)."""
    v = re.sub(r"<ref.*?(/>|</ref>)", "", v, flags=re.S)
    v = re.sub(r"<!--.*?(-->|$)", "", v, flags=re.S)
    v = re.sub(r"\{\{Ruby\|([^|{}]*)\|(?:[^{}]|\{\{[^{}]*\}\})*\}\}", r"\1", v)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", v)
    v = v.replace("'''", "").replace("''", "")
    lines = [re.sub(r"<[^>]+>", "", s).strip() for s in re.split(r"<br\s*/?>|\n", v)]
    return [s for s in lines if s]


# Generations and their systems, oldest first. This is also the sidebar order.
GENS = {
    "Original": ["4 Layer System", "Spin Gear System", "Magnacore System", "Engine Gear System", "Hard Metal System"],
    "Metal": ["Metal System", "Hybrid Wheel System", "4D System", "Synchrome System", "Extreme Top System"],
    "Burst": ["Burst System", "Dual Layer System", "God Layer System", "SwitchStrike System", "Cho-Z Layer System",
              "SlingShock System", "Gatinko Layer System", "HyperSphere System", "Superking Layer System",
              "SpeedStorm System", "Dynamite Battle Layer System", "QuadDrive System", "Pro Series System"],
    "X": ["Basic Line", "Unique Line", "Custom Line"],
}
SYSTEM_GEN = {s: g for g, ss in GENS.items() for s in ss}
ALIASES = {"Magnecore": "Magnacore System", "Heavy Metal System": "Hard Metal System"}
NOT_PARTS = re.compile(r"Image|Name|AKA|ProductCode|Type|SpinDirection|Price|System|Series|Release|Owner|Appear|"
                       r"SpecialMoves|WBO|Weight$|Creator|Anime|Manga|Product|Toyline|Avatar|Classification|Element$")
LABELS = {"BladeX": "blade", "DBCore": "db core", "GTChip": "gt chip", "QSBlade": "qs blade", "BUBlade": "bu blade"}
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def date_key(s):
    """'March 28th, 2009' -> '2009-03-28'; partial dates give '2009-03' or '2009'."""
    year = re.search(r"\b(19|20)\d\d\b", s)
    if not year:
        return None
    out = year.group(0)
    month = re.search(r"\b(" + "|".join(MONTHS) + r")[a-z]*\.?(?:\s+(\d{1,2})(?!\d))?", s.lower())
    if month:
        out += f"-{MONTHS.index(month.group(1)) + 1:02d}"
        if month.group(2):
            out += f"-{int(month.group(2)):02d}"
    return out


def first(box, key):
    return (clean(box.get(key, "")) or [None])[0]


def gen_of(system, series, date):
    if system in SYSTEM_GEN:
        return SYSTEM_GEN[system]
    s = series or ""
    if "Burst" in s:
        return "Burst"
    if "Beyblade X" in s:
        return "X"
    if "Metal" in s or "Shogun" in s:
        return "Metal"
    if s:
        return "Original"
    if date:
        y = int(date[:4])
        return "Original" if y < 2008 else "Metal" if y < 2015 else "Burst" if y < 2023 else "X"
    return None


def build(raw):
    boxes = {t: infobox(p.get("text", "")) for t, p in raw.items()}
    counts = {}
    for b in boxes.values():
        for k in b:
            counts[k] = counts.get(k, 0) + 1
    beys = []
    for title, box in boxes.items():
        if not box:
            continue
        system = first(box, "System")
        system = ALIASES.get(system, system)
        release = next((first(box, k) for k in ("ReleaseJP", "ReleaseUS", "ReleaseCA", "ReleaseEU", "ReleaseAU", "ReleaseKR", "ReleaseEN") if first(box, k)), None)
        date = date_key(release) if release else None
        gen = gen_of(system, first(box, "Series"), date)
        if not gen:
            continue
        image = raw[title].get("image", "")
        m = re.search(r"/images/(.+?)/revision/", image)
        bey = {
            "name": title,
            "img": m.group(1) if m else None,
            "gen": gen,
            "system": system if system in SYSTEM_GEN else None,
            # "BB-28A (Pegasus Tornado Wing 2-Pack)" -> "BB-28A"
            "code": (re.match(r"[\w-]+", first(box, "ProductCode") or "") or [None])[0],
            "type": first(box, "Type"),
            "spin": first(box, "SpinDirection"),
            "release": release,
            "date": date,
            "weight": first(box, "Weight"),
            "jp": first(box, "JPName"),
            # keys seen under 10 times are typos or one-off notes, not parts
            "parts": [[LABELS.get(k) or re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", k).lower(), ", ".join(clean(v))]
                      for k, v in box.items() if counts[k] >= 10 and not NOT_PARTS.search(k) and clean(v)],
        }
        beys.append({k: v for k, v in bey.items() if v})
    # a third have no release date, so order by system first to keep those in their era; no system goes last in its generation
    gens, systems = list(GENS), list(SYSTEM_GEN)
    beys.sort(key=lambda b: (gens.index(b["gen"]), systems.index(b["system"]) if "system" in b else 99, b.get("date") or "9999", b["name"]))
    return beys


if __name__ == "__main__":
    if os.path.exists(CACHE):
        raw = json.load(open(CACHE))
    else:
        raw = fetch_raw()
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        json.dump(raw, open(CACHE, "w"))
    beys = build(raw)

    # self-check against two pages whose facts are well known
    by_name = {b["name"]: b for b in beys}
    peg, valk = by_name["Storm Pegasus 105RF"], by_name["Valkyrie Wing Accel"]
    assert (peg["code"], peg["type"], peg["date"], peg["gen"], peg["jp"]) == ("BB-28", "Attack", "2009-03-28", "Metal", "ストームペガシス105RF"), peg
    assert ["fusion wheel", "Storm"] in peg["parts"] and ["driver", "Accel"] in valk["parts"], (peg, valk)
    assert valk["system"] == "Burst System" and valk["img"] == "5/5c/B01ValkyrieWingAccel.jpg", valk
    assert date_key("August 2010") == "2010-08" and date_key("2004") == "2004" and date_key("TBA") is None

    json.dump({"gens": GENS, "beys": beys}, open(os.path.join(ROOT, "beys.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print(len(beys), "beys from", len(raw), "pages")
