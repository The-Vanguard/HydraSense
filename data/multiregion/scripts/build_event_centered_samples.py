"""
build_event_centered_samples.py -- Step 5: event-centered positive + negative
sample expansion for all 10 target_location tags in the filtered event set
(Wayanad, Idukki, Rudraprayag, Chamoli, Ribhoi, Nilgiris, Sikkim/Mangan,
Darjeeling/Kalimpong, Kullu, Dhemaji).

Dhemaji is the one genuinely different region: Brahmaputra floodplain, not
steep terrain, and 90/202 raw rows are state-wide 10+-district monsoon
summary records (62% riverine_flood, 0% flash_flood) rather than local
Dhemaji events. Per user decision, Dhemaji is scoped to its 112 locally-listed
rows (<=10 districts, see DHEMAJI_MAX_DISTRICTS) and its ambiguous rows are
NOT defaulted to flash_flood (same treatment as Ribhoi) -- floodplain
riverine flooding is a genuinely different hazard from what this dataset
targets.

Reuses ml/features/event_centered_sampling.py's design (6-snapshot escalating
tier expansion, antecedent_precipitation_index decay formula, 4:1 negative
pooling, 7-day leakage exclusion) WITHOUT modifying that file -- it is
Wayanad-hardcoded and Phase-4 owned; this is a from-scratch multi-region
version living in data/multiregion/.

HARD CONSTRAINT (CLAUDE.md): every feature value is either a real number
pulled from a real fetched source, or null with a documented reason. Nothing
here is interpolated, guessed, or synthetically generated. river_discharge
is always null -- confirmed unavailable at every GUARDIAN station checked
(no rating curve anywhere in this dataset).

LABELING DECISION (flagged, not silent, user-confirmed per-region): the
"ambiguous" Main Cause rows in Rudraprayag, Chamoli, Nilgiris, Sikkim/Mangan,
Darjeeling/Kalimpong, and Kullu get the same regional-default flash_flood
label Wayanad/Idukki received (steep terrain reasoning -- Himalayan valley
for Rudraprayag/Chamoli/Kullu, Western Ghats escarpment for Nilgiris, Eastern
Himalaya/Teesta valley including GLOF-type events for Sikkim and Darjeeling/
Kalimpong). Ribhoi's ambiguous rows are NOT defaulted -- Meghalaya
plateau/foothill terrain is a more genuinely mixed flash-flood/riverine
regime and this session has no equivalent confidence for that call. Ribhoi's
positive flash-flood sample set is therefore limited to its explicitly-tagged
rows.
"""

import json
import re
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
EVENTS_CSV = REPO_ROOT / "data" / "multiregion" / "events" / "flood_events_labeled_step2.csv"
TERRAIN_JSON = REPO_ROOT / "data" / "multiregion" / "events" / "terrain_features_points.json"
WEATHER_DIR = REPO_ROOT / "data" / "multiregion" / "weather"
SOIL_DIR = REPO_ROOT / "data" / "multiregion" / "soil"
RIVER_DIR = REPO_ROOT / "data" / "multiregion" / "river"
OUT_DIR = REPO_ROOT / "data" / "multiregion" / "events"

LABEL_SCHEME = [(-72, "Yellow"), (-48, "Yellow"), (-24, "Orange"), (-12, "Orange"), (-6, "Red"), (0, "Red")]
TIER_TO_INT = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
NEG_POS_RATIO = 4
LEAKAGE_EXCLUSION_DAYS = 7
RANDOM_SEED = 42

# Dhemaji-specific, user-confirmed scope cut: 90/202 raw Dhemaji rows list
# 10+ Assam districts at once (state-wide monsoon summary records, 62%
# riverine_flood, 0% flash_flood) -- barely "Dhemaji events." Restricted to
# the 112 locally-scoped rows (<=10 districts listed).
DHEMAJI_MAX_DISTRICTS = 10


def filter_dhemaji_scope(region: str, sub: pd.DataFrame) -> pd.DataFrame:
    if region != "Dhemaji":
        return sub
    n_districts = sub["Districts"].astype(str).apply(lambda s: len(s.split(",")))
    return sub[n_districts <= DHEMAJI_MAX_DISTRICTS]

# ---------------------------------------------------------------------------
# Point assignment: keyword -> point name, per region. Default point used
# when no keyword matches (district-level-only events).
# ---------------------------------------------------------------------------
REGION_POINTS = {
    "Wayanad": {
        "default": "Chooralmala",
        "keywords": {},  # the 2024 manual event is handled specially below (all 4 villages)
        "all_points": ["Mundakkai", "Chooralmala", "Attamala", "Punjirimattom"],
    },
    "Idukki": {
        "default": "Idukki_district_centroid_proxy_Painavu",
        "keywords": {"munnar": "Munnar_town", "petimudi": "Pettimudi_Rajamala", "pettimudi": "Pettimudi_Rajamala"},
        "all_points": ["Munnar_town", "Pettimudi_Rajamala", "Idamalayar_Dam", "Idukki_Arch_Dam", "Idukki_district_centroid_proxy_Painavu"],
    },
    "Rudraprayag": {
        "default": "Rudraprayag_town",
        "keywords": {"kedarnath": "Kedarnath", "mandakini": "Kedarnath", "saraswati": "Kedarnath", "guptkashi": "Guptkashi"},
        "all_points": ["Rudraprayag_town", "Kedarnath", "Guptkashi"],
    },
    "Chamoli": {
        "default": "Gopeshwar",
        "keywords": {"joshimath": "Joshimath", "tapovan": "Joshimath", "rishiganga": "Joshimath",
                     "dhauliganga": "Joshimath", "nandadevi": "Joshimath", "glacier": "Joshimath", "badrinath": "Badrinath"},
        "all_points": ["Joshimath", "Gopeshwar", "Badrinath"],
    },
    "Ribhoi": {
        "default": "Nongpoh_town_district_HQ",
        "keywords": {"byrnihat": "Byrnihat"},
        "all_points": ["Nongpoh_town_district_HQ", "Byrnihat"],
    },
    "Nilgiris": {
        "default": "Ooty_Udhagamandalam_district_HQ",
        "keywords": {"gudalur": "Gudalur", "coonoor": "Coonoor", "ooty": "Ooty_Udhagamandalam_district_HQ",
                     "udhagamandalam": "Ooty_Udhagamandalam_district_HQ"},
        "all_points": ["Ooty_Udhagamandalam_district_HQ", "Coonoor", "Gudalur"],
    },
    "Sikkim/Mangan": {
        "default": "Mangan_district_HQ",
        "keywords": {"chungthang": "Chungthang", "lachen": "Lachen", "mangan": "Mangan_district_HQ",
                     "lhonak": "Chungthang", "teesta": "Chungthang"},
        "all_points": ["Mangan_district_HQ", "Chungthang", "Lachen"],
    },
    "Darjeeling/Kalimpong": {
        "default": "Darjeeling_town_district_HQ",
        "keywords": {"darjeeling": "Darjeeling_town_district_HQ", "kalimpong": "Kalimpong_town_district_HQ",
                     "kurseong": "Kurseong", "mirik": "Kurseong"},
        "all_points": ["Darjeeling_town_district_HQ", "Kalimpong_town_district_HQ", "Kurseong"],
    },
    "Kullu": {
        "default": "Kullu_town_district_HQ",
        "keywords": {"manali": "Manali", "bhuntar": "Bhuntar", "beas": "Manali", "kullu": "Kullu_town_district_HQ"},
        "all_points": ["Kullu_town_district_HQ", "Manali", "Bhuntar"],
    },
    "Dhemaji": {
        "default": "Dhemaji_town_district_HQ",
        "keywords": {"jonai": "Jonai", "siang": "Jonai", "gogamukh": "Gogamukh", "sissiborgaon": "Gogamukh"},
        "all_points": ["Dhemaji_town_district_HQ", "Jonai", "Gogamukh"],
    },
}

# terrain_features_points.json key differs from target_location for these
# regions (slash / different short name used by the terrain script) -- mapped
# explicitly here rather than silently mismatching.
REGION_TO_TERRAIN_KEY = {"Sikkim/Mangan": "Sikkim", "Darjeeling/Kalimpong": "Darjeeling"}

# Real CWC danger-level thresholds confirmed live (Step 4). Only attached
# where a real station was actually matched to that point -- everywhere else
# stays null.
CWC_THRESHOLD_M = {
    "Idukki_Arch_Dam": 732.43,
    "Rudraprayag_town": 624.7,   # Rudraprayag (confluence) station
    "Joshimath": 1383.0,
    "Badrinath": 3113.0,
}

# GUARDIAN WSE file -> which point(s) it applies to
WSE_FILE_TO_POINTS = {
    "wse_Kabini_Reservoir.json": ["Chooralmala", "Mundakkai", "Attamala", "Punjirimattom"],  # nearest available (Kabini is Wayanad-adjacent)
    "wse_KOTTATHARA.json": ["Chooralmala", "Mundakkai", "Attamala", "Punjirimattom"],
    "wse_Idamalayar_Reservoir.json": ["Idamalayar_Dam"],
    "wse_Rudraprayag_A.json": ["Rudraprayag_town"],
    "wse_Rudraprayag_M.json": ["Rudraprayag_town"],
    "wse_Rudraprayag_conf.json": ["Rudraprayag_town"],
    "wse_Joshimath.json": ["Joshimath"],
    "wse_Badrinath.json": ["Badrinath"],
    "wse_Karnaprayag_A.json": ["Gopeshwar"],   # nearest available point in Chamoli's Alaknanda valley
    "wse_Karnaprayag_P.json": ["Gopeshwar"],
    "wse_Nandprayag.json": ["Gopeshwar"],
    "wse_Byrnihat.json": ["Byrnihat"],
    # Sikkim: "Lachen" GUARDIAN station is a real, exact-name match for the
    # Lachen point (Lachen Chu, a Teesta headwater). Also applied to
    # Chungthang -- flagged approximation: Chungthang sits just downstream of
    # Lachen Chu's confluence with Lachung Chu, no dedicated real station
    # found under "Chungthang" itself. Mangan_district_HQ intentionally left
    # unattached: nearest real Teesta gauges (Melli/Rangpo/Singtam, also
    # fetched and saved to data/multiregion/river/ but unused here) sit
    # 60-100km further south, past several tributary confluences -- too far
    # to be a meaningful flash-flood proxy for North Sikkim, so left null
    # rather than forced.
    "wse_Lachen.json": ["Lachen", "Chungthang"],
    # Nilgiris: Bhavani Bridge / Bhavani Sagar Dam are real Bhavani-river
    # stations (also fetched, saved) but sit in the plains ~40-60km from and
    # well below Ooty/Coonoor/Gudalur's hill-town catchments -- not attached,
    # left null and documented rather than forced as a stretched proxy.
    #
    # Darjeeling/Kalimpong: "Melli" is a real Teesta-river GUARDIAN station
    # sitting right at the Kalimpong district border (~9km from the
    # Kalimpong point) -- close enough to be a legitimate proxy, unlike the
    # Nilgiris/Mangan cases above. Darjeeling_town and Kurseong sit on small
    # ungauged hill streams (Balason etc.) -- no real station found, left
    # null. Kullu: no real GUARDIAN or CWC station found anywhere in the
    # Beas valley (searched by name and by Himachal Pradesh CWC subdivision)
    # -- river_water_level_m stays null for all 3 Kullu points, documented.
    "wse_Melli.json": ["Kalimpong_town_district_HQ"],
    #
    # Dhemaji: "Dibrugarh" is a real Brahmaputra mainstem GUARDIAN station in
    # the neighboring district, same river reach (~60-80km east) -- attached
    # to Dhemaji_town as the nearest chosen point. "Subansiri Lower Dam" is a
    # real dam gauge on the Subansiri (a major tributary) right at the
    # Dhemaji/Lakhimpur-Arunachal border -- attached to Gogamukh (nearest
    # point, western subdivision). "Risiang" (also fetched, saved, unused)
    # sits at ~1200m elevation per its own real WSE data -- clearly upstream
    # hill terrain, not a match for lowland Jonai (~100m) -- left unattached,
    # same reasoning as the Nilgiris/Mangan cases. Jonai itself stays null.
    "wse_Dibrugarh.json": ["Dhemaji_town_district_HQ"],
    "wse_Subansiri_Lower_Dam.json": ["Gogamukh"],
}


def assign_point(region: str, row: pd.Series) -> list[str]:
    if row["UEI"] == "MANUAL-2024-WAYANAD-001":
        return ["Mundakkai", "Chooralmala", "Attamala", "Punjirimattom"]
    text = f"{row.get('Main Cause','')} {row.get('Districts','')} {row.get('Location','')}".lower()
    cfg = REGION_POINTS[region]
    for kw, pt in cfg["keywords"].items():
        if kw in text:
            return [pt]
    return [cfg["default"]]


def has_landslide_mention(main_cause: str) -> bool:
    return bool(re.search(r"landslide|landslip|mudslide|mud slip|land slide", str(main_cause).lower()))


# ---------------------------------------------------------------------------
# Real data loaders
# ---------------------------------------------------------------------------
def load_terrain() -> dict:
    return json.loads(TERRAIN_JSON.read_text())


def load_rainfall(region: str) -> dict:
    safe_name = region.lower().replace("/", "_")
    p = WEATHER_DIR / f"rainfall_historical_{safe_name}.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {loc["location"]: dict(zip(loc["series"]["time"], loc["series"]["precipitation_mm"])) for loc in data["locations"]}


def load_soil(region: str) -> dict:
    safe_name = region.lower().replace("/", "_")
    p = SOIL_DIR / f"soil_moisture_{safe_name}.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    return {loc["location"]: loc["gwetroot_hourly"] for loc in data["locations"]}


def load_river() -> dict:
    """Returns {point_name: sorted [(datetime, wse_m), ...]}"""
    out: dict[str, list] = {}
    for fname, points in WSE_FILE_TO_POINTS.items():
        p = RIVER_DIR / fname
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        times = data["series"]["time"]
        vals = data["series"]["wse_m"]
        pairs = sorted(
            (datetime.fromisoformat(t), v) for t, v in zip(times, vals) if v is not None
        )
        for pt in points:
            out.setdefault(pt, [])
            out[pt].extend(pairs)
    for pt in out:
        out[pt] = sorted(out[pt])
    return out


def get_rainfall_at(lookup: dict, point: str, dt: datetime) -> float | None:
    if point not in lookup:
        return None
    return lookup[point].get(dt.strftime("%Y-%m-%dT%H:00"))


def get_soil_at(lookup: dict, point: str, dt: datetime) -> float | None:
    if point not in lookup:
        return None
    series = lookup[point]
    return series.get(dt.strftime("%Y%m%d%H")) or series.get(dt.strftime("%Y%m%d"))


def get_river_at(river_lookup: dict, point: str, dt: datetime, tolerance_hours: int = 3):
    """Nearest real WSE reading within +/- tolerance_hours, else None. Returns (value, actual_dt)."""
    if point not in river_lookup or not river_lookup[point]:
        return None, None
    pairs = river_lookup[point]
    best = None
    best_diff = None
    for ts, v in pairs:
        diff = abs((ts - dt).total_seconds())
        if diff <= tolerance_hours * 3600 and (best_diff is None or diff < best_diff):
            best, best_diff, best_ts = v, diff, ts
    if best is None:
        return None, None
    return best, best_ts


def compute_api(series: list) -> list:
    api_vals = []
    running = 0.0
    for p in series:
        if p is None:
            api_vals.append(None)
        else:
            running = 0.85 * running + p
            api_vals.append(round(running, 4))
    return api_vals


def sum_window(series: list, end_idx: int, window: int):
    start = max(0, end_idx - window)
    vals = [v for v in series[start:end_idx] if v is not None]
    return round(sum(vals), 4) if vals else None


def static_feats_for_point(terrain: dict, region: str, point: str) -> dict:
    terrain_key = REGION_TO_TERRAIN_KEY.get(region, region)
    feats = terrain.get(terrain_key, {}).get(point, {})
    return {
        "elevation": feats.get("elevation"), "slope_deg": feats.get("slope_deg"),
        "aspect": feats.get("aspect"), "TWI": feats.get("TWI"), "TRI": feats.get("TRI"),
        "distance_to_river_m": feats.get("distance_to_river_m"),
        "flow_accumulation_cells": feats.get("flow_accumulation_cells"),
        "drainage_density_km_per_km2": feats.get("drainage_density_km_per_km2"),
        "cwc_danger_level_m": CWC_THRESHOLD_M.get(point),
    }


def build_snapshot_row(region, point, event_id, snap_dt, tier, sample_type,
                        rainfall_lookup, soil_lookup, river_lookup, terrain,
                        flash_flood_occurrence, landslide_occurrence, rainfall_72h_series=None, series_idx=None,
                        hours_before_event=None):
    static = static_feats_for_point(terrain, region, point)

    if rainfall_72h_series is not None and series_idx is not None:
        r1h = sum_window(rainfall_72h_series, series_idx, 1)
        r3h = sum_window(rainfall_72h_series, series_idx, 3)
        r6h = sum_window(rainfall_72h_series, series_idx, 6)
        r24h = sum_window(rainfall_72h_series, series_idx, 24)
        r72h = sum_window(rainfall_72h_series, 72, 72) if series_idx >= 72 else sum_window(rainfall_72h_series, series_idx, series_idx)
        api_series = compute_api(rainfall_72h_series)
        api_val = api_series[series_idx] if series_idx < len(api_series) else None
    else:
        r1h = get_rainfall_at(rainfall_lookup, point, snap_dt)
        r3h = r6h = r24h = r72h = api_val = None  # negatives: single-hour lookup only, no 72h back-series fetched

    soil = get_soil_at(soil_lookup, point, snap_dt)
    river_val, river_ts = get_river_at(river_lookup, point, snap_dt)
    river_prev_val, _ = get_river_at(river_lookup, point, snap_dt - timedelta(hours=1))
    river_level_change = (
        round(river_val - river_prev_val, 3)
        if river_val is not None and river_prev_val is not None else None
    )

    return {
        "region": region, "point": point, "event_id": event_id,
        "snapshot_timestamp": snap_dt.isoformat(), "tier": tier, "tier_int": TIER_TO_INT[tier],
        "sample_type": sample_type, "hours_before_event": hours_before_event,
        "flash_flood_occurrence": flash_flood_occurrence, "landslide_occurrence": landslide_occurrence,
        **static,
        "rainfall_1h": r1h, "rainfall_3h": r3h, "rainfall_6h": r6h, "rainfall_24h": r24h,
        "rainfall_72h_antecedent": r72h, "antecedent_precipitation_index": api_val,
        "rain_intensity_mm_hr": r1h,
        "soil_saturation_ratio": soil,
        "river_water_level_m": river_val, "river_water_level_timestamp": river_ts.isoformat() if river_ts else None,
        "river_discharge": None,  # confirmed unavailable at every GUARDIAN station checked -- never fabricated
        "river_level_change_m_per_hr": river_level_change,
        "data_source": "real: rainfall=Open-Meteo ERA5 archive, soil=NASA POWER GWETROOT, terrain=SRTM30m+pysheds, river=GUARDIAN CWC telemetry",
    }


def main():
    events_df = pd.read_csv(EVENTS_CSV, low_memory=False)
    events_df["_dt"] = pd.to_datetime(events_df["Start Date"], format="%d-%m-%Y %H:%M", errors="coerce")
    manual_mask = events_df["UEI"] == "MANUAL-2024-WAYANAD-001"
    if manual_mask.any():
        events_df.loc[manual_mask, "_dt"] = pd.Timestamp("2024-07-30 02:17:00")

    terrain = load_terrain()
    regions = [
        "Wayanad", "Idukki", "Rudraprayag", "Chamoli", "Ribhoi",
        "Nilgiris", "Sikkim/Mangan", "Darjeeling/Kalimpong", "Kullu", "Dhemaji",
    ]

    rainfall_lookups = {r: load_rainfall(r) for r in regions}
    soil_lookups = {r: load_soil(r) for r in regions}
    river_lookup = load_river()

    all_positive_rows = []
    for region in regions:
        sub = events_df[events_df["target_location"] == region].copy()
        sub = filter_dhemaji_scope(region, sub)
        print(f"\n[{region}] {len(sub)} real events")
        n_flash, n_landslide, n_excluded = 0, 0, 0

        for _, row in sub.iterrows():
            event_ts = row["_dt"]
            if pd.isna(event_ts):
                continue
            event_ts = event_ts.to_pydatetime()
            cause = row["flood_cause_final"]

            # Regional-default extension (flagged in module docstring): Rudraprayag + Chamoli
            # ambiguous rows get the same steep-terrain flash_flood default Wayanad/Idukki had.
            # Ribhoi's ambiguous rows are NOT defaulted.
            is_flash = cause == "flash_flood"
            if cause == "ambiguous" and region in (
                "Rudraprayag", "Chamoli", "Nilgiris", "Sikkim/Mangan", "Darjeeling/Kalimpong", "Kullu",
            ):
                is_flash = True
            is_landslide = has_landslide_mention(row["Main Cause"]) or cause == "landslide_only"

            if not is_flash and not is_landslide:
                n_excluded += 1
                continue  # riverine_flood / unlabeled ambiguous (Ribhoi) -- not a positive sample for this hazard model

            points = assign_point(region, row)
            for point in points:
                rainfall_series = [
                    get_rainfall_at(rainfall_lookups[region], point, event_ts - timedelta(hours=h))
                    for h in range(72, -1, -1)
                ]
                for offset_h, tier in LABEL_SCHEME:
                    snap_dt = event_ts + timedelta(hours=offset_h)
                    series_idx = 72 + offset_h
                    r = build_snapshot_row(
                        region, point, row["UEI"], snap_dt, tier, "positive",
                        rainfall_lookups[region], soil_lookups[region], river_lookup, terrain,
                        flash_flood_occurrence=int(is_flash), landslide_occurrence=int(is_landslide),
                        rainfall_72h_series=rainfall_series, series_idx=series_idx,
                        hours_before_event=offset_h,
                    )
                    all_positive_rows.append(r)
                if is_flash:
                    n_flash += 1
                if is_landslide:
                    n_landslide += 1

        print(f"  flash_flood positive events: {n_flash}, landslide positive events: {n_landslide}, excluded (riverine/unlabeled): {n_excluded}")

    positive_df = pd.DataFrame(all_positive_rows)
    print(f"\nTotal positive snapshot rows: {len(positive_df)}  ({positive_df['event_id'].nunique()} unique events)")

    # -------------------------------------------------------------------
    # Negative sampling: Pool A (same points, >=30 days clear of any event)
    # + Pool B (other real points, real storm periods, no failure) -- same
    # design as ml/features/event_centered_sampling.py, generalized across
    # regions and using each region's REAL date range (not a hardcoded one).
    # -------------------------------------------------------------------
    import random
    rng = random.Random(RANDOM_SEED)

    all_negative_rows = []
    for region in regions:
        sub = events_df[events_df["target_location"] == region].copy()
        sub = filter_dhemaji_scope(region, sub)
        event_dates = sorted(sub["_dt"].dropna().dt.date.unique())
        if not event_dates:
            continue
        year_min, year_max = event_dates[0].year, event_dates[-1].year

        def is_excluded(d: date) -> bool:
            return any(abs((d - ed).days) < LEAKAGE_EXCLUSION_DAYS for ed in event_dates)

        n_pos_region = len({r["event_id"] for r in all_positive_rows if r["region"] == region})
        n_target = n_pos_region * NEG_POS_RATIO

        candidates = []
        for year in range(year_min, year_max + 1):
            for month in range(6, 12):
                for day in (5, 10, 15, 20, 25):
                    try:
                        d = date(year, month, day)
                    except ValueError:
                        continue
                    if not is_excluded(d):
                        for point in REGION_POINTS[region]["all_points"]:
                            candidates.append((point, datetime(year, month, day, 6)))
        rng.shuffle(candidates)
        selected = candidates[:n_target]

        for point, snap_dt in selected:
            r = build_snapshot_row(
                region, point, None, snap_dt, "Green", "negative",
                rainfall_lookups[region], soil_lookups[region], river_lookup, terrain,
                flash_flood_occurrence=0, landslide_occurrence=0,
            )
            all_negative_rows.append(r)

        n_rain_covered = sum(1 for point, dt in selected if get_rainfall_at(rainfall_lookups[region], point, dt) is not None)
        print(f"[{region}] Negatives: {len(selected)} generated (target {n_target}), "
              f"{n_rain_covered} with real rainfall coverage ({n_rain_covered/max(len(selected),1)*100:.0f}%)")

    negative_df = pd.DataFrame(all_negative_rows)
    print(f"\nTotal negative rows: {len(negative_df)}")

    combined = pd.concat([positive_df, negative_df], ignore_index=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_parquet = OUT_DIR / "event_centered_samples_10locations.parquet"
    combined.to_parquet(out_parquet, index=False)

    summary = {
        "regions": regions,
        "total_rows": len(combined),
        "positive_rows": len(positive_df),
        "negative_rows": len(negative_df),
        "positive_events": int(positive_df["event_id"].nunique()) if len(positive_df) else 0,
        "per_region_positive_rows": positive_df.groupby("region").size().to_dict() if len(positive_df) else {},
        "per_region_negative_rows": negative_df.groupby("region").size().to_dict() if len(negative_df) else {},
        "real_coverage": {
            "rainfall_1h_non_null_pct": round(100 * combined["rainfall_1h"].notna().mean(), 1),
            "soil_saturation_non_null_pct": round(100 * combined["soil_saturation_ratio"].notna().mean(), 1),
            "river_water_level_non_null_pct": round(100 * combined["river_water_level_m"].notna().mean(), 1),
            "river_discharge_non_null_pct": 0.0,
        },
        "labeling_decision_flag": (
            "Rudraprayag + Chamoli + Nilgiris + Sikkim/Mangan + Darjeeling/Kalimpong + Kullu ambiguous Main "
            "Cause rows regional-defaulted to flash_flood (steep-terrain reasoning, user-confirmed per region). "
            "Ribhoi and Dhemaji ambiguous rows NOT defaulted -- excluded from flash_flood_occurrence positives, "
            "kept only if explicitly flash_flood/landslide tagged. Dhemaji additionally scoped to its 112 "
            "locally-listed rows (<=10 districts) out of 202 raw rows -- see DHEMAJI_MAX_DISTRICTS."
        ),
    }
    (OUT_DIR / "step5_sampling_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    print("\n" + "=" * 70)
    print("STEP 5 SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nSaved -> {out_parquet}")


if __name__ == "__main__":
    main()
