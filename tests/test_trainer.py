import json
import logging

import httpx
import pytest

from app.trainer import Evaluation, completion_content, log_model_failure


def response_with(content, finish_reason="stop"):
    return httpx.Response(200, request=httpx.Request("POST", "https://example.test/completions"), json={
        "id": "gen-example", "provider": "test-provider",
        "usage": {"prompt_tokens": 200, "completion_tokens": 1400, "total_tokens": 1600},
        "choices": [{"finish_reason": finish_reason, "message": {"content": content}}],
    })


def test_truncated_completion_logs_metadata_without_answer_or_key(caplog):
    secret = "private-student-answer-and-key"
    response = response_with('{"score":50,"feedback":"' + secret, "length")
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError):
        completion_content(response, "evaluate", "test-model", Evaluation.model_validate_json)
    assert secret not in caplog.text
    details = json.loads(caplog.records[-1].message.split(": ", 1)[1])
    assert details["generation_id"] == "gen-example"
    assert details["finish_reason"] == "length"
    assert details["completion_tokens"] == 1400
    assert details["validation"] == [{"field": "", "type": "json_invalid"}]


def test_invalid_credit_logs_field_and_type_without_validation_input(caplog):
    content = json.dumps({"feedback": "private-feedback", "criterion_results": [
        {"id": "c1", "status": "partial", "credit": 999, "evidence": "private-answer"}]})
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError):
        completion_content(response_with(content), "evaluate", "test-model", Evaluation.model_validate_json)
    assert "private-feedback" not in caplog.text
    assert '"field": "criterion_results.0.credit"' in caplog.text
    assert '"type": "less_than_equal"' in caplog.text


@pytest.mark.parametrize("content", [None, "", " ", {"feedback": "private-feedback"}])
def test_empty_or_non_text_response_is_rejected_and_logged(content, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError):
        completion_content(response_with(content), "evaluate", "test-model", Evaluation.model_validate_json)
    assert '"error_type": "ValueError"' in caplog.text
    assert "private-feedback" not in caplog.text


def test_http_failure_records_status_without_raw_provider_error(caplog):
    response = httpx.Response(429, request=httpx.Request("POST", "https://example.test/completions"),
                              json={"error": {"message": "private-provider-error"}})
    with caplog.at_level(logging.WARNING), pytest.raises(httpx.HTTPStatusError):
        completion_content(response, "evaluate", "test-model", Evaluation.model_validate_json)
    assert '"http_status": 429' in caplog.text
    assert "private-provider-error" not in caplog.text


def test_network_timeout_is_logged_without_exception_text(caplog):
    with caplog.at_level(logging.WARNING):
        log_model_failure("evaluate", "test-model", 101, httpx.ReadTimeout("private-request-content"))
    assert "ReadTimeout" in caplog.text and "question_id=101" in caplog.text
    assert "private-request-content" not in caplog.text


def test_valid_completion_retains_evaluation_and_does_not_log_warning(caplog):
    content = json.dumps({"feedback": "Good answer", "criterion_results": [
        {"id": "c1", "status": "partial", "credit": 3, "evidence": "answer"}]})
    result = completion_content(response_with(content), "evaluate", "test-model", Evaluation.model_validate_json)
    assert result.criterion_results[0].credit == 3 and result.criterion_results[0].status == "partial"
    assert not caplog.records
