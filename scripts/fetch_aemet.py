"""AEMET: localidades principales de Navarra (diaria + horaria), avisos y presion.
Genera data/tiempo.json."""
import json, os, io, math, time, tarfile, unicodedata, datetime, zoneinfo, urllib.request, urllib.error
import xml.etree.ElementTree as ET

KEY = os.environ.get("AEMET_API_KEY", "")
BASE = "https://opendata.aemet.es/opendata/api"
PAUSA = 1.3  # AEMET limita a 50 peticiones por minuto
MADRID = zoneinfo.ZoneInfo("Europe/Madrid")
NS = "{urn:oasis:names:tc:emergency:cap:1.2}"
MAPA = {  # nombre en el mapa -> inicios del nombre oficial (sin tildes, minusculas)
    "Pamplona": ["pamplona"], "Tudela": ["tudela"], "Estella-Lizarra": ["estella"],
    "Tafalla": ["tafalla"], "Sangüesa": ["sanguesa"], "Altsasu": ["alsasua", "altsasu"],
    "Elizondo": ["baztan"], "Bera": ["bera", "vera de bidasoa"], "Isaba": ["isaba"],
    "Leitza": ["leitza"], "Sartaguda": ["sartaguda"],
}

def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")

def num(x):
    try: return float(str(x).replace(",", "."))
    except Exception: return None

def get(url, intentos=4, raw=False):
    err = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"api_key": KEY, "Accept": "application/json"})
            b = urllib.request.urlopen(req, timeout=60).read()
            time.sleep(PAUSA)
            if raw: return b
            try: t = b.decode("utf-8")
            except UnicodeDecodeError: t = b.decode("latin-1")
            return json.loads(t)
        except urllib.error.HTTPError as e:
            err = e; print("  HTTP", e.code, url[-60:]); time.sleep(40 if e.code == 429 else 6 * (i + 1))
        except Exception as e:
            err = e; time.sleep(6 * (i + 1))
    raise err

def datos(url, raw=False, intentos=4):
    r = get(url, intentos)
    return get(r["datos"], intentos, raw) if isinstance(r, dict) and "datos" in r else r

def dia(d):
    cielos = [c for c in d.get("estadoCielo", []) if c.get("value")]
    c = next((c for c in cielos if c.get("periodo") == "00-24"), cielos[0] if cielos else {})
    vs = [v for v in d.get("viento", []) if v.get("direccion") and v.get("velocidad") is not None]
    v = max(vs, key=lambda x: int(x["velocidad"])) if vs else {}
    ll = [int(p["value"]) for p in d.get("probPrecipitacion", []) if str(p.get("value", "")).strip() != ""]
    hr = d.get("humedadRelativa") or {}
    return {"fecha": d["fecha"][:10], "cielo": c.get("value", ""), "txt": c.get("descripcion", ""),
            "tmax": d["temperatura"]["maxima"], "tmin": d["temperatura"]["minima"],
            "smax": d["sensTermica"]["maxima"], "smin": d["sensTermica"]["minima"],
            "dir": v.get("direccion", ""), "vel": v.get("velocidad", 0),
            "lluvia": max(ll) if ll else 0, "uv": d.get("uvMax"),
            "hmax": hr.get("maxima"), "hmin": hr.get("minima")}

def serie(lst):
    return {str(e["periodo"]).zfill(2)[:2]: e for e in (lst or []) if "periodo" in e and str(e.get("value", "")).strip() != ""}

def horas(p):  # [hora, cielo, temp, sensacion, humedad, viento, direccion, lluvia_mm]
    H = []
    for d in p[0]["prediccion"]["dia"]:
        f = d["fecha"][:10]
        T, C, S, R, P = (serie(d.get(k)) for k in ("temperatura", "estadoCielo", "sensTermica", "humedadRelativa", "precipitacion"))
        V = {str(e["periodo"]).zfill(2)[:2]: e for e in d.get("vientoAndRachaMax", []) if e.get("velocidad")}
        for per in sorted(T):
            v = V.get(per, {})
            H.append([f + "T" + per, C.get(per, {}).get("value", ""), num(T[per]["value"]),
                      num(S.get(per, {}).get("value")), num(R.get(per, {}).get("value")),
                      num((v.get("velocidad") or [None])[0]), (v.get("direccion") or [""])[0],
                      num(P.get(per, {}).get("value"))])
    return H

def orto(p):
    return {d["fecha"][:10]: (d.get("orto"), d.get("ocaso")) for d in p[0]["prediccion"]["dia"]}

def estaciones():
    try: obs = datos(BASE + "/observacion/convencional/todas")
    except Exception as e:
        print("Sin observaciones:", e); return []
    ult = {}
    for o in obs:
        la, lo = o.get("lat"), o.get("lon")
        if la is None or lo is None or o.get("idema") is None: continue
        if o.get("pres_nmar") is None and o.get("pres") is None: continue
        if not (41.6 <= la <= 43.6 and -3.0 <= lo <= -0.3): continue
        if o["idema"] not in ult or o.get("fint", "") > ult[o["idema"]].get("fint", ""): ult[o["idema"]] = o
    return list(ult.values())

