import os
import tempfile
import unittest

import radar_core


class GeoTests(unittest.TestCase):
    def test_north_and_distance(self):
        bearing = radar_core.bearing_deg(52.0, 13.0, 53.0, 13.0)
        self.assertLess(bearing, 1.0)
        distance = radar_core.distance_km(52.0, 13.0, 53.0, 13.0)
        self.assertGreater(distance, 110)
        self.assertLess(distance, 112)

    def test_move_north_increases_latitude(self):
        lat, lon = radar_core.move_aircraft(52.0, 13.0, 0, 500, 60)
        self.assertGreater(lat, 52.0)
        self.assertAlmostEqual(lon, 13.0, places=2)

    def test_altitude_labels(self):
        self.assertEqual(radar_core.format_alt(None), "")
        self.assertEqual(radar_core.format_alt(0), "GND")
        self.assertEqual(radar_core.format_alt(4500), "4500ft")
        self.assertEqual(radar_core.format_alt(32000), "FL320")


class FeedTests(unittest.TestCase):
    def test_dump1090_contacts(self):
        payload = {
            "aircraft": [
                {
                    "hex": "abc123",
                    "flight": "BAW1   ",
                    "lat": 52.62,
                    "lon": 13.405,
                    "alt_baro": 35000,
                    "gs": 400,
                    "track": 180,
                    "baro_rate": -64,
                    "seen": 1,
                    "seen_pos": 1,
                },
                {
                    "hex": "def456",
                    "flight": "",
                    "lat": 52.52,
                    "lon": 13.55,
                    "alt_baro": "ground",
                    "gs": 5,
                    "seen": 2,
                },
                {
                    "hex": "aaa111",
                    "flight": "OLD",
                    "lat": 52.8,
                    "lon": 13.4,
                    "alt_baro": 10000,
                    "seen_pos": 90,
                },
                {"hex": "bbb222", "flight": "NOPOS", "seen": 1},
            ]
        }
        contacts, unpositioned = radar_core.normalize_dump1090(payload, 52.52, 13.405)
        self.assertEqual(unpositioned, 1)
        self.assertEqual(len(contacts), 2)
        baw = next(item for item in contacts if item["cs"] == "BAW1")
        self.assertEqual(baw["alt"], 35000)
        view = radar_core.project_contacts(contacts, 52.52, 13.405, 50, 5, unpositioned)
        self.assertEqual(view["in_range"], 2)
        baw_view = next(item for item in view["aircraft"] if item["cs"] == "BAW1")
        self.assertGreater(baw_view["km"], 10)
        self.assertLess(baw_view["km"], 13)
        self.assertLess(baw_view["brg"], 5)
        self.assertEqual(baw_view["alt"], 35000)
        self.assertEqual(baw_view["trk"], 180)

    def test_pisky_url_cleanup(self):
        self.assertEqual(
            radar_core.clean_pisky_base("http://pi:5050/livemap"),
            "http://pi:5050",
        )
        self.assertEqual(
            radar_core.clean_pisky_base("http://pi:5050/api/dump1090/aircraft.json"),
            "http://pi:5050",
        )


class SimulatorTests(unittest.TestCase):
    def test_aircraft_move_and_stay_near_home(self):
        sim = radar_core.Simulator(__import__("random").Random(3))
        sim.configure(52.52, 13.405, 50, 6)
        start = [(round(c["lat"], 3), round(c["lon"], 3)) for c in sim.craft]
        sim.advance(20, 52.52, 13.405, 50)
        later = [(round(c["lat"], 3), round(c["lon"], 3)) for c in sim.craft]
        self.assertNotEqual(start, later)
        self.assertEqual(len(sim.craft), 6)
        routed = [craft for craft in sim.contacts() if craft.get("from") and craft.get("to")]
        self.assertGreaterEqual(len(routed), 1)
        self.assertNotEqual(routed[0]["from"], routed[0]["to"])
        for craft in sim.contacts():
            km = radar_core.distance_km(52.52, 13.405, craft["lat"], craft["lon"])
            self.assertLess(km, 80)


class ConfigTests(unittest.TestCase):
    def test_theme_is_part_of_the_picture(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.close()
        try:
            store = radar_core.ConfigStore(handle.name)
            saved = store.update({"theme": "amber"})
            self.assertEqual(saved["theme"], "amber")
            cfg = store.get()
            frame = radar_core.build_frame(
                cfg, "simulator", True, "", 52.0, 13.0, "config", [], 0, {}
            )
            self.assertEqual(frame["theme"], "amber")
            self.assertEqual(frame["palette"]["sweep"], radar_core.THEMES["amber"]["sweep"])
            with self.assertRaises(ValueError):
                store.update({"theme": "neon"})
        finally:
            os.unlink(handle.name)

    def test_pisky_card_fields(self):
        raw = '\n'.join([
            "data: " + '{"type":"flight_update","flights":[{"icao":"abc123","origin":"EDDB","destination":"EGLL","origin_city":"Berlin","destination_city":"London","airline_name":"British Airways","aircraft_type":"A320","aircraft_registration":"G-EUYY"}]}',
            "",
        ])
        details = radar_core.parse_sse_snapshot(raw)
        self.assertEqual(details["ABC123"]["from"], "EDDB")
        self.assertEqual(details["ABC123"]["to_city"], "London")
        contacts = [{"hex": "ABC123", "cs": "BAW1", "lat": 1, "lon": 2, "alt": 1, "trk": 0, "gs": 1, "vr": 0}]
        radar_core.apply_details(contacts, details)
        view = radar_core.project_contacts(contacts, 1, 2, 50, 3)
        card = view["aircraft"][0]
        self.assertEqual(card["airline"], "British Airways")
        self.assertEqual(card["type"], "A320")
        self.assertEqual(card["reg"], "G-EUYY")

    def test_rejects_bad_mode(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.close()
        try:
            store = radar_core.ConfigStore(handle.name)
            with self.assertRaises(ValueError):
                store.update({"mode": "sideways"})
        finally:
            os.unlink(handle.name)


if __name__ == "__main__":
    unittest.main()
