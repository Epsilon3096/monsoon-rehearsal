"""Check the adapter never upgrades public context to hydraulic evidence."""
from datetime import date
import hashlib
import io
import json

import pytest

from monsoon.public_weather import acquire, describe_payload


def test_old_forecast_and_warning_missing_validity_are_not_current_evidence():
    forecast = [{"date":"2026-01-01", "location":{"location_name":"Selangor"}, "summary_forecast":"Hujan"}]
    info = describe_payload("forecast", forecast, date(2026,10,13))
    assert not info["covers_reference_date"]
    assert not info["rainfall_intensity_available"]
    warning = [{"valid_from":None,"valid_to":None,"warning_issue":{"issued":"2026-10-13T10:00:00"}}]
    info = describe_payload("warning", warning, date(2026,10,13))
    assert info["date_from"] is None
    assert info["missing_validity_fields"] == 2
    assert info["freshness"] == "archived_response_not_live_status"
    assert "not proof" in describe_payload("warning", [], date(2026,10,13))["empty_response_meaning"]


def test_archive_preserves_bytes_source_and_detects_truncation(tmp_path):
    body = json.dumps([{"date":"2026-10-13","location":{"location_name":"Selangor"},"summary_forecast":"Hujan"}] * 14).encode()
    requested = []
    class Response(io.BytesIO):
        status = 200
        headers = {"Date":"Tue, 13 Oct 2026 14:00:00 GMT", "Content-Type":"application/json"}
    def opener(request, timeout):
        requested.append(request.full_url)
        return Response(body if "/forecast?" in request.full_url else b"[]")
    manifest = acquire(tmp_path,date(2026,10,13),opener=opener)
    assert len(requested) == 2
    assert "filter=Selangor" in requested[0]
    row = manifest["records"][0]
    assert row["possibly_truncated"]
    assert (tmp_path/row["file"]).read_bytes() == body
    assert row["sha256"] == hashlib.sha256(body).hexdigest()
    assert manifest["records"][1]["record_count"] == 0


@pytest.mark.parametrize("payload", [{"error":"unavailable"}, [None], [{"date":"invalid"}]])
def test_malformed_weather_fails_explicitly(payload):
    with pytest.raises((ValueError,KeyError)):
        describe_payload("forecast",payload,date(2026,10,13))
