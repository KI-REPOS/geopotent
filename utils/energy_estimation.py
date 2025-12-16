"""
Robust energy estimation utilities.

- Fetches hourly weather from Open-Meteo Archive API (hourly: shortwave_radiation, wind_speed_10m)
- Converts irradiance (W/m²) to kWh and computes PV energy per hour
- Computes wind turbine power per hour using rotor diameter and simple power equation
- Produces JSON-safe results including base64 plots
"""

import math
import json
import logging
import base64
import io
from datetime import datetime
from typing import Dict, Any, List
from .soil_analysis import estimate_agri_revenue

import requests
import requests_cache
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # ✅ Non-GUI backend (avoids Tkinter errors in Django)
import matplotlib.pyplot as plt

# -------------------- Logging --------------------
logger = logging.getLogger(__name__)

# -------------------- Helpers --------------------
def plot_to_base64(fig) -> str:
    """Convert matplotlib figure to a data-uri PNG (base64)."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    data = base64.b64encode(buf.read()).decode("utf-8")
    buf.close()
    plt.close(fig)
    return f"data:image/png;base64,{data}"

def convert_numpy_types(obj):
    """Recursively convert numpy / pandas / datetime to Python native types for JSON."""
    if isinstance(obj, dict):
        return {k: convert_numpy_types(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_numpy_types(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return str(obj)
    if isinstance(obj, pd.Series):
        return convert_numpy_types(obj.to_list())
    if pd.isna(obj):
        return None
    return obj

def safe_json(obj):
    """Return JSON-safe object (no numpy, datetimes, NaN)."""
    clean = convert_numpy_types(obj)
    return json.loads(json.dumps(clean, allow_nan=False))

# -------------------- Weather Fetch --------------------
def fetch_hourly_weather(lat: float, lon: float, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch hourly weather from Open-Meteo archive API.

    Returns DataFrame with columns:
      - time (datetime UTC)
      - shortwave_radiation (W/m²)
      - wind_speed_10m (m/s)
      - temperature_2m (°C) if available
    """
    try:
        start = pd.to_datetime(start_date).date().isoformat()
        end = pd.to_datetime(end_date).date().isoformat()

        params = {
            "latitude": float(lat),
            "longitude": float(lon),
            "start_date": start,
            "end_date": end,
            "hourly": "shortwave_radiation,wind_speed_10m,temperature_2m",
            "timezone": "UTC",
        }

        session = requests_cache.CachedSession(".openmeteo_cache", expire_after=3600)
        resp = session.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=30)

        if resp.status_code != 200:
            logger.error("Open-Meteo HTTP %s: %s", resp.status_code, resp.text[:200])
            return pd.DataFrame()

        payload = resp.json()
        if "hourly" not in payload or not payload["hourly"]:
            logger.warning("Open-Meteo returned no hourly payload for %s - %s", start, end)
            return pd.DataFrame()

        hourly = payload["hourly"]
        times = pd.to_datetime(hourly.get("time", []), utc=True)
        sr = np.array(hourly.get("shortwave_radiation", []), dtype=float)  # W/m²
        ws = np.array(hourly.get("wind_speed_10m", []), dtype=float)
        temp = np.array(hourly.get("temperature_2m", []), dtype=float) if "temperature_2m" in hourly else None

        df = pd.DataFrame({"time": times})
        df["shortwave_radiation"] = pd.Series(sr)
        df["wind_speed_10m"] = pd.Series(ws)
        if temp is not None and len(temp) == len(df):
            df["temperature_2m"] = pd.Series(temp)

        df = df.dropna(subset=["shortwave_radiation", "wind_speed_10m"], how="all").reset_index(drop=True)
        logger.debug("Fetched weather rows=%s from %s to %s (lat=%s lon=%s)", len(df), start, end, lat, lon)
        return df

    except Exception as e:
        logger.exception("fetch_hourly_weather failed: %s", e)
        return pd.DataFrame()

