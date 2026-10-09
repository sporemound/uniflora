from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from uniflora.external_feeds.aprsfi.config import (
    AprsFiSettings,
    AprsFiTarget,
    load_targets,
)
from uniflora.external_feeds.aprsfi.formatter import render_exterior_report
from uniflora.external_feeds.aprsfi.models import (
    AprsFiLocationRecord,
    AprsFiWeatherRecord,
)
from uniflora.external_feeds.aprsfi.service import AprsFiExteriorService


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def settings() -> AprsFiSettings:
    return AprsFiSettings(
        api_key="test-key",
        alias_secret="0123456789abcdef0123456789abcdef",
        project_url="https://example.org/uniflora",
        targets=(
            AprsFiTarget("N0CALL", location=True),
            AprsFiTarget("N0CALL-2", location=False, weather=True),
        ),
    )


class ModelTests(unittest.TestCase):
    def test_location_parser_discards_free_text(self) -> None:
        entry = {
            "name": "N0CALL",
            "type": "l",
            "time": "1267445689",
            "lasttime": "1270580127",
            "lat": "63.06717",
            "lng": "27.66050",
            "speed": "12.3",
            "comment": "private-ish comment",
            "status": "another free-text field",
            "path": "WIDE2-2,qAR,N0CALL-9",
            "srccall": "N0CALL",
        }
        record = AprsFiLocationRecord.from_api(entry)
        self.assertEqual(record.name, "N0CALL")
        self.assertAlmostEqual(record.latitude or 0.0, 63.06717)
        self.assertFalse(hasattr(record, "comment"))
        self.assertFalse(hasattr(record, "status"))
        self.assertFalse(hasattr(record, "path"))

    def test_weather_parser_uses_metric_values(self) -> None:
        record = AprsFiWeatherRecord.from_api(
            {
                "name": "N0CALL-2",
                "time": "1270580978",
                "temp": "2.8",
                "pressure": "1022.1",
                "humidity": "88",
                "wind_speed": "2.7",
            }
        )
        self.assertEqual(record.temperature_c, 2.8)
        self.assertEqual(record.pressure_mbar, 1022.1)
        self.assertEqual(record.wind_speed_mps, 2.7)


class ConfigTests(unittest.TestCase):
    def test_load_targets(self) -> None:
        with TemporaryDirectory() as temp:
            path = Path(temp) / "targets.json"
            path.write_text(
                json.dumps(
                    {
                        "targets": [
                            {
                                "name": "N0CALL",
                                "location": True,
                                "weather": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            targets = load_targets(path)
            self.assertEqual(targets[0].name, "N0CALL")


class FormatterTests(unittest.TestCase):
    def test_report_hides_callsign_and_exact_coordinates(self) -> None:
        location = AprsFiLocationRecord(
            name="N0CALL",
            target_type="l",
            first_at_position=NOW,
            last_reported_at=NOW,
            latitude=25.728333,
            longitude=32.601389,
            course_degrees=None,
            speed_kph=0.0,
            altitude_m=None,
        )
        text = render_exterior_report(
            (location,),
            (),
            settings(),
            now=NOW,
        )
        self.assertNotIn("N0CALL", text)
        self.assertNotIn("25.728333", text)
        self.assertNotIn("32.601389", text)
        self.assertIn("Data source: <https://aprs.fi/>", text)
        self.assertIn("settlement state unchanged", text)


class _FakeClient:
    def __init__(self) -> None:
        self.location_calls = 0
        self.weather_calls = 0

    async def query_locations(self, names):
        self.location_calls += 1
        return (
            AprsFiLocationRecord(
                name=tuple(names)[0],
                target_type="l",
                first_at_position=NOW,
                last_reported_at=NOW,
                latitude=25.728333,
                longitude=32.601389,
                course_degrees=None,
                speed_kph=0.0,
                altitude_m=None,
            ),
        )

    async def query_weather(self, names):
        self.weather_calls += 1
        return (
            AprsFiWeatherRecord(
                name=tuple(names)[0],
                reported_at=NOW,
                temperature_c=30.0,
                pressure_mbar=1005.0,
                humidity_percent=20.0,
                wind_direction_degrees=90.0,
                wind_speed_mps=2.0,
                wind_gust_mps=None,
                rain_1h_mm=0.0,
                rain_24h_mm=None,
                rain_since_midnight_mm=None,
                luminosity_wm2=None,
            ),
        )

    async def close(self):
        return None


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_request_uses_cache(self) -> None:
        fake = _FakeClient()
        service = AprsFiExteriorService(settings(), client=fake)  # type: ignore[arg-type]

        first = await service.report()
        second = await service.report()

        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual(fake.location_calls, 1)
        self.assertEqual(fake.weather_calls, 1)
        self.assertIn("CACHED OBSERVATION", second.text)


if __name__ == "__main__":
    unittest.main()