def cercana(est, la, lo):
    try:
        k = math.cos(math.radians(la))
        o = min(est, key=lambda e: (e["lat"] - la) ** 2 + ((e["lon"] - lo) * k) ** 2)
        v = o["pres_nmar"] if o.get("pres_nmar") is not None else o["pres"]
        return [round(v), o.get("ubi", "")]
    except Exception:
        return None

def parse_cap(raw):
    try: tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:*")
    except Exception: return None
    niv = {"minor": "verde", "moderate": "amarillo", "severe": "naranja", "extreme": "rojo"}
    ahora = datetime.datetime.now(datetime.timezone.utc); res = []
    for m in tf.getmembers():
        if not m.name.lower().endswith(".xml"): continue
        r = ET.fromstring(tf.extractfile(m).read())
        for inf in r.findall(NS + "info"):
            if not (inf.findtext(NS + "language") or "").lower().startswith("es"): continue
            par = {p.findtext(NS + "valueName"): p.findtext(NS + "value") for p in inf.findall(NS + "parameter")}
            n = (par.get("AEMET-Meteoalerta nivel") or niv.get((inf.findtext(NS + "severity") or "").lower(), "")).lower()
            hasta = inf.findtext(NS + "expires") or ""
            try:
                if datetime.datetime.fromisoformat(hasta.replace("Z", "+00:00")) < ahora: continue
            except Exception: pass
            for a in inf.findall(NS + "area"):
                res.append({"f": inf.findtext(NS + "event"), "n": n, "z": a.findtext(NS + "areaDesc") or "",
                            "g": [g.findtext(NS + "value") for g in a.findall(NS + "geocode")],
                            "d": inf.findtext(NS + "onset") or inf.findtext(NS + "effective"), "h": hasta})
    return res

def avisos():
    for area in ("74", "75", "73", "76", "72"):  # el codigo de Navarra se detecta por el nombre de la zona
        try: raw = datos(f"{BASE}/avisos_cap/ultimoelaborado/area/{area}", raw=True, intentos=2)
        except Exception as e:
            print("Avisos area", area, "->", e); continue
        res = parse_cap(raw)
        if res is None: continue
        nav = [a for a in res if "avarr" in norm(a["z"]) and a["n"] in ("amarillo", "naranja", "rojo")]
        if nav or any("avarr" in norm(a["z"]) for a in res):
            print("Avisos: area", area, "->", len(nav), "activos en Navarra"); return nav
    print("Avisos: ninguno localizado"); return []

def main():
    ahora = datetime.datetime.now(MADRID)
    corte = (ahora - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H")
    try:
        with open("data/tiempo.json", encoding="utf-8") as f: previo = json.load(f)["lugares"]
    except Exception: previo = {}
    maestro = [m for m in datos(BASE + "/maestro/municipios") if m["id"].startswith("id31")]
    print(len(maestro), "municipios de Navarra en el maestro")
    ids = {}
    for nombre, alias in MAPA.items():
        m = next((m for m in maestro if any(norm(m["nombre"]).startswith(a) for a in alias)), None)
        print(nombre, "->", (m["nombre"], m["id"]) if m else "NO ENCONTRADO")
        if m: ids[nombre] = m
    est = estaciones(); print(len(est), "estaciones con presion")
    av = avisos()

    def proc(m):
        cod = m["id"][2:]; la, lo = num(m.get("latitud_dec")), num(m.get("longitud_dec"))
        p = datos(f"{BASE}/prediccion/especifica/municipio/diaria/{cod}")
        reg = {"aemet": m["nombre"], "z": m.get("zona_comarcal"), "p": cercana(est, la, lo),
               "dias": [dia(d) for d in p[0]["prediccion"]["dia"]], "h": []}
        try:
            ph = datos(f"{BASE}/prediccion/especifica/municipio/horaria/{cod}")
            o = orto(ph)
            for d in reg["dias"]: d["orto"], d["ocaso"] = o.get(d["fecha"], (None, None))
            reg["h"] = [h for h in horas(ph) if h[0] >= corte][:48]
        except Exception as e:
            print("  sin horaria", cod, e)
        return reg

    L, fallos = {}, []
    for n, m in ids.items():
        try: L[n] = proc(m)
        except Exception as e:
            print("FALLO", n, "->", e); fallos.append(n)
    for n in fallos:  # segunda pasada
        try: L[n] = proc(ids[n])
        except Exception:
            if n in previo: L[n] = previo[n]; print("Se mantienen datos anteriores de", n)
    if "Pamplona" not in L:
        raise SystemExit("Sin datos de Pamplona: no se actualiza el archivo")
    os.makedirs("data", exist_ok=True)
    iso = ahora.astimezone(datetime.timezone.utc).isoformat()
    with open("data/tiempo.json", "w", encoding="utf-8") as f:
        json.dump({"actualizado": iso, "av": av, "lugares": L}, f, ensure_ascii=False, separators=(",", ":"))
    print("Listo:", len(L), "localidades,", len(fallos), "con fallo en la primera pasada")

if __name__ == "__main__":
    main()
