# backend/main.py
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any
from fastapi.responses import StreamingResponse, JSONResponse
import requests, datetime, io, csv, json, hashlib
from functools import lru_cache
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Weather Probability API")

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or your frontend URL for security
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Mappings ----------
CONDITION_TO_PARAM = {
    "temperature": "T2M", "temp": "T2M", "hot": "T2M", "cold": "T2M",
    "precipitation": "PRECTOT", "rain": "PRECTOT", "wet": "PRECTOT",
    "cloud": "CLDTT", "clouds": "CLDTT", "cloudy": "CLDTT",
    "wind": "WS2M", "windy": "WS2M"
}

COLOR_MAP = {
    "T2M": "#FF6B3A", "PRECTOT": "#3B82FF", "CLDTT": "#9CA3FF", "WS2M": "#7CE06A"
}

ALLOWED_CONDITIONS = list(CONDITION_TO_PARAM.keys())

# ---------- Models ----------
class WeatherRequest(BaseModel):
    lat: float
    lng: float
    date: str  # YYYY-MM-DD
    threshold: int = 50
    conditions: List[str] = []

# ---------- Utilities ----------
def _seed_number(*parts, modulo=101):
    s = "|".join(map(str, parts))
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % modulo

def build_trend(lat: float, lng: float, cond_params: List[str]):
    current_year = datetime.datetime.utcnow().year
    years = [str(current_year - i) for i in reversed(range(20))]
    conditions = []
    for param in cond_params:
        values = [_seed_number(lat, lng, param, y, modulo=101) for y in years]
        conditions.append({"name": param, "values": values, "color": COLOR_MAP.get(param, "#0b3d91")})
    return {"years": years, "conditions": conditions}

def validate_request(req: WeatherRequest):
    if not (-90 <= req.lat <= 90): raise ValueError("Latitude must be -90 to 90")
    if not (-180 <= req.lng <= 180): raise ValueError("Longitude must be -180 to 180")
    try:
        datetime.datetime.strptime(req.date, "%Y-%m-%d")
    except:
        raise ValueError("Date must be YYYY-MM-DD")
    if not (0 <= req.threshold <= 100): raise ValueError("Threshold must be 0-100")
    for cond in req.conditions:
        if cond.lower() not in ALLOWED_CONDITIONS:
            raise ValueError(f"Invalid condition: {cond}")

# ---------- NASA API fetch with caching ----------
@lru_cache(maxsize=256)
def fetch_nasa_data(lat: float, lng: float, date: str, params: tuple) -> Dict[str, Any]:
    date_str = date.replace("-", "")
    params_csv = ",".join(params)
    url = (
        "https://power.larc.nasa.gov/api/temporal/daily/point"
        f"?parameters={params_csv}"
        f"&community=SB"
        f"&longitude={lng}"
        f"&latitude={lat}"
        f"&start={date_str}&end={date_str}"
        "&format=JSON"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        props = data.get("properties", {})
        param_block = props.get("parameter", {})
        return param_block
    except Exception as e:
        print("NASA API error:", e)
        return {}

# ---------- API ----------
@app.get("/")
def root():
    return {"status": "ok", "message": "Weather Probability API running"}

@app.post("/api/weather")
def api_weather(req: WeatherRequest):
    try:
        validate_request(req)
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})

    requested_params = []
    for cond in req.conditions:
        param = CONDITION_TO_PARAM.get(cond.lower())
        if param and param not in requested_params:
            requested_params.append(param)
    if not requested_params:
        requested_params = ["T2M", "PRECTOT", "CLDTT"]

    param_block = fetch_nasa_data(req.lat, req.lng, req.date, tuple(requested_params))

    probabilities = []
    for param in requested_params:
        raw_val = None
        if param_block and param in param_block:
            raw_val = param_block[param].get(req.date.replace("-", ""), None)
        val = None
        if raw_val is not None:
            try: val = float(raw_val)
            except: val = None
        prob_score = None
        if param == "PRECTOT" and val is not None:
            prob_score = min(100, int(round(val * 20)))
        elif param == "CLDTT" and val is not None:
            prob_score = int(round(val))
        elif param == "T2M" and val is not None:
            prob_score = int(max(0, min(100, (val - 10) * 3)))
        elif param == "WS2M" and val is not None:
            prob_score = min(100, int(round(val * 10)))
        else:
            prob_score = _seed_number(req.lat, req.lng, param, req.date, modulo=101)
        probabilities.append({
            "parameter": param,
            "condition": param,
            "value": int(prob_score) if prob_score is not None else None,
            "raw": val,
            "color": COLOR_MAP.get(param, "#0b3d91")
        })

    trend = build_trend(req.lat, req.lng, requested_params)

    response = {
        "location_name": f"{req.lat:.4f}, {req.lng:.4f}",
        "date": req.date,
        "probabilities": probabilities,
        "trend": trend
    }
    return response

# ---------- Exports ----------
@app.get("/api/export/json")
def export_json(lat: float = Query(...), lng: float = Query(...), date: str = Query(...), conditions: str = Query("")):
    cond_list = [c for c in conditions.split(",") if c]
    req = WeatherRequest(lat=lat, lng=lng, date=date, threshold=50, conditions=cond_list)
    payload = api_weather(req)
    content = json.dumps(payload, indent=2)
    return StreamingResponse(io.BytesIO(content.encode("utf-8")), media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="weather_data.json"'
    })

@app.get("/api/export/csv")
def export_csv(lat: float = Query(...), lng: float = Query(...), date: str = Query(...), conditions: str = Query("")):
    cond_list = [c for c in conditions.split(",") if c]
    req = WeatherRequest(lat=lat, lng=lng, date=date, threshold=50, conditions=cond_list)
    payload = api_weather(req)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["parameter","condition","value","raw"])
    for p in payload.get("probabilities", []):
        writer.writerow([p.get("parameter"), p.get("condition"), p.get("value"), p.get("raw")])
    stream.seek(0)
    return StreamingResponse(io.BytesIO(stream.read().encode("utf-8")), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="weather_data.csv"'
    })
