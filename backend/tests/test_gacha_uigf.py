import json
import unittest

from app.services.gacha_uigf import export_uigf_v42, parse_uigf


class GachaUIGFTests(unittest.TestCase):
    def _build_genshin_record(self):
        return {
            "record_id": "1000001",
            "pool_type": "301",
            "pool_name": "角色活动祈愿",
            "item_name": "刻晴",
            "item_type": "角色",
            "rank_type": "5",
            "time_text": "2026-03-18 12:00:00",
        }

    def _build_starrail_record(self):
        return {
            "record_id": "2000001",
            "pool_type": "11",
            "pool_name": "角色活动跃迁",
            "item_name": "希儿",
            "item_type": "角色",
            "rank_type": "5",
            "time_text": "2026-03-18 12:00:00",
        }

    def test_export_uigf_v42_marks_archive_version(self):
        payload = export_uigf_v42({"genshin": {"10001": [self._build_genshin_record()]}})

        self.assertEqual(payload["info"]["version"], "v4.2")

    def test_export_uigf_v42_places_genshin_records_under_hk4e(self):
        payload = export_uigf_v42({"genshin": {"10001": [self._build_genshin_record()]}})

        self.assertIn("hk4e", payload)
        self.assertEqual(payload["hk4e"][0]["uid"], "10001")
        self.assertEqual(payload["hk4e"][0]["list"][0]["uigf_gacha_type"], "301")

    def test_export_uigf_v42_places_starrail_records_under_hkrpg(self):
        payload = export_uigf_v42({"starrail": {"80001": [self._build_starrail_record()]}})

        self.assertIn("hkrpg", payload)
        self.assertEqual(payload["hkrpg"][0]["uid"], "80001")
        self.assertEqual(payload["hkrpg"][0]["list"][0]["gacha_type"], "11")
        self.assertEqual(payload["hkrpg"][0]["list"][0]["gacha_id"], "synthetic-11")
        self.assertNotIn("uigf_gacha_type", payload["hkrpg"][0]["list"][0])

    def test_export_uigf_v42_preserves_multiple_uid_sections_without_flattening(self):
        payload = export_uigf_v42(
            {
                "genshin": {
                    "10001": [self._build_genshin_record()],
                    "10002": [
                        {
                            **self._build_genshin_record(),
                            "record_id": "1000002",
                            "item_name": "迪卢克",
                        }
                    ],
                }
            }
        )

        self.assertEqual(len(payload["hk4e"]), 2)
        self.assertEqual({section["uid"] for section in payload["hk4e"]}, {"10001", "10002"})

    def test_parse_uigf_accepts_versions_40_41_and_42(self):
        for version in ("v4.0", "v4.1", "v4.2"):
            with self.subTest(version=version):
                payload = {
                    "info": {
                        "export_timestamp": 1710000000,
                        "export_app": "test-suite",
                        "export_app_version": "1.0.0",
                        "version": version,
                    },
                    "hk4e": [
                        {
                            "uid": "10001",
                            "timezone": 8,
                            "lang": "zh-cn",
                            "list": [
                                {
                                    "uigf_gacha_type": "301",
                                    "gacha_type": "301",
                                    "item_id": "",
                                    "count": "1",
                                    "time": "2026-03-18 12:00:00",
                                    "name": "刻晴",
                                    "item_type": "角色",
                                    "rank_type": "5",
                                    "id": "1000001",
                                }
                            ],
                        }
                    ],
                }

                parsed = parse_uigf(payload)

                self.assertEqual(parsed.source_version, version)
                self.assertIn("genshin", parsed.records_by_game_and_uid)
                self.assertIn("10001", parsed.records_by_game_and_uid["genshin"])
                self.assertEqual(
                    parsed.records_by_game_and_uid["genshin"]["10001"][0].record_id,
                    "1000001",
                )

    def test_parse_uigf_accepts_standard_hkrpg_structure(self):
        payload = {
            "info": {
                "export_timestamp": 1710000000,
                "export_app": "test-suite",
                "export_app_version": "1.0.0",
                "version": "v4.2",
            },
            "hkrpg": [
                {
                    "uid": "80001",
                    "timezone": 8,
                    "lang": "zh-cn",
                    "list": [
                        {
                            "gacha_id": "2001",
                            "gacha_type": "11",
                            "item_id": "",
                            "count": "1",
                            "time": "2026-03-18 12:00:00",
                            "name": "希儿",
                            "item_type": "角色",
                            "rank_type": "5",
                            "id": "2000001",
                        }
                    ],
                }
            ],
        }

        parsed = parse_uigf(payload)

        self.assertIn("starrail", parsed.records_by_game_and_uid)
        self.assertIn("80001", parsed.records_by_game_and_uid["starrail"])
        self.assertEqual(
            parsed.records_by_game_and_uid["starrail"]["80001"][0].record_id,
            "2000001",
        )

    def test_parse_uigf_keeps_multiple_uid_groups_for_same_game(self):
        payload = {
            "info": {
                "export_timestamp": 1710000000,
                "export_app": "test-suite",
                "export_app_version": "1.0.0",
                "version": "v4.2",
            },
            "hk4e": [
                {
                    "uid": "10001",
                    "timezone": 8,
                    "lang": "zh-cn",
                    "list": [
                        {
                            "uigf_gacha_type": "301",
                            "gacha_type": "301",
                            "item_id": "",
                            "count": "1",
                            "time": "2026-03-18 12:00:00",
                            "name": "刻晴",
                            "item_type": "角色",
                            "rank_type": "5",
                            "id": "1000001",
                        }
                    ],
                },
                {
                    "uid": "10002",
                    "timezone": 8,
                    "lang": "zh-cn",
                    "list": [
                        {
                            "uigf_gacha_type": "301",
                            "gacha_type": "301",
                            "item_id": "",
                            "count": "1",
                            "time": "2026-03-18 11:59:00",
                            "name": "迪卢克",
                            "item_type": "角色",
                            "rank_type": "5",
                            "id": "1000002",
                        }
                    ],
                },
            ],
        }

        parsed = parse_uigf(payload)

        self.assertEqual(set(parsed.records_by_game_and_uid["genshin"].keys()), {"10001", "10002"})

    def test_parse_uigf_accepts_raw_json_text(self):
        payload = json.dumps(
            {
                "info": {
                    "export_timestamp": 1710000000,
                    "export_app": "test-suite",
                    "export_app_version": "1.0.0",
                    "version": "v4.2",
                },
                "hkrpg": [
                    {
                        "uid": "80001",
                        "timezone": 8,
                        "lang": "zh-cn",
                        "list": [
                            {
                                "gacha_id": "2001",
                                "gacha_type": "11",
                                "item_id": "",
                                "count": "1",
                                "time": "2026-03-18 12:00:00",
                                "name": "希儿",
                                "item_type": "角色",
                                "rank_type": "5",
                                "id": "2000001",
                            }
                        ],
                    }
                ],
            }
        )

        parsed = parse_uigf(payload)

        self.assertEqual(
            parsed.records_by_game_and_uid["starrail"]["80001"][0].item_name,
            "希儿",
        )

    def test_parse_uigf_rejects_missing_or_malformed_info(self):
        invalid_payloads = [
            {},
            {"info": "invalid"},
            {
                "info": {
                    "export_timestamp": 1710000000,
                    "export_app": "test-suite",
                    "export_app_version": "1.0.0",
                }
            },
            {
                "info": {
                    "export_timestamp": 1710000000,
                    "export_app": "test-suite",
                    "export_app_version": "1.0.0",
                    "version": "v3.0",
                }
            },
            {
                "info": {
                    "export_app": "test-suite",
                    "export_app_version": "1.0.0",
                    "version": "v4.2",
                }
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_uigf(payload)

    def test_parse_uigf_rejects_malformed_game_sections(self):
        invalid_payloads = [
            {
                "info": {
                    "export_timestamp": 1710000000,
                    "export_app": "test-suite",
                    "export_app_version": "1.0.0",
                    "version": "v4.2",
                },
                "hk4e": [
                    {
                        "uid": "10001",
                        "timezone": 8,
                        "lang": "zh-cn",
                        "list": [
                            {
                                "gacha_type": "301",
                                "item_id": "",
                                "count": "1",
                                "time": "2026-03-18 12:00:00",
                                "name": "刻晴",
                                "item_type": "角色",
                                "rank_type": "5",
                                "id": "1000001",
                            }
                        ],
                    }
                ],
            },
            {
                "info": {
                    "export_timestamp": 1710000000,
                    "export_app": "test-suite",
                    "export_app_version": "1.0.0",
                    "version": "v4.2",
                },
                "hkrpg": [
                    {
                        "uid": "80001",
                        "timezone": 8,
                        "lang": "zh-cn",
                        "list": "invalid-list",
                    }
                ],
            },
        ]

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_uigf(payload)


if __name__ == "__main__":
    unittest.main()
