"""Archive METMalaysia public context without inventing rainfall intensities.

This adapter has no connection to hydraulic inputs or scheduling decisions.
Fetching is explicit; opening the application never sends an API request.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.data.gov.my/weather/"
DOCS = "https://developer.data.gov.my/realtime-api/weather"


def describe_payload(kind, rows, reference_date):
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("Weather response must be a list of records.")
    if kind == "forecast":
        dates = []
        for row in rows:
            date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            if not isinstance(row.get("location"), dict) or not isinstance(row["location"].get("location_name"), str):
                raise ValueError("Forecast location is missing.")
            if not isinstance(row.get("summary_forecast"), str):
                raise ValueError("Qualitative forecast is missing.")
            dates.append(date)
        return {"record_count": len(rows), "date_from": str(min(dates)) if dates else None,
                "date_to": str(max(dates)) if dates else None,
                "covers_reference_date": reference_date in dates,
                "freshness": "dated_snapshot" if reference_date in dates else "does_not_cover_reference_date",
                "locations": sorted({r["location"]["location_name"] for r in rows}),
                "rainfall_intensity_available": False,
                "units": "Qualitative forecast phrases; temperature in degrees Celsius. No rainfall mm or mm/h."}
    if kind == "warning":
        dates = []
        missing_validity_fields = 0
        for row in rows:
            for key in ("valid_from", "valid_to"):
                if row.get(key) is None:
                    missing_validity_fields += 1
                    continue
                value = datetime.fromisoformat(row[key])
                dates.append(value.date())
            if not isinstance(row.get("warning_issue"), dict):
                raise ValueError("Warning issue metadata is missing.")
        return {"record_count": len(rows), "date_from": str(min(dates)) if dates else None,
                "date_to": str(max(dates)) if dates else None,
                "missing_validity_fields": missing_validity_fields,
                "freshness": "archived_response_not_live_status", "rainfall_intensity_available": False,
                "units": "Unmodified warning text and source validity timestamps; no numeric rainfall conversion.",
                "timezone_note": "Source warning timestamps are preserved. Naive timestamps are not silently assigned a timezone.",
                "empty_response_meaning": "An empty response is not proof of safe weather or an all-clear."}
    raise ValueError("Unsupported public weather kind.")


def acquire(destination, reference_date, *, opener=urlopen):
    """Two GET requests; below the documented four weather requests/minute."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    records = []
    for kind, query in [("forecast", {"filter": "Selangor@location__location_name", "limit": 14}),
                        ("warning", {"limit": 100})]:
        url = API + kind + "?" + urlencode(query)
        requested = datetime.now(timezone.utc).isoformat()
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "MonsoonRehearsal/0.2 research-snapshot"})
        with opener(request, timeout=45) as response:
            raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError("Unexpectedly large weather response.")
            status = response.status
            source_date = response.headers.get("Date")
            content_type = response.headers.get("Content-Type")
        if status != 200:
            raise ValueError(f"Weather API returned {status}.")
        rows = json.loads(raw)
        summary = describe_payload(kind, rows, reference_date)
        digest = hashlib.sha256(raw).hexdigest()
        filename = f"met_{kind}_{digest[:12]}.json"
        (destination / filename).write_bytes(raw)
        records.append({"kind": kind, "file": filename, "sha256": digest, "bytes": len(raw),
                        "url": url, "retrieved_at_utc": requested, "http_date": source_date,
                        "http_status": status, "content_type": content_type,
                        "query_limit": query["limit"], "possibly_truncated": len(rows) >= query["limit"], **summary})
    manifest = {"schema_version": 1, "source": "METMalaysia via Malaysia's Official Open API",
                "documentation_url": DOCS, "access_url": "https://developer.data.gov.my/quickstart",
                "access": "Public GET; no API token, account or access request used.",
                "reference_date": str(reference_date), "geography": "Selangor forecast; national warning response. No selected pilot site.",
                "purpose": "Public-data ingestion and regional context; not hydraulic calibration or policy-performance evidence.",
                "licence": "Dataset-specific redistribution terms not established from the API docs; retain source attribution and verify terms before public redistribution.",
                "limitations": ["Qualitative forecasts cannot determine storm intensity, hydrographs or a safe maintenance deadline.",
                                "No forecast is treated as a probability distribution.",
                                "Snapshot dates and HTTP timestamps may differ from the research reference date; check coverage.",
                                "No public weather record is injected into the frozen synthetic catchment."],
                "records": records}
    (destination / "met_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-date", required=True, help="YYYY-MM-DD; user's local date used to check coverage.")
    args = parser.parse_args()
    manifest = acquire(args.output, datetime.strptime(args.reference_date, "%Y-%m-%d").date())
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
