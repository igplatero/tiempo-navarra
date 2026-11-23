"""Descarga la prevision diaria de AEMET para los municipios y genera data/tiempo.json"""
import json, os, time, unicodedata, urllib.request, datetime

KEY = os.environ["AEMET_API_KEY"]
BASE = "https://opendata.aemet.es/opendata/api"
LUGARES = {
    "Pamplona": ["pamplona"], "Tudela": ["tudela"], "Estella-Lizarra": ["estella"],
    "Tafalla": ["tafalla"], "Sangüesa": ["sanguesa"], "Altsasu": ["alsasua", "altsasu"],
    "Elizondo": ["baztan"], "Bera": ["bera", "vera de bidasoa"], "Isaba": ["isaba"],
}

def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")

def get(url, intentos=4):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"api_key": KEY, "Accept": "application/json"})
            raw = urllib.request.urlopen(req, timeout=30).read()
            try: txt = raw.decode("utf-8")
            except UnicodeDecodeError: txt = raw.decode("latin-1")
            return json.loads(txt)
        except Exception as e:
            err = e
            print("  reintento", i + 1, "->", e)
            time.sleep(8 * (i + 1))
    raise err

def datos(url):
    r = get(url)
    return get(r["datos"]) if isinstance(r, dict) and "datos" in r else r

def dia(d):
    cielos = [c for c in d.get("estadoCielo", []) if c.get("value")]
    c = next((c for c in cielos if c.get("periodo") == "00-24"), cielos[0] if cielos else {})
    vs = [v for v in d.get("viento", []) if v.get("direccion") and v.get("velocidad") is not None]
    v = max(vs, key=lambda x: int(x["velocidad"])) if vs else {}
    ll = [int(p["value"]) for p in d.get("probPrecipitacion", []) if str(p.get("value", "")).strip() != ""]
    return {"fecha": d["fecha"][:10], "cielo": c.get("value", ""), "txt": c.get("descripcion", ""),
            "tmax": d["temperatura"]["maxima"], "tmin": d["temperatura"]["minima"],
            "smax": d["sensTermica"]["maxima"], "smin": d["sensTermica"]["minima"],
            "dir": v.get("direccion", ""), "vel": v.get("velocidad", 0),
            "lluvia": max(ll) if ll else 0, "uv": d.get("uvMax")}

previo = {}
if os.path.exists("data/tiempo.json"):
    try:
        with open("data/tiempo.json", encoding="utf-8") as f:
            previo = json.load(f)["lugares"]
    except Exception:
        pass

maestro = [m for m in datos(BASE + "/maestro/municipios") if m["id"].startswith("id31")]
out = {}
for nombre, alias in LUGARES.items():
    m = next((m for m in maestro if any(norm(m["nombre"]).startswith(a) for a in alias)), None)
    if not m:
        print("NO ENCONTRADO:", nombre)
        continue
    print(nombre, "->", m["nombre"], m["id"])
    try:
        p = datos(f"{BASE}/prediccion/especifica/municipio/diaria/{m['id'][2:]}")
        out[nombre] = {"aemet": m["nombre"], "dias": [dia(d) for d in p[0]["prediccion"]["dia"]]}
    except Exception as e:
        print("FALLO", nombre, "->", e)
        if nombre in previo:
            out[nombre] = previo[nombre]
            print("  se mantienen los datos anteriores de", nombre)
    time.sleep(3)

if "Pamplona" not in out:
    raise SystemExit("Sin datos de Pamplona: no se actualiza el archivo")
os.makedirs("data", exist_ok=True)
with open("data/tiempo.json", "w", encoding="utf-8") as f:
    json.dump({"actualizado": datetime.datetime.now(datetime.timezone.utc).isoformat(), "lugares": out}, f, ensure_ascii=False)
