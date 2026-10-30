"""Correction input contract; run without PostgreSQL as well as in CI."""

import pytest
from pydantic import ValidationError

from app.schemas import AttendanceCorrectionRequest


def valid_payload():
    return {
        "clock_in_at": "2026-10-29T09:00:00+09:00",
        "clock_out_at": "2026-10-29T18:00:00+09:00",
        "expected_operation_id": 1,
        "change_reason": "退勤打刻を忘れたため",
    }


@pytest.mark.parametrize("replacement", [
    {"clock_in_at": "2026-10-29T09:00:00"},
    {"clock_out_at": "2026-10-29T18:00:00"},
    {"clock_out_at": "2026-10-29T08:59:59+09:00"},
    {"clock_in_at": "invalid"},
    {"clock_in_at": 1793232000},
    {"change_reason": " \n\t　 "},
    {"change_reason": "あ" * 501},
    {"change_reason": None},
    {"expected_operation_id": 0},
    {"expected_operation_id": True},
    {"expected_operation_id": "1"},
    {"expected_operation_id": 2**63},
    {"user_id": 123},
    {"cancelled_at": None},
])
def test_invalid_corrections_are_rejected(replacement):
    with pytest.raises(ValidationError):
        AttendanceCorrectionRequest.model_validate(valid_payload() | replacement)


@pytest.mark.parametrize("missing", [
    "clock_in_at", "clock_out_at", "expected_operation_id", "change_reason",
])
def test_all_correction_fields_must_be_explicit(missing):
    payload = valid_payload()
    del payload[missing]
    with pytest.raises(ValidationError):
        AttendanceCorrectionRequest.model_validate(payload)


def test_explicit_null_reopens_shift_and_reason_is_trimmed():
    parsed = AttendanceCorrectionRequest.model_validate(valid_payload() | {
        "clock_out_at": None, "expected_operation_id": None,
        "change_reason": "  退勤時刻を誤入力  ",
    })
    assert parsed.clock_out_at is None
    assert parsed.expected_operation_id is None
    assert parsed.change_reason == "退勤時刻を誤入力"


def test_equal_instants_with_different_offsets_are_allowed():
    parsed = AttendanceCorrectionRequest.model_validate(valid_payload() | {
        "clock_out_at": "2026-10-29T00:00:00Z", "change_reason": "あ" * 500,
    })
    assert parsed.clock_in_at == parsed.clock_out_at