# -------------------- Energy Models --------------------
def pv_energy_model_from_hourly(irradiance_wm2_series: pd.Series, area_m2: float, pv_cfg: Dict[str, Any]) -> pd.Series:
    """Compute hourly PV energy (kWh) from irradiance series (W/m²)."""
    if irradiance_wm2_series is None or irradiance_wm2_series.empty or area_m2 <= 0:
        return pd.Series(0.0, index=irradiance_wm2_series.index if irradiance_wm2_series is not None else pd.RangeIndex(0))

    eff = float(pv_cfg.get("efficiency", 0.18))
    pr = float(pv_cfg.get("performance_ratio", 0.75))
    sys_eff = float(pv_cfg.get("system_efficiency", 0.95))
    land_cov = float(pv_cfg.get("land_coverage", 1.0))

    pv_area = float(area_m2) * land_cov
    kwh_per_m2 = irradiance_wm2_series.astype(float) / 1000.0  # convert W/m² → kWh/m² (per hour)
    energy_kwh = kwh_per_m2 * pv_area * eff * pr * sys_eff

    return energy_kwh.fillna(0.0)

def wind_energy_model_from_hourly(ws_series: pd.Series, wind_cfg: Dict[str, Any]) -> pd.Series:
    """Compute hourly wind turbine energy (kWh) from wind speed series (m/s)."""
    if ws_series is None or ws_series.empty:
        return pd.Series(0.0, index=ws_series.index if ws_series is not None else pd.RangeIndex(0))

    rho = 1.225
    rotor_diameter = float(wind_cfg.get("rotor_diameter_m", 0.0))
    rated_power_kw = float(wind_cfg.get("rated_power_kw", 0.0))
    cut_in = float(wind_cfg.get("cut_in_ms", 3.0))
    rated_ws = float(wind_cfg.get("rated_ws_ms", 12.0))
    cut_out = float(wind_cfg.get("cut_out_ms", 25.0))
    cp = float(wind_cfg.get("cp", 0.35))
    sys_eff = float(wind_cfg.get("system_efficiency", 0.95))

    if rotor_diameter <= 0 or rated_power_kw <= 0:
        return pd.Series(0.0, index=ws_series.index)

    A = math.pi * (rotor_diameter / 2.0) ** 2
    v = ws_series.astype(float)

    power_w = 0.5 * rho * A * (v ** 3) * cp * sys_eff
    rated_power_w = rated_power_kw * 1000.0

    power_w = np.where(v < cut_in, 0.0, power_w)
    power_w = np.where(v > cut_out, 0.0, power_w)
    power_w = np.where((v >= rated_ws) & (v <= cut_out), np.minimum(power_w, rated_power_w), power_w)
    power_w = np.where(power_w < 0, 0.0, power_w)

    return pd.Series(power_w / 1000.0, index=ws_series.index).fillna(0.0)

