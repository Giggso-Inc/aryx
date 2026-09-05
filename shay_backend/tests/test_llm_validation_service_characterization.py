"""
Golden-master / characterization tests for app/services/llm_validation_service.py.

Purpose: this file had no dedicated direct-unit test coverage before this
pass (tests/test_token_details_characterization.py exercises these
functions only indirectly, through the /gpt-token-validation route, by
patching them out entirely). It is about to be split into a package (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Before the split, we
capture the CURRENT observable behavior of every public function directly,
so the split can be verified to change nothing.

These are characterization tests, not "correctness" tests: assertions match
what the code actually does today, bugs included.

Pattern follows tests/test_channels_characterization.py: no real network
calls (mocked at the exact import path used inside the module under test).

Do not modify app/services/llm_validation_service.py from this file's tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


MODPATH = "app.services.llm_validation_service"


# ---------------------------------------------------------------------------
# module-level availability flags / re-exports
# ---------------------------------------------------------------------------

def test_openai_available_flag_reflects_import():
    from app.services.llm_validation_service import OPENAI_AVAILABLE
    assert OPENAI_AVAILABLE is True


def test_gemini_available_flag_reflects_import():
    from app.services.llm_validation_service import GEMINI_AVAILABLE
    assert GEMINI_AVAILABLE is True


def test_langchain_available_flag_reflects_import():
    from app.services.llm_validation_service import LANGCHAIN_AVAILABLE
    assert LANGCHAIN_AVAILABLE is True


# ---------------------------------------------------------------------------
# updateAzureOpenAiChat
# ---------------------------------------------------------------------------

def test_update_azure_openai_chat_requires_package_when_unavailable():
    from app.services.llm_validation_service import updateAzureOpenAiChat
    with patch(f"{MODPATH}.azure.OPENAI_AVAILABLE", False):
        with pytest.raises(ImportError, match="openai package is required"):
            updateAzureOpenAiChat("prompt", "token", "deploy", "https://endpoint", "2024-01-01")


def test_update_azure_openai_chat_success():
    from app.services.llm_validation_service import updateAzureOpenAiChat

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="hello back"))]
    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(return_value=fake_response)

    with patch(f"{MODPATH}.azure.AzureOpenAI", return_value=fake_client) as mock_azure_cls:
        result = updateAzureOpenAiChat(
            "test prompt", "token-123", "gpt-4-deploy", "https://example.openai.azure.com", "2024-01-01"
        )

    mock_azure_cls.assert_called_once_with(
        api_key="token-123", api_version="2024-01-01", azure_endpoint="https://example.openai.azure.com"
    )
    fake_client.chat.completions.create.assert_called_once_with(
        model="gpt-4-deploy",
        messages=[{"role": "user", "content": "test prompt"}],
        max_tokens=10,
    )
    assert result == "hello back"


# ---------------------------------------------------------------------------
# updateOpenAiChat
# ---------------------------------------------------------------------------

def test_update_openai_chat_requires_package_when_unavailable():
    from app.services.llm_validation_service import updateOpenAiChat
    with patch(f"{MODPATH}.openai_chat.OPENAI_AVAILABLE", False):
        with pytest.raises(ImportError, match="openai package is required"):
            updateOpenAiChat("prompt", "key", "gpt-4")


def test_update_openai_chat_success():
    from app.services.llm_validation_service import updateOpenAiChat

    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="chat reply"))]
    fake_client = MagicMock()
    fake_client.chat.completions.create = MagicMock(return_value=fake_response)

    with patch(f"{MODPATH}.openai_chat.OpenAI", return_value=fake_client) as mock_openai_cls:
        result = updateOpenAiChat("hi", "sk-test", "gpt-3.5-turbo")

    mock_openai_cls.assert_called_once_with(api_key="sk-test")
    fake_client.chat.completions.create.assert_called_once_with(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
    )
    assert result == "chat reply"


# ---------------------------------------------------------------------------
# validate_gemini
# ---------------------------------------------------------------------------

def test_validate_gemini_requires_package_when_unavailable():
    from app.services.llm_validation_service import validate_gemini
    with patch(f"{MODPATH}.gemini.GEMINI_AVAILABLE", False):
        with pytest.raises(ImportError, match="google-generativeai package is required"):
            validate_gemini("key", "gemini-pro")


def test_validate_gemini_success_via_text_attribute():
    from app.services.llm_validation_service import validate_gemini

    fake_response = MagicMock()
    fake_response.text = "gemini says hi"
    fake_model_instance = MagicMock()
    fake_model_instance.generate_content = MagicMock(return_value=fake_response)

    with patch(f"{MODPATH}.gemini.genai") as mock_genai:
        mock_genai.GenerativeModel = MagicMock(return_value=fake_model_instance)
        result = validate_gemini("key-123", "gemini-pro", prompt="hello")

    mock_genai.configure.assert_called_once_with(api_key="key-123")
    mock_genai.GenerativeModel.assert_called_once_with("gemini-pro")
    fake_model_instance.generate_content.assert_called_once_with("hello")
    assert result == "gemini says hi"


def test_validate_gemini_falls_back_to_candidates_when_no_text():
    from app.services.llm_validation_service import validate_gemini

    fake_response = MagicMock()
    fake_response.text = None
    fake_part = MagicMock(text="from candidates")
    fake_content = MagicMock(parts=[fake_part])
    fake_candidate = MagicMock(content=fake_content)
    fake_response.candidates = [fake_candidate]
    fake_model_instance = MagicMock()
    fake_model_instance.generate_content = MagicMock(return_value=fake_response)

    with patch(f"{MODPATH}.gemini.genai") as mock_genai:
        mock_genai.GenerativeModel = MagicMock(return_value=fake_model_instance)
        result = validate_gemini("key-123", "gemini-pro")

    assert result == "from candidates"


def test_validate_gemini_default_prompt_used_when_not_provided():
    from app.services.llm_validation_service import validate_gemini

    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_model_instance = MagicMock()
    fake_model_instance.generate_content = MagicMock(return_value=fake_response)

    with patch(f"{MODPATH}.gemini.genai") as mock_genai:
        mock_genai.GenerativeModel = MagicMock(return_value=fake_model_instance)
        validate_gemini("key-123", "gemini-pro")

    fake_model_instance.generate_content.assert_called_once_with("This is a test prompt.")
