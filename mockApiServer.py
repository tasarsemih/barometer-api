#!/usr/bin/env python3
"""
BAROMETER.IO — Python Mock API Server
Serves alternative economic indicator data via HTTP endpoints.

In production, replace the mock data generators below with calls to:
  - Baltic Exchange API → BDI
  - AFCO / Fibre Box Association → Cardboard Box Index
  - NPD Group / Circana → Retail indices (Lipstick, Underwear)
  - CTBUH (Council on Tall Buildings) → Skyscraper Index
  - The Economist Data API → Big Mac Index
  - BLS (Bureau of Labor Statistics) → Waitress/Waiter Index

Usage:
  pip install flask flask-cors
  python mockApiServer.py

Endpoints:
  GET /api/indicators          → All current indicator values + crisis score
  GET /api/historical?period=2008  → 2008 crisis overlay data
  GET /api/historical?period=2020  → 2020 crash overlay data
  GET /api/score               → Just the crisis score
"""

import json
import math
import random
import time
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 3001

# ============================================================
# BASE INDICATOR VALUES
# ============================================================
BASE_VALUES = {
    "bdi": {
        "current": 1243,
        "previous": 1357,
        "week_ago": 1580,
        "month_ago": 2100,
        "unit": "pts",
        "sparkline": [2100, 1980, 1850, 1760, 1650, 1540, 1480, 1380, 1300, 1243],
        "source": "Baltic Exchange (Simulated)",
        "name": "Baltic Dry Index",
        "weight": 0.30,
    },
    "cardboard": {
        "current": 88.2,
        "previous": 89.1,
        "week_ago": 91.4,
        "month_ago": 98.0,
        "unit": "idx",
        "sparkline": [98, 97, 95, 93, 92, 91, 90, 89, 88.5, 88.2],
        "source": "AFCO Production Index (Simulated)",
        "name": "Cardboard Box Index",
        "weight": 0.20,
    },
    "lipstick": {
        "current": 112.7,
        "previous": 111.2,
        "week_ago": 109.5,
        "month_ago": 100.0,
        "unit": "idx",
        "sparkline": [100, 101, 103, 104, 105, 107, 109, 110, 112, 112.7],
        "source": "Retail Analytics Panel (Simulated)",
        "name": "Lipstick Index",
        "weight": 0.10,
    },
    "underwear": {
        "current": -3.8,
        "previous": -3.1,
        "week_ago": -2.4,
        "month_ago": 1.2,
        "unit": "%yoy",
        "sparkline": [1.2, 0.8, 0.3, -0.2, -0.8, -1.5, -2.1, -2.9, -3.4, -3.8],
        "source": "NPD Group Apparel (Simulated)",
        "name": "Men's Underwear Index",
        "weight": 0.15,
    },
    "skyscraper": {
        "current": 4,
        "previous": 3,
        "week_ago": 3,
        "month_ago": 1,
        "unit": "completions",
        "sparkline": [1, 1, 2, 2, 2, 3, 3, 3, 4, 4],
        "source": "CTBUH Database (Simulated)",
        "name": "Skyscraper Index",
        "weight": 0.10,
    },
    "bigmac": {
        "current": 31,
        "previous": 29,
        "week_ago": 28,
        "month_ago": 24,
        "unit": "% overval",
        "sparkline": [24, 25, 25, 26, 27, 27, 28, 29, 30, 31],
        "source": "The Economist PPP Model (Simulated)",
        "name": "Big Mac Index",
        "weight": 0.10,
    },
    "waitress": {
        "current": 8.4,
        "previous": 8.1,
        "week_ago": 7.8,
        "month_ago": 6.2,
        "unit": "% share",
        "sparkline": [6.2, 6.4, 6.5, 6.7, 7.0, 7.3, 7.6, 7.9, 8.2, 8.4],
        "source": "BLS Current Employment Statistics (Simulated)",
        "name": "Waiter/Waitress Index",
        "weight": 0.05,
    },
}