# -------------------- Main Estimation --------------------
def estimate_energy_potential(
    lat: float,
    lon: float,
    start_date: str,
    end_date: str,
    area_m2: float,
    pv_config: Dict[str, Any],
    wind_config: Dict[str, Any],
    dc_voltage: float = 48.0,
) -> Dict[str, Any]:
    """Top-level function called by views.py. Returns a JSON-safe dict."""
    try:
        area_m2 = float(area_m2) if area_m2 is not None else 0.0
    except Exception:
        area_m2 = 0.0

    df = fetch_hourly_weather(lat, lon, start_date, end_date)
    if df.empty:
        return {
            "total_energy_kwh": 0.0,
            "pv_energy_kwh": 0.0,
            "wind_energy_kwh": 0.0,
            "total_revenue": 0.0,
            "monthly_breakdown": [],
            "hourly_plot": "",
            "daily_plot": "",
            "config": {"pv": pv_config, "wind": wind_config, "dc_voltage": dc_voltage},
        }

    # Compute PV + Wind
    df["pv_energy_kwh"] = pv_energy_model_from_hourly(df["shortwave_radiation"], area_m2, pv_config)
    df["wind_energy_kwh"] = wind_energy_model_from_hourly(df["wind_speed_10m"], wind_config)
    df["total_energy_kwh"] = df["pv_energy_kwh"] + df["wind_energy_kwh"]

    total_pv = float(df["pv_energy_kwh"].sum())
    total_wind = float(df["wind_energy_kwh"].sum())
    total_energy = float(df["total_energy_kwh"].sum())
    price_per_kwh = float(pv_config.get("price_per_kwh", 6.0))
    revenue = total_energy * price_per_kwh

    # --- Hourly plot
    try:
        fig1, ax1 = plt.subplots(figsize=(10, 4))
        ax1.plot(df["time"], df["pv_energy_kwh"], label="PV (kWh/hour)")
        ax1.plot(df["time"], df["wind_energy_kwh"], label="Wind (kWh/hour)", alpha=0.8)
        ax1.set_title("Hourly Energy (kWh)")
        ax1.set_ylabel("kWh")
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        hourly_plot = plot_to_base64(fig1)
    except Exception:
        logger.exception("Failed to create hourly plot")
        hourly_plot = ""

    # --- Daily plot
    try:
        df["date_local"] = pd.to_datetime(df["time"]).dt.date
        daily = df.groupby("date_local", as_index=False).agg({
            "pv_energy_kwh": "sum",
            "wind_energy_kwh": "sum",
            "total_energy_kwh": "sum"
        })
        fig2, ax2 = plt.subplots(figsize=(10, 4))
        ax2.plot(pd.to_datetime(daily["date_local"]), daily["pv_energy_kwh"], label="PV (kWh/day)")
        ax2.plot(pd.to_datetime(daily["date_local"]), daily["wind_energy_kwh"], label="Wind (kWh/day)", alpha=0.8)
        ax2.set_title("Daily Energy (kWh/day)")
        ax2.set_ylabel("kWh/day")
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        daily_plot = plot_to_base64(fig2)
    except Exception:
        logger.exception("Failed to create daily plot")
        daily_plot = ""

    # --- Monthly breakdown
    df["month"] = pd.to_datetime(df["time"]).dt.to_period("M")
    monthly = df.groupby("month").agg({
        "pv_energy_kwh": "sum",
        "wind_energy_kwh": "sum",
        "total_energy_kwh": "sum"
    }).reset_index()

    monthly["revenue_inr"] = monthly["total_energy_kwh"] * price_per_kwh
    monthly["month"] = monthly["month"].astype(str)  # <-- fix blank issue
    monthly_breakdown = monthly.to_dict(orient="records")

    results = {
        "total_energy_kwh": total_energy,
        "pv_energy_kwh": total_pv,
        "wind_energy_kwh": total_wind,
        "total_revenue": revenue,
        "monthly_breakdown": monthly_breakdown,
        "hourly_plot": hourly_plot,
        "daily_plot": daily_plot,
        "config": {"pv": pv_config, "wind": wind_config, "dc_voltage": dc_voltage},
    }

    # --- Mixed Analysis & Optimization ---
    # 1. Solar Only
    revenue_solar_only = revenue
    
    # 2. Wind Only (Assumes full land available for wind spacing, but actual footprint is small)
    # Wind revenue is already part of 'revenue' if both are enabled, but let's separate them.
    revenue_wind_only = total_wind * price_per_kwh
    
    # 3. Agriculture Only
    area_ha = area_m2 / 10000.0
    # We need crop recommendations passed in or we fetch them? 
    # Ideally, views.py passes them, but here we might need to re-fetch or just return a structure 
    # that views.py populates.
    # For now, let's assume we return the raw energy data and views.py handles the mixing 
    # OR we accept crop_revenue as an argument.
    # Let's change the signature to accept optional crop_revenue_data
    
    results = {
        "total_energy_kwh": total_energy,
        "pv_energy_kwh": total_pv,
        "wind_energy_kwh": total_wind,
        "total_revenue": revenue,
        "monthly_breakdown": monthly_breakdown,
        "hourly_plot": hourly_plot,
        "daily_plot": daily_plot,
        "config": {"pv": pv_config, "wind": wind_config, "dc_voltage": dc_voltage},
    }

    return safe_json(results)

