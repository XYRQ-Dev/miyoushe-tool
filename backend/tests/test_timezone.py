import logging
import unittest
from datetime import date, datetime, timedelta, timezone

from app.schemas.account import AccountResponse
from app.schemas.task_log import TaskLogResponse
from app.schemas.user import UserResponse
from app.utils.timezone import (
    SHANGHAI,
    ShanghaiLogFormatter,
    get_shanghai_date,
    get_shanghai_day_utc_range,
    shanghai_now,
    to_shanghai,
    utc_now,
    utc_now_naive,
)


class TimezoneHelperTests(unittest.TestCase):
    def test_utc_now_helpers_return_utc_with_and_without_tzinfo(self):
        aware_now = utc_now()
        naive_now = utc_now_naive()

        self.assertEqual(aware_now.tzinfo, timezone.utc)
        self.assertIsNone(naive_now.tzinfo)
        self.assertLess(abs((aware_now.replace(tzinfo=None) - naive_now).total_seconds()), 2)

    def test_to_shanghai_treats_naive_values_as_utc(self):
        converted = to_shanghai(datetime(2026, 3, 16, 16, 30, 0))

        self.assertEqual(converted.tzinfo, SHANGHAI)
        self.assertEqual(converted.utcoffset(), timedelta(hours=8))
        self.assertEqual(converted.hour, 0)
        self.assertEqual(converted.minute, 30)
        self.assertEqual(converted.day, 17)

    def test_to_shanghai_converts_aware_utc_without_changing_instant(self):
        source = datetime(2026, 3, 16, 16, 30, 0, tzinfo=timezone.utc)
        converted = to_shanghai(source)

        self.assertEqual(converted.utcoffset(), timedelta(hours=8))
        self.assertEqual(converted, source.astimezone(SHANGHAI))

    def test_shanghai_day_range_uses_east_eight_midnight(self):
        start, end = get_shanghai_day_utc_range(date(2026, 3, 17))

        self.assertIsNone(start.tzinfo)
        self.assertIsNone(end.tzinfo)
        self.assertEqual(start, datetime(2026, 3, 16, 16, 0, 0))
        self.assertEqual(end, datetime(2026, 3, 17, 16, 0, 0))

    def test_get_shanghai_date_matches_shanghai_now(self):
        self.assertEqual(get_shanghai_date(), shanghai_now().date())

    def test_user_response_serializes_naive_utc_as_shanghai(self):
        response = UserResponse(
            id=1,
            username="demo",
            role="user",
            is_active=True,
            created_at=datetime(2026, 3, 16, 16, 30, 0),
        )

        self.assertEqual(response.created_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(response.created_at.hour, 0)
        self.assertTrue(response.model_dump(mode="json")["created_at"].endswith("+08:00"))

    def test_account_and_log_responses_convert_naive_utc_fields(self):
        naive_utc = datetime(2026, 3, 16, 16, 30, 0)
        account = AccountResponse(
            id=1,
            user_id=1,
            created_at=naive_utc,
            last_cookie_check=naive_utc,
            last_refresh_attempt_at=None,
        )
        log = TaskLogResponse(
            id=1,
            account_id=1,
            task_type="checkin",
            status="success",
            executed_at=naive_utc,
        )

        self.assertIsNone(account.last_refresh_attempt_at)
        self.assertEqual(account.last_cookie_check.hour, 0)
        self.assertEqual(log.executed_at.utcoffset(), timedelta(hours=8))
        self.assertTrue(account.model_dump(mode="json")["last_cookie_check"].endswith("+08:00"))
        self.assertTrue(log.model_dump(mode="json")["executed_at"].endswith("+08:00"))

    def test_shanghai_log_formatter_renders_east_eight_wall_clock(self):
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.created = datetime(2026, 3, 16, 16, 30, 0, tzinfo=timezone.utc).timestamp()
        formatter = ShanghaiLogFormatter("%(asctime)s")

        self.assertEqual(formatter.formatTime(record), "2026-03-17 00:30:00,000")


if __name__ == "__main__":
    unittest.main()