HISTORICAL = {
    "2008": {
        "label": "2008 Global Financial Crisis",
        "period": "Jan 2007 – Dec 2008",
        "description": "The subprime mortgage crisis triggered a global meltdown. BDI collapsed 94%. Lehman Brothers filed for bankruptcy September 15, 2008.",
        "months": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
        "composite": [28, 32, 38, 45, 55, 62, 70, 80, 92, 96, 88, 72],
        "bdi": [85, 82, 78, 70, 60, 50, 38, 25, 18, 20, 28, 38],
        "cardboard": [102, 101, 99, 96, 90, 82, 72, 65, 58, 60, 66, 74],
        "lipstick": [100, 101, 103, 106, 109, 111, 114, 116, 118, 117, 115, 112],
        "underwear": [2.1, 1.8, 1.2, 0.4, -0.8, -2.1, -3.5, -4.8, -6.2, -5.9, -5.1, -4.2],
        "color": "#ff4757",
    },
    "2020": {
        "label": "2020 COVID-19 Market Crash",
        "period": "Jan 2020 – Dec 2020",
        "description": "Fastest market crash in history. S&P 500 fell 34% in 33 days. Followed by most rapid recovery ever, fueled by unprecedented fiscal stimulus.",
        "months": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],
        "composite": [28, 30, 92, 88, 72, 60, 52, 46, 44, 46, 40, 35],
        "bdi": [72, 70, 28, 32, 42, 56, 65, 72, 74, 73, 72, 70],
        "cardboard": [100, 99, 82, 76, 82, 91, 96, 99, 101, 102, 103, 104],
        "color": "#ffca28",
    },
}

# ============================================================
# CRISIS PROBABILITY ALGORITHM
# ============================================================
def calculate_stress(indicator_id, value):
    """
    Calculate stress score (0-100) for each indicator.
    Higher = more crisis risk.
    """
    stress_maps = {
        "bdi": [(2000, 10), (1500, 30), (1000, 60), (0, 85)],
        "cardboard": [(100, 10), (95, 30), (88, 55), (0, 82)],
        "lipstick": [(110, 85), (106, 60), (102, 30), (0, 10)],
        "underwear": [(2, 10), (0, 30), (-2, 60), (-100, 85)],
        "skyscraper": [(5, 82), (3, 60), (1, 30), (0, 10)],
        "bigmac": [(30, 83), (22, 60), (10, 30), (-100, 10)],
        "waitress": [(8.2, 80), (7.8, 60), (7, 30), (0, 10)],
    }

    thresholds = stress_maps.get(indicator_id, [(0, 50)])

    for threshold, stress in sorted(thresholds, reverse=True):
        if value >= threshold:
            return stress

    return thresholds[-1][1]


def calculate_crisis_score(indicator_values):
    """
    Weighted crisis probability score (0-100).
    Applies each indicator's weight from the algorithm.
    """
    weighted_sum = 0.0
    total_weight = 0.0

    for indicator_id, value in indicator_values.items():
        if indicator_id in BASE_VALUES:
            weight = BASE_VALUES[indicator_id]["weight"]
            stress = calculate_stress(indicator_id, value)
            weighted_sum += stress * weight
            total_weight += weight

    if total_weight == 0:
        return 0

    return round(weighted_sum / total_weight)


def get_risk_level(score):
    if score < 25:
        return {"label": "LOW RISK", "color": "#00d4aa"}
    elif score < 50:
        return {"label": "MODERATE RISK", "color": "#ffca28"}
    elif score < 75:
        return {"label": "HIGH RISK", "color": "#ff7043"}
    else:
        return {"label": "CRITICAL RISK", "color": "#ff4757"}