def calculate_mixed_potential(energy_results: Dict, crop_results: Dict, area_ha: float) -> Dict:
    """
    Calculate and compare different land-use mixes.
    """
    price_per_kwh = 6.0 # INR
    
    # Base values
    solar_kwh = energy_results.get("pv_energy_kwh", 0)
    wind_kwh = energy_results.get("wind_energy_kwh", 0)
    agri_revenue = crop_results.get("max_revenue", 0)
    best_crop = crop_results.get("best_crop", "Unknown")

    solar_revenue = solar_kwh * price_per_kwh
    wind_revenue = wind_kwh * price_per_kwh

    # Scenarios
    scenarios = []

    # 1. Solar Only
    scenarios.append({
        "name": "Solar Only",
        "revenue": solar_revenue,
        "details": "Full area used for Solar PV."
    })

    # 2. Wind Only
    scenarios.append({
        "name": "Wind Only",
        "revenue": wind_revenue,
        "details": "Full area used for Wind Turbines."
    })

    # 3. Agriculture Only
    scenarios.append({
        "name": f"Agriculture Only ({best_crop})",
        "revenue": agri_revenue,
        "details": f"Full area cultivated with {best_crop}."
    })

    # 4. Solar + Wind (Hybrid)
    # Assumption: Wind turbines take ~5% space, Solar takes rest? 
    # Or they coexist. Usually Wind spacing is large. 
    # Let's assume Solar takes 95% area, Wind takes 100% effectiveness (height).
    # But shading might be an issue. Let's assume 90% Solar, 100% Wind.
    s_w_revenue = (solar_revenue * 0.9) + wind_revenue
    scenarios.append({
        "name": "Solar + Wind",
        "revenue": s_w_revenue,
        "details": "Wind turbines with Solar PV filling the spacing (90% Solar capacity)."
    })

    # 5. Solar + Agri (Agrivoltaics)
    # Assumption: Solar panels spaced/elevated. 
    # Solar density: 60%, Agri yield: 70%.
    s_a_revenue = (solar_revenue * 0.6) + (agri_revenue * 0.7)
    scenarios.append({
        "name": f"Agrivoltaics (Solar + {best_crop})",
        "revenue": s_a_revenue,
        "details": "Elevated/Spaced Solar panels allowing cultivation (60% Solar, 70% Agri yield)."
    })

    # 6. Wind + Agri
    # Wind footprint is small (~5%). Agri yield ~95%.
    w_a_revenue = wind_revenue + (agri_revenue * 0.95)
    scenarios.append({
        "name": f"Wind + Agriculture ({best_crop})",
        "revenue": w_a_revenue,
        "details": "Wind turbines with cultivation in between (95% Agri yield)."
    })

    # 7. All Three
    # Solar (Agrivoltaics config) + Wind.
    # Solar: 60%, Agri: 65% (more shading/poles), Wind: 100%.
    all_revenue = (solar_revenue * 0.6) + (agri_revenue * 0.65) + wind_revenue
    scenarios.append({
        "name": "Mixed (Solar + Wind + Agri)",
        "revenue": all_revenue,
        "details": "Integrated system: Wind turbines, spaced Solar, and crops."
    })

    # Find best
    best_scenario = max(scenarios, key=lambda x: x["revenue"])

    return {
        "scenarios": scenarios,
        "best_scenario": best_scenario
    }
