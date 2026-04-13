"""
driving_midpoint.py
-------------------
Find the driving midpoint between any number of locations.

Strategy:
1. Geocode each address → lat/lng
2. Compute the geographic centroid (midpoint of straight-line coords)
3. Query the OpenRouteService Matrix API to find which candidate point
   minimises the *maximum* driving time from all input locations
   (i.e. the "fairest" meeting point).

Requirements:
    pip install requests python-dotenv

API key:
    Sign up free at https://openrouteservice.org/, then create a .env file
    in the same directory as this script:

        ORS_API_KEY=your_key_here

Usage:
    python driving_midpoint.py "New York, NY" "Philadelphia, PA" "Boston, MA"
"""

import os
import math
import argparse
import requests
from dotenv import load_dotenv

load_dotenv()  # loads .env from the current directory (or any parent)

# ── Configuration ────────────────────────────────────────────────────────────

ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_BASE    = "https://api.openrouteservice.org"

# How many candidate points to test around the centroid
CANDIDATE_RADIUS_KM = 10   # search radius
CANDIDATE_GRID      = 3    # creates a (2n+1)² grid  →  7×7 = 49 candidates

# ── Geocoding ────────────────────────────────────────────────────────────────

def geocode(address: str) -> tuple[float, float]:
    """Return (lat, lng) for a free-text address via ORS Geocoding."""
    url = f"{ORS_BASE}/geocode/search"
    params = {
        "api_key": ORS_API_KEY,
        "text":    address,
        "size":    1,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    features = r.json().get("features", [])
    if not features:
        raise ValueError(f"Could not geocode: {address!r}")
    lng, lat = features[0]["geometry"]["coordinates"]
    return lat, lng

# ── Centroid ─────────────────────────────────────────────────────────────────

def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """
    Compute the geographic centroid using 3-D averaging on the unit sphere,
    which handles the antimeridian and poles correctly.
    """
    x = y = z = 0.0
    for lat, lng in points:
        la, lo = math.radians(lat), math.radians(lng)
        x += math.cos(la) * math.cos(lo)
        y += math.cos(la) * math.sin(lo)
        z += math.sin(la)
    n = len(points)
    x /= n; y /= n; z /= n
    lng_c = math.degrees(math.atan2(y, x))
    hyp   = math.sqrt(x*x + y*y)
    lat_c = math.degrees(math.atan2(z, hyp))
    return lat_c, lng_c

# ── Candidate grid ───────────────────────────────────────────────────────────

def candidates_around(lat: float, lng: float,
                      radius_km: float, n: int) -> list[tuple[float, float]]:
    """Return a regular grid of (lat, lng) points centred on (lat, lng)."""
    # 1 degree latitude ≈ 111 km
    d_lat = radius_km / 111.0
    d_lng = radius_km / (111.0 * math.cos(math.radians(lat)))
    pts = []
    steps = range(-n, n + 1)
    for i in steps:
        for j in steps:
            pts.append((lat + i * d_lat / n,
                        lng + j * d_lng / n))
    return pts

# ── ORS Matrix API ───────────────────────────────────────────────────────────

def driving_durations_matrix(
    origins:      list[tuple[float, float]],
    destinations: list[tuple[float, float]],
) -> list[list[float]]:
    """
    Returns a matrix[i][j] = driving seconds from origins[i] to destinations[j].
    ORS accepts coordinates as [lng, lat].
    """
    url = f"{ORS_BASE}/v2/matrix/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type":  "application/json",
    }
    # Combine all points; sources = first len(origins) indices
    all_coords = [[lng, lat] for lat, lng in origins + destinations]
    src_idx  = list(range(len(origins)))
    dst_idx  = list(range(len(origins), len(all_coords)))
    body = {
        "locations":    all_coords,
        "sources":      src_idx,
        "destinations": dst_idx,
        "metrics":      ["duration"],
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["durations"]   # list of lists, seconds

# ── Reverse geocode ───────────────────────────────────────────────────────────

def reverse_geocode(lat: float, lng: float) -> str:
    url = f"{ORS_BASE}/geocode/reverse"
    params = {
        "api_key": ORS_API_KEY,
        "point.lat": lat,
        "point.lon": lng,
        "size": 1,
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    features = r.json().get("features", [])
    if not features:
        return f"{lat:.5f}, {lng:.5f}"
    return features[0]["properties"].get("label", f"{lat:.5f}, {lng:.5f}")

# ── Main logic ───────────────────────────────────────────────────────────────

def find_midpoint(addresses: list[str]) -> None:
    if len(addresses) < 2:
        raise ValueError("Please supply at least two addresses.")

    print("\n📍 Geocoding addresses…")
    points = []
    for addr in addresses:
        lat, lng = geocode(addr)
        print(f"   {addr!r:45s} → ({lat:.5f}, {lng:.5f})")
        points.append((lat, lng))

    c_lat, c_lng = centroid(points)
    print(f"\n🔵 Geographic centroid: ({c_lat:.5f}, {c_lng:.5f})")

    print(f"\n🔍 Building {(2*CANDIDATE_GRID+1)**2}-point candidate grid "
          f"(±{CANDIDATE_RADIUS_KM} km)…")
    candidates = candidates_around(c_lat, c_lng,
                                   CANDIDATE_RADIUS_KM, CANDIDATE_GRID)

    print("🚗 Querying driving-time matrix…")
    # origins = input addresses, destinations = candidate points
    matrix = driving_durations_matrix(points, candidates)
    # matrix[i][j] = seconds from address i to candidate j

    # For each candidate j, find the max travel time from any address
    best_idx   = None
    best_max_t = float("inf")
    best_total = float("inf")

    for j in range(len(candidates)):
        times = [matrix[i][j] for i in range(len(points))
                 if matrix[i][j] is not None]
        if len(times) < len(points):
            continue          # unreachable candidate
        max_t   = max(times)
        total_t = sum(times)
        if max_t < best_max_t or (max_t == best_max_t and total_t < best_total):
            best_max_t = max_t
            best_total = total_t
            best_idx   = j

    if best_idx is None:
        print("❌  No reachable candidate found. Try increasing CANDIDATE_RADIUS_KM.")
        return

    best_lat, best_lng = candidates[best_idx]
    label = reverse_geocode(best_lat, best_lng)

    print("\n" + "═" * 60)
    print("✅  OPTIMAL DRIVING MIDPOINT")
    print("═" * 60)
    print(f"   Address  : {label}")
    print(f"   Coords   : ({best_lat:.5f}, {best_lng:.5f})")
    print(f"   Maps link: https://maps.google.com/?q={best_lat},{best_lng}")
    print()
    print("   Travel times from each location:")
    for i, addr in enumerate(addresses):
        secs = matrix[i][best_idx]
        mins = int(secs // 60)
        print(f"     {addr!r:45s}  {mins} min")
    print(f"\n   Worst-case travel : {int(best_max_t // 60)} min")
    print(f"   Total travel time : {int(best_total // 60)} min")
    print("═" * 60)

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    global CANDIDATE_RADIUS_KM, CANDIDATE_GRID
    parser = argparse.ArgumentParser(
        description="Find the fairest driving midpoint between multiple locations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python driving_midpoint.py "New York, NY" "Philadelphia, PA" "Boston, MA"
  python driving_midpoint.py "10 Downing St, London" "Oxford, UK" "Cambridge, UK"
        """,
    )
    parser.add_argument(
        "addresses",
        nargs="+",
        help="Two or more addresses (quote each one)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=CANDIDATE_RADIUS_KM,
        help=f"Search radius in km around centroid (default: {CANDIDATE_RADIUS_KM})",
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=CANDIDATE_GRID,
        help=f"Grid density n — creates (2n+1)^2 candidates (default: {CANDIDATE_GRID})",
    )
    args = parser.parse_args()

    CANDIDATE_RADIUS_KM = args.radius
    CANDIDATE_GRID      = args.grid

    if not ORS_API_KEY:
        print("⚠️  ORS_API_KEY not found. Create a .env file in this directory:")
        print("       ORS_API_KEY=your_key_here")
        print("   Free key at: https://openrouteservice.org/\n")

    find_midpoint(args.addresses)

if __name__ == "__main__":
    main()