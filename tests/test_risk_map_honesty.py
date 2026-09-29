"""tests/test_risk_map_honesty.py -- /risk/map data comes only from real stored scores.

Regression tests for the removed "mock distribution": earlier, every region except Wayanad returned
hash-derived risk scores, forced Orange/Red hexes, a fake 180-minute lead time and fake sensors.
"""
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import h3
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import repository, risk_engine  # noqa: E402

NOW = datetime.now(timezone.utc)
HEX_RIB1 = h3.latlng_to_cell(25.90, 91.90, 8)
HEX_RIB2 = h3.latlng_to_cell(25.95, 91.95, 8)
HEX_RIB_UNSCORED = h3.latlng_to_cell(25.85, 91.85, 8)
HEX_WY = h3.latlng_to_cell(11.51, 76.05, 8)
HEX_IDK = h3.latlng_to_cell(9.98, 76.95, 8)


@pytest.fixture()
def db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE hexes (hex_id TEXT PRIMARY KEY, geom TEXT, static_features TEXT, region_code TEXT, resolution INT);
        CREATE TABLE risk_scores (id INTEGER PRIMARY KEY AUTOINCREMENT, hex_id TEXT, timestamp TEXT, risk_score REAL,
            tier TEXT, confidence_score REAL, lead_time_min INT, lead_time_basis TEXT, feature_contributions TEXT,
            data_source TEXT, provenance TEXT, sensor_adjusted INT);
    """)
    for hid, reg, feats in [(HEX_RIB1, "ribhoi-ml", {"has_local_calibration": True}), (HEX_RIB2, "ribhoi-ml", {}),
                            (HEX_RIB_UNSCORED, "ribhoi-ml", {}), (HEX_WY, "", {}), (HEX_IDK, "idukki-kl", {})]:
        conn.execute("INSERT INTO hexes VALUES (?,?,?,?,8)", (hid, "{}", json.dumps(feats), reg))

    def add(hid, score, tier, conf, age_h=0.1, sensor=0, source="open_meteo_live", lead=None):
        ts = (NOW - timedelta(hours=age_h)).isoformat()
        conn.execute("INSERT INTO risk_scores (hex_id,timestamp,risk_score,tier,confidence_score,lead_time_min,"
                     "data_source,sensor_adjusted) VALUES (?,?,?,?,?,?,?,?)", (hid, ts, score, tier, conf, lead, source, sensor))

    @contextmanager
    def fake_db():
        yield conn
    monkeypatch.setattr(repository, "get_db", fake_db)
    monkeypatch.setattr(risk_engine, "LAST_RESULTS", {})
    monkeypatch.delenv("HYDRASENSE_MAX_SCORE_AGE_H", raising=False)
    return add


def ids(entries):
    return {e["hex_id"] for e in entries}


def test_only_scored_hexes_are_returned_and_nothing_is_generated(db):
    db(HEX_RIB1, 12.5, "Green", 55.0)
    out = repository.get_risk_map_data("ribhoi-ml")
    assert ids(out) == {HEX_RIB1}                              # HEX_RIB2 / HEX_RIB_UNSCORED have no score: absent
    assert repository.get_risk_map_data("dhemaji-as") == []    # nothing scored -> empty, not a mock


def test_values_are_the_stored_ones_with_no_invented_defaults(db):
    db(HEX_RIB1, 12.5, "Green", None, sensor=0)                # confidence NULL must stay None (was defaulted to 85/86)
    e = repository.get_risk_map_data("ribhoi-ml")[0]
    assert e["risk_score"] == 12.5 and e["tier"] == "Green" and e["confidence_score"] is None
    assert e["lead_time_min"] is None                          # no fake 180-minute lead time
    assert e["instrumented_hex"] is False and e["sensor_adjusted"] is False
    assert e["has_local_calibration"] is True                  # from the hex's static features, not hard-coded
    assert e["data_source"] == "open_meteo_live"


def test_orange_red_never_appear_unless_stored(db):
    for i, h in enumerate([HEX_RIB1, HEX_RIB2]):
        db(h, 5.0 + i, "Green", 50.0)
    tiers = {e["tier"] for e in repository.get_risk_map_data("ribhoi-ml")}
    assert tiers == {"Green"}


def test_sensor_flag_comes_from_the_score_row(db):
    db(HEX_RIB2, 20.0, "Green", 60.0, sensor=1)
    e = repository.get_risk_map_data("ribhoi-ml")[0]
    assert e["instrumented_hex"] is True and e["sensor_adjusted"] is True
    assert e["has_local_calibration"] is False                 # absent in static features -> False, not True


def test_legacy_hexes_with_no_region_are_assigned_by_geography_only(db):
    # An old seeded hex at Munnar (Idukki) has an empty region code: it must NOT appear in Wayanad's map
    # (that pulled the camera to the middle of India), but it does belong to Idukki's bounding box.
    munnar = h3.latlng_to_cell(9.90, 76.85, 8)
    far = h3.latlng_to_cell(28.0, 70.0, 8)                       # in no region's box
    with repository.get_db() as c:
        for hid in (munnar, far):
            c.execute("INSERT INTO hexes VALUES (?,?,?,?,8)", (hid, "{}", "{}", ""))
    db(munnar, 9.0, "Green", 50.0)
    db(far, 9.0, "Green", 50.0)
    db(HEX_WY, 12.0, "Green", 50.0)
    assert ids(repository.get_risk_map_data("wayanad-kl")) == {HEX_WY}
    assert munnar in ids(repository.get_risk_map_data("idukki-kl"))
    for code in repository.REGION_BBOX:
        assert far not in ids(repository.get_risk_map_data(code))


def test_regions_are_isolated_and_legacy_hexes_belong_to_wayanad(db):
    db(HEX_RIB1, 10.0, "Green", 50.0)
    db(HEX_IDK, 11.0, "Green", 50.0)
    db(HEX_WY, 12.0, "Green", 50.0)
    assert ids(repository.get_risk_map_data("ribhoi-ml")) == {HEX_RIB1}
    assert ids(repository.get_risk_map_data("idukki-kl")) == {HEX_IDK}
    assert ids(repository.get_risk_map_data("wayanad-kl")) == {HEX_WY}      # Ribhoi hexes were once labelled Wayanad
    assert ids(repository.get_risk_map_data(None)) == {HEX_WY}


def test_stale_scores_are_not_shown_as_current(db, monkeypatch):
    db(HEX_RIB1, 12.0, "Green", 50.0, age_h=30)
    assert repository.get_risk_map_data("ribhoi-ml") == []
    monkeypatch.setenv("HYDRASENSE_MAX_SCORE_AGE_H", "48")
    assert ids(repository.get_risk_map_data("ribhoi-ml")) == {HEX_RIB1}


def test_latest_score_per_hex_wins(db):
    db(HEX_RIB1, 10.0, "Green", 50.0, age_h=5)
    db(HEX_RIB1, 40.0, "Yellow", 50.0, age_h=1)
    out = repository.get_risk_map_data("ribhoi-ml")
    assert len(out) == 1 and out[0]["risk_score"] == 40.0 and out[0]["tier"] == "Yellow"


def test_per_hazard_tiers_use_the_physics_indices_when_known(db):
    db(HEX_RIB1, 60.0, "Orange", 50.0)
    risk_engine.LAST_RESULTS[HEX_RIB1] = dict(index_flood=10.0, index_landslide=60.0,
                                              confidence_primary_reason="cached soil layer")
    e = repository.get_risk_map_data("ribhoi-ml")[0]
    assert e["flood_tier"] == "Green" and e["landslide_tier"] == "Orange" and e["conf_reason"] == "cached soil layer"
    risk_engine.LAST_RESULTS.clear()
    e = repository.get_risk_map_data("ribhoi-ml")[0]
    assert e["flood_tier"] == "Orange" and e["landslide_tier"] == "Orange"   # falls back to the overall tier


def test_bbox_filter(db):
    db(HEX_RIB1, 10.0, "Green", 50.0)
    db(HEX_RIB2, 11.0, "Green", 50.0)
    out = repository.get_risk_map_data("ribhoi-ml", bbox="91.85,25.85,91.92,25.92")      # minLon,minLat,maxLon,maxLat
    assert ids(out) == {HEX_RIB1}


def test_labels_and_state_parse():
    assert repository._state_from_label("Ribhoi (Nongpoh), Meghalaya (Northeast)") == "Meghalaya"
    assert repository._state_from_label("Wayanad, Kerala (Western Ghats)") == "Kerala"
    assert repository._state_from_label("nonsense") == "India"


def test_response_model_has_no_optimistic_defaults():
    from backend.models import RiskMapEntry
    m = RiskMapEntry(hex_id="h", risk_score=1.0, tier="Green")
    assert m.confidence_score is None and m.has_local_calibration is False
