"""Experiment B — UK postcode → admin boundaries + IMD enrichment.

Lookup order: SQLite cache → postcodes.io API → persist result.
IMD 2019 (England) loaded once into memory and joined by LSOA code.
"""
import csv
import io
import re
import threading

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from yield_system.auth import assert_within_daily_limit, require_api_key
from yield_system.db import connect
from yield_system.log import post_log, pre_log

EXPERIMENT = "postcode"
router = APIRouter(prefix="/v1/postcode", tags=[EXPERIMENT])

_IMD_URL = (
    "https://assets.publishing.service.gov.uk/media/5dc407b440f0b6379a7acc8d/"
    "File_7_-_All_IoD2019_Scores__Ranks__Deciles_and_Population_Denominators_3.csv"
)

# lsoa_code → (decile, quintile, score)
_IMD: dict[str, tuple[int, int, float]] = {}
_IMD_LOCK = threading.Lock()


def _load_imd() -> None:
    if _IMD:
        return
    with _IMD_LOCK:
        if _IMD:
            return
        try:
            r = httpx.get(_IMD_URL, timeout=30.0)
            r.raise_for_status()
        except httpx.HTTPError:
            return
        reader = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            lsoa = row.get("LSOA code (2011)", "").strip()
            if not lsoa:
                continue
            try:
                decile = int(
                    row.get("Index of Multiple Deprivation (IMD) Decile (where 1 is most deprived 10% of LSOAs)", 5)
                    or 5
                )
                score = float(
                    row.get("Index of Multiple Deprivation (IMD) Score", 25.0) or 25.0
                )
            except (ValueError, TypeError):
                decile, score = 5, 25.0
            quintile = (decile - 1) // 2 + 1
            _IMD[lsoa] = (decile, quintile, score)


class PostcodeData(BaseModel):
    postcode: str
    lat: float
    lng: float
    lsoa_code: str
    msoa_code: str
    district: str
    region: str
    imd_decile: int
    imd_quintile: int
    deprivation_score: float


_POSTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}$")


def normalize_postcode(raw: str) -> str | None:
    cleaned = raw.upper().replace(" ", "").strip()
    if not _POSTCODE_RE.match(cleaned):
        return None
    return cleaned


def _from_cache(normalized: str) -> PostcodeData | None:
    with connect() as c:
        row = c.execute(
            "SELECT postcode, lat, lng, lsoa_code, msoa_code, district, region, "
            "imd_decile, imd_quintile, deprivation_score "
            "FROM postcodes WHERE postcode = ?",
            (normalized,),
        ).fetchone()
    return PostcodeData(**dict(row)) if row else None


def _persist(data: PostcodeData) -> None:
    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO postcodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data.postcode, data.lat, data.lng, data.lsoa_code, data.msoa_code,
                data.district, data.region, data.imd_decile, data.imd_quintile,
                data.deprivation_score,
            ),
        )


def _from_api(normalized: str) -> PostcodeData | None:
    try:
        r = httpx.get(
            f"https://api.postcodes.io/postcodes/{normalized}",
            timeout=10.0,
        )
        if r.status_code == 404:
            return None
        r.raise_for_status()
        d = r.json().get("result") or {}
    except (httpx.HTTPError, ValueError):
        return None

    codes = d.get("codes") or {}
    lsoa = codes.get("lsoa") or ""

    _load_imd()
    decile, quintile, score = _IMD.get(lsoa, (5, 3, 25.0))

    data = PostcodeData(
        postcode=normalized,
        lat=float(d.get("latitude") or 0),
        lng=float(d.get("longitude") or 0),
        lsoa_code=lsoa or "UNKNOWN",
        msoa_code=codes.get("msoa") or "UNKNOWN",
        district=d.get("admin_district") or "UNKNOWN",
        region=d.get("region") or d.get("country") or "UNKNOWN",
        imd_decile=decile,
        imd_quintile=quintile,
        deprivation_score=score,
    )
    _persist(data)
    return data


def lookup_postcode(normalized: str) -> PostcodeData | None:
    cached = _from_cache(normalized)
    if cached is not None:
        return cached
    return _from_api(normalized)


def _auth(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    return require_api_key(EXPERIMENT, x_api_key)


@router.get("/{raw}")
def get_postcode(raw: str, customer: dict = Depends(_auth)) -> PostcodeData:
    normalized = normalize_postcode(raw)
    if normalized is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid UK postcode format")
    assert_within_daily_limit(customer["customer_id"], customer["plan"])
    call_id = pre_log(
        experiment=f"customer:{customer['customer_id']}",
        action=f"lookup:{normalized}",
        expected_cost_gbp=0.0,
        expected_outcome="200_or_404",
    )
    data = lookup_postcode(normalized)
    if data is None:
        post_log(call_id, "404_not_found")
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"postcode {normalized} not found")
    post_log(call_id, "200_ok")
    return data


def ensure_table() -> None:
    with connect() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS postcodes (
                postcode TEXT PRIMARY KEY,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                lsoa_code TEXT NOT NULL,
                msoa_code TEXT NOT NULL,
                district TEXT NOT NULL,
                region TEXT NOT NULL,
                imd_decile INTEGER NOT NULL,
                imd_quintile INTEGER NOT NULL,
                deprivation_score REAL NOT NULL
            )
            """
        )