def get_oracle_assessment(score, bearish_count):
    if score >= 80:
        return {
            "headline": "Critical Systemic Stress — Crisis Conditions Present",
            "sub": f"{bearish_count} of 7 indicators at critical levels. Pattern matches pre-2008 conditions with 78% fidelity.",
        }
    elif score >= 65:
        return {
            "headline": "Elevated Systemic Stress Detected",
            "sub": f"{bearish_count} of 7 indicators flashing cautionary signals. Pattern similarity to pre-2008: 61%.",
        }
    elif score >= 45:
        return {
            "headline": "Moderate Stress — Caution Warranted",
            "sub": f"Mixed signals. {bearish_count} bearish readings. No immediate crisis pattern, but deterioration trend noted.",
        }
    else:
        return {
            "headline": "Low-Moderate Stress — Monitor Outliers",
            "sub": f"Most indicators within normal ranges. {bearish_count} early warning signals present.",
        }


def generate_live_data():
    """Generate current indicator values with micro-variation for realism."""
    live = {}
    values = {}

    for key, base in BASE_VALUES.items():
        variation = random.uniform(-0.003, 0.003)
        current = round(base["current"] * (1 + variation), 2)
        stress = calculate_stress(key, current)
        change_day = round((current - base["previous"]) / abs(base["previous"] or 1) * 100, 2)
        change_week = round((current - base["week_ago"]) / abs(base["week_ago"] or 1) * 100, 2)
        change_month = round((current - base["month_ago"]) / abs(base["month_ago"] or 1) * 100, 2)

        live[key] = {
            **base,
            "current": current,
            "stress": stress,
            "change_day": change_day,
            "change_week": change_week,
            "change_month": change_month,
            "last_updated": datetime.utcnow().isoformat() + "Z",
        }
        values[key] = current

    return live, values


# ============================================================
# HTTP SERVER
# ============================================================
class BarometerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/indicators":
            live_data, values = generate_live_data()
            crisis_score = calculate_crisis_score(values)
            risk = get_risk_level(crisis_score)
            bearish = sum(1 for k, v in live_data.items() if v["stress"] > 65)
            assessment = get_oracle_assessment(crisis_score, bearish)

            self.send_json({
                "success": True,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "crisis_score": crisis_score,
                "risk_level": risk,
                "assessment": assessment,
                "indicators": live_data,
                "meta": {
                    "data_type": "simulated",
                    "refresh_interval_ms": 30000,
                    "version": "2.4.1",
                    "algorithm": {
                        "description": "Weighted stress composite of 7 alternative economic indicators",
                        "weights": {k: v["weight"] for k, v in BASE_VALUES.items()},
                    },
                },
            })

        elif path == "/api/score":
            _, values = generate_live_data()
            score = calculate_crisis_score(values)
            risk = get_risk_level(score)
            self.send_json({"score": score, "risk": risk, "timestamp": datetime.utcnow().isoformat() + "Z"})

        elif path == "/api/historical":
            period = params.get("period", [None])[0]
            if not period or period not in HISTORICAL:
                self.send_json({"error": f"Invalid period. Use: 2008 or 2020"}, status=400)
                return
            self.send_json({"success": True, "period": period, "data": HISTORICAL[period]})

        elif path == "/api/health":
            self.send_json({"status": "ok", "uptime": time.time(), "version": "2.4.1"})

        elif path == "/" or path == "/api":
            self.send_json({
                "name": "BAROMETER.IO API",
                "version": "2.4.1",
                "endpoints": {
                    "GET /api/indicators": "All current indicator values + crisis score",
                    "GET /api/score": "Crisis score only",
                    "GET /api/historical?period=2008": "2008 crisis overlay",
                    "GET /api/historical?period=2020": "2020 crash overlay",
                    "GET /api/health": "Server health check",
                },
            })

        else:
            self.send_json({"error": "Not found"}, status=404)


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════╗
║         BAROMETER.IO — Python API Server     ║
║         Alternative Economic Indicators      ║
╠══════════════════════════════════════════════╣
║  Running at: http://localhost:{PORT}            ║
║                                              ║
║  Endpoints:                                  ║
║  GET /api/indicators  → All live data        ║
║  GET /api/score       → Crisis score         ║
║  GET /api/historical  → Historical overlays  ║
║  GET /api/health      → Health check         ║
╚══════════════════════════════════════════════╝
    """)

    server = HTTPServer(("localhost", PORT), BarometerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()
