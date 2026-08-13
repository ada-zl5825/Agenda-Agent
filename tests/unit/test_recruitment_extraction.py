"""Unit tests for the sanitized Phase 4 application and LangChain boundaries."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from recruitment_agent.application.errors import ExtractionInputError, ExtractionInvocationError
from recruitment_agent.application.recruitment_extraction import (
    RecruitmentExtractionService,
    build_extraction_request,
)
from recruitment_agent.application.secure_email_processing import SecurePreparedEmail
from recruitment_agent.config.settings import AzureOpenAISettings
from recruitment_agent.email.models import (
    NormalizedEmail,
    PrefilterDecision,
    PrefilterResult,
)
from recruitment_agent.extraction.langchain_azure import (
    LangChainRecruitmentExtractionModel,
    _create_langchain_chat_model,
    _uses_foundry_v1,
    create_azure_recruitment_extraction_model,
)
from recruitment_agent.extraction.models import (
    ExtractionIssueCode,
    ExtractionValidationStatus,
    RecruitmentExtraction,
    RecruitmentExtractionRequest,
)
from recruitment_agent.extraction.validator import ExtractionValidator
from recruitment_agent.links.models import (
    ActionLinkType,
    EncryptedActionUrl,
    SecureLink,
)
from recruitment_agent.privacy.models import SanitizedContent

SOURCE_EMAIL_ID = UUID("00000000-0000-0000-0000-000000000401")


def _assessment_extraction() -> RecruitmentExtraction:
    fixture = json.loads(
        Path("tests/fixtures/extraction/assessment.json").read_text(encoding="utf-8")
    )
    return RecruitmentExtraction.model_validate(fixture["response"])


def _assessment_sanitized_text() -> str:
    fixture = json.loads(
        Path("tests/fixtures/extraction/assessment.json").read_text(encoding="utf-8")
    )
    return str(fixture["sanitized_text"])


def _prepared_email(*, sanitized_text: str) -> SecurePreparedEmail:
    normalized = NormalizedEmail(
        source_email_id=SOURCE_EMAIL_ID,
        graph_message_id="graph-message-4",
        internet_message_id=None,
        subject="Private candidate subject",
        sender_name="Recruiter",
        sender_address="recruiter@example.test",
        sender_domain="example.test",
        outer_sender_name=None,
        outer_sender_address=None,
        outer_sender_domain=None,
        received_at=datetime(2026, 8, 13, 8, tzinfo=UTC),
        body_text="Never expose https://assessment.example.test/start?token=raw-secret",
        outlook_web_link=None,
        has_attachments=False,
        is_forwarded=False,
    )
    link = SecureLink(
        id=UUID("00000000-0000-0000-0000-000000000402"),
        source_email_id=SOURCE_EMAIL_ID,
        ref="ACTION_LINK_01",
        link_type=ActionLinkType.ASSESSMENT,
        domain="assessment.example.test",
        encrypted_url=EncryptedActionUrl(
            ciphertext=b"encrypted-only",
            nonce=b"nonce-value12",
            key_version="v1",
        ),
        display_text="start assessment",
        created_at=datetime(2026, 8, 13, 8, tzinfo=UTC),
    )
    return SecurePreparedEmail(
        normalized=normalized,
        secure_links=(link,),
        sanitized=SanitizedContent(text=sanitized_text, redaction_counts={"email": 1}),
        prefilter=PrefilterResult(
            decision=PrefilterDecision.LIKELY_RECRUITMENT,
            matched_rules=("assessment",),
        ),
    )


class CapturingModel:
    def __init__(self, extraction: RecruitmentExtraction) -> None:
        self.extraction = extraction
        self.request: RecruitmentExtractionRequest | None = None

    async def extract(self, request: RecruitmentExtractionRequest) -> RecruitmentExtraction:
        self.request = request
        return self.extraction


class StaticRunnable:
    def __init__(self, result: object) -> None:
        self.result = result
        self.value: dict[str, object] | None = None

    async def ainvoke(self, value: dict[str, object]) -> object:
        self.value = value
        return self.result


class FailingRunnable:
    async def ainvoke(self, value: dict[str, object]) -> object:
        del value
        raise RuntimeError("provider leaked a private email body")


@pytest.mark.asyncio
async def test_service_sends_only_sanitized_text_and_opaque_refs_to_model() -> None:
    sanitized = f"{_assessment_sanitized_text()} Candidate: [REDACTED_EMAIL]."
    prepared = _prepared_email(sanitized_text=sanitized)
    model = CapturingModel(_assessment_extraction())

    outcome = await RecruitmentExtractionService(model=model).extract(prepared)

    assert outcome.validation.status is ExtractionValidationStatus.VALID
    assert model.request is not None
    assert model.request.sanitized_text == sanitized
    assert model.request.allowed_link_refs == ("ACTION_LINK_01",)
    assert "raw-secret" not in repr(model.request)
    assert "recruiter@example.test" not in repr(model.request)


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "Visit https://example.test/private",
        "Email mailto:private@example.test",
        "Continue at www.example.test/private",
        "Use ACTION_LINK_01?token=still-secret",
    ],
)
def test_input_guard_rejects_plaintext_url_material(unsafe_text: str) -> None:
    with pytest.raises(ExtractionInputError, match="forbidden URL fragment"):
        build_extraction_request(_prepared_email(sanitized_text=unsafe_text))


@pytest.mark.asyncio
async def test_langchain_adapter_passes_only_safe_prompt_values() -> None:
    extraction = _assessment_extraction()
    runnable = StaticRunnable(extraction.model_dump(mode="json"))
    adapter = LangChainRecruitmentExtractionModel(runnable=runnable)
    request = build_extraction_request(
        _prepared_email(sanitized_text=_assessment_sanitized_text())
    )

    result = await adapter.extract(request)

    assert result == extraction
    assert runnable.value is not None
    assert set(runnable.value) == {
        "allowed_link_refs",
        "prompt_version",
        "received_at",
        "sanitized_text",
    }
    assert "https://" not in str(runnable.value)
    assert "raw-secret" not in str(runnable.value)


@pytest.mark.asyncio
async def test_langchain_adapter_replaces_provider_failure_with_safe_error() -> None:
    adapter = LangChainRecruitmentExtractionModel(runnable=FailingRunnable())
    request = build_extraction_request(
        _prepared_email(sanitized_text="Assessment via ACTION_LINK_01")
    )

    with pytest.raises(ExtractionInvocationError, match="structured extraction failed") as raised:
        await adapter.extract(request)

    assert "private email body" not in str(raised.value)


def test_validator_rejects_model_hallucinated_link_reference() -> None:
    extraction = _assessment_extraction().model_copy(
        update={"action_link_ref": "ACTION_LINK_99"}
    )
    request = build_extraction_request(
        _prepared_email(sanitized_text=_assessment_sanitized_text())
    )

    validation = ExtractionValidator().validate(extraction, request)

    assert validation.status is ExtractionValidationStatus.INVALID
    assert [issue.code for issue in validation.issues] == [ExtractionIssueCode.UNKNOWN_LINK_REF]


def test_validator_rejects_ungrounded_company_evidence() -> None:
    extraction = _assessment_extraction().model_copy(update={"company_raw": "Invented Corp"})
    request = build_extraction_request(
        _prepared_email(
            sanitized_text=(
                "Nimbus Labs Graduate Engineer assessment by 18 August 2026 at 17:00 BST "
                "using ACTION_LINK_01."
            )
        )
    )

    validation = ExtractionValidator().validate(extraction, request)

    assert validation.status is ExtractionValidationStatus.INVALID
    assert validation.issues[0].code is ExtractionIssueCode.EVIDENCE_NOT_FOUND
    assert validation.issues[0].field == "company_raw"


def test_extraction_representation_excludes_source_evidence() -> None:
    extraction = _assessment_extraction()

    assert "Nimbus Labs" not in repr(extraction)
    assert "Graduate Engineer" not in repr(extraction)
    assert "18 August 2026" not in repr(extraction)


@pytest.mark.asyncio
async def test_azure_factory_composes_strict_model_without_api_key() -> None:
    settings = AzureOpenAISettings(
        llm_enabled=True,
        azure_openai_endpoint="https://openai.example.test",
        azure_openai_deployment="structured-model",
    )

    async def token_provider() -> str:
        return "managed-identity-token"

    adapter = create_azure_recruitment_extraction_model(settings, token_provider=token_provider)

    assert isinstance(adapter, LangChainRecruitmentExtractionModel)
    await adapter.aclose()


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://foundry.example.test/openai/v1", True),
        ("https://foundry.example.test/openai/v1/", True),
        ("https://classic.example.test", False),
        ("https://classic.example.test/openai/deployments/model", False),
    ],
)
def test_foundry_v1_endpoint_detection(endpoint: str, expected: bool) -> None:
    assert _uses_foundry_v1(endpoint) is expected


def test_foundry_v1_client_uses_deployment_as_model_and_async_token_provider() -> None:
    async def token_provider() -> str:
        return "managed-identity-token"

    model = _create_langchain_chat_model(
        endpoint="https://foundry.example.test/openai/v1",
        deployment="structured-model",
        api_version="unused-for-v1",
        token_provider=token_provider,
        timeout=30,
        max_retries=2,
    )

    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base == "https://foundry.example.test/openai/v1/"
    assert model.model_name == "structured-model"
    assert model.openai_api_key is token_provider


def test_classic_client_keeps_azure_deployment_route() -> None:
    async def token_provider() -> str:
        return "managed-identity-token"

    model = _create_langchain_chat_model(
        endpoint="https://classic.example.test",
        deployment="structured-model",
        api_version="2024-10-21",
        token_provider=token_provider,
        timeout=30,
        max_retries=2,
    )

    assert isinstance(model, AzureChatOpenAI)
    assert model.azure_endpoint == "https://classic.example.test"
    assert model.deployment_name == "structured-model"
    assert model.openai_api_version == "2024-10-21"
