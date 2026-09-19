import unittest

from app.services.geetest import (
    GENERIC_RISK_MESSAGE,
    GEETEST_RISK_MESSAGE,
    parse_checkin_risk,
)


class ParseCheckinRiskTests(unittest.TestCase):
    def test_is_risk_with_gt_and_challenge_is_geetest(self):
        info = parse_checkin_risk({
            "retcode": 0,
            "data": {
                "is_risk": True,
                "gt": "gt-token",
                "challenge": "challenge-token",
                "success": 1,
            },
        })

        self.assertIsNotNone(info)
        self.assertEqual(info.kind, "geetest")
        self.assertTrue(info.has_gt)
        self.assertTrue(info.has_challenge)
        self.assertEqual(info.message, GEETEST_RISK_MESSAGE)

    def test_gt_only_is_geetest(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"gt": "gt-token"}})

        self.assertEqual(info.kind, "geetest")
        self.assertTrue(info.has_gt)
        self.assertFalse(info.has_challenge)

    def test_challenge_only_is_geetest(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"challenge": "challenge-token"}})

        self.assertEqual(info.kind, "geetest")
        self.assertFalse(info.has_gt)
        self.assertTrue(info.has_challenge)

    def test_success_one_without_tokens_is_unsolvable_risk(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"success": 1}})

        self.assertEqual(info.kind, "risk")
        self.assertFalse(info.has_gt)
        self.assertFalse(info.has_challenge)
        self.assertEqual(info.message, GENERIC_RISK_MESSAGE)

    def test_success_one_is_not_treated_as_signed(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"success": 1, "is_sign": False}})

        self.assertIsNotNone(info)
        self.assertEqual(info.kind, "risk")

    def test_nonzero_risk_code_without_tokens_is_unsolvable_risk(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"risk_code": 375}})

        self.assertEqual(info.kind, "risk")
        self.assertEqual(info.risk_code, 375)
        self.assertEqual(info.message, GENERIC_RISK_MESSAGE)

    def test_zero_risk_code_alone_is_not_risk(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"risk_code": 0, "success": 0}})

        self.assertIsNone(info)

    def test_geetest_retcode_without_data_is_geetest(self):
        for retcode in (1034, 10035, 10041):
            with self.subTest(retcode=retcode):
                info = parse_checkin_risk({"retcode": retcode, "message": "not login"})
                self.assertEqual(info.kind, "geetest")
                self.assertEqual(info.retcode, retcode)
                self.assertEqual(info.message, GEETEST_RISK_MESSAGE)

    def test_already_signed_retcode_is_not_risk_even_with_gt(self):
        info = parse_checkin_risk({
            "retcode": -5003,
            "data": {"is_risk": True, "gt": "gt-token", "challenge": "challenge-token"},
        })

        self.assertIsNone(info)

    def test_game_record_geetest_code_is_not_sign_risk(self):
        info = parse_checkin_risk({"retcode": 5003, "message": "geetest"})

        self.assertIsNone(info)

    def test_successful_sign_payload_is_not_risk(self):
        info = parse_checkin_risk({
            "retcode": 0,
            "data": {"success": 0, "is_risk": False, "total_sign_day": 12},
        })

        self.assertIsNone(info)

    def test_empty_gt_does_not_count_as_geetest_token(self):
        info = parse_checkin_risk({"retcode": 0, "data": {"is_risk": True, "gt": "  "}})

        self.assertEqual(info.kind, "risk")
        self.assertFalse(info.has_gt)

    def test_non_dict_payload_is_not_risk(self):
        self.assertIsNone(parse_checkin_risk(None))
        self.assertIsNone(parse_checkin_risk([]))
