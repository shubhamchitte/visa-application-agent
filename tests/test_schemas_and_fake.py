import pytest
from pydantic import ValidationError

from visa_agent.llm.base import Malformed, RateLimited
from visa_agent.llm.fake import FakeLLM
from visa_agent.schemas import Extraction, Field, FieldStatus, WritePlan


def test_field_with_evidence_ok():
    f = Field(value="UTO1234567", evidence_quote="Passport No. UTO1234567", page=1)
    assert f.status is FieldStatus.PROPOSED


def test_null_field_ok():
    assert Field().value is None


def test_one_field_without_evidence_does_not_sink_the_doc():
    ex = Extraction.model_validate({"doc_type": "passport", "fields": {
        "full_name": {"value": "ADA LOVE", "evidence_quote": "ADA LOVE", "page": 1},
        "email": {"value": "made@up.uto"}}})
    assert ex.fields["full_name"].has_evidence() and not ex.fields["email"].has_evidence()


def test_extra_keys_and_bad_page_rejected():
    with pytest.raises(ValidationError):
        Field(value="X", evidence_quote="X", page=1, confidence=0.99)
    with pytest.raises(ValidationError):
        Field(value="X", evidence_quote="X", page=0)


@pytest.mark.parametrize("status", ["APPROVED", "REJECTED"])
def test_writeplan_cannot_hold_forbidden_status(status):
    with pytest.raises(ValidationError):
        WritePlan(record_id="R1", status=status, reason="x")


GOOD = {"doc_type": "passport", "fields": {"full_name": {"value": "ADA LOVE", "evidence_quote": "ADA LOVE", "page": 1}}}


def test_fake_llm_returns_canned_and_validates():
    llm = FakeLLM("c1", {("c1", "passport"): [GOOD]})
    out = Extraction.model_validate(llm.extract("passport", "p", {}))
    assert out.fields["full_name"].value == "ADA LOVE"
    assert llm.calls == ["passport"]


def test_fake_llm_sequence_errors_then_ok():
    llm = FakeLLM("c13", {("c13", "form"): ["{not json", RateLimited(retry_after=1), GOOD]})
    with pytest.raises(Malformed):
        llm.extract("form", "p", {})
    with pytest.raises(RateLimited) as e:
        llm.extract("form", "p", {})
    assert e.value.retryable and e.value.retry_after == 1
    assert llm.extract("form", "p", {}) == GOOD
    assert llm.extract("form", "p", {}) == GOOD  # last item repeats


def test_fake_llm_unknown_doc_fails_loudly():
    with pytest.raises(KeyError):
        FakeLLM("c1", {}).extract("passport", "p", {})


def test_malformed_is_not_retryable():
    assert not Malformed().retryable
