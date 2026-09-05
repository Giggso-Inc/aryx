"""
Golden-master / characterization tests for app/utils/file_validation.py.

Purpose: file_validation.py is 203 lines with zero dedicated test coverage
before this file. It is about to be split per
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md.

read_from_s3 is mocked at the boto3.client boundary — no real AWS calls.
Everything else is pure string/bytes processing exercised directly with
real inputs (fast, no mocking needed).

Do not modify app/utils/file_validation.py from this file's tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.utils.file_validation import (
    extract_section_headers,
    get_validation_summary,
    read_from_s3,
    validate_cloud_log_file,
    validate_file_content,
    validate_kubernetes_log_file,
    validate_log_file,
)

SAMPLE_LOG_WITH_HEADERS = (
    "some preamble\n"
    "------ INFO SECTION (details) ------\n"
    "log line 1\n"
    "------ ERROR SECTION (more details) ------\n"
    "log line 2\n"
)


# ---------------------------------------------------------------------------
# extract_section_headers
# ---------------------------------------------------------------------------
class TestExtractSectionHeaders:
    def test_extracts_matching_headers(self):
        headers, lines = extract_section_headers(SAMPLE_LOG_WITH_HEADERS)
        assert headers == [
            "------ INFO SECTION (details) ------",
            "------ ERROR SECTION (more details) ------",
        ]
        # SAMPLE_LOG_WITH_HEADERS ends with a trailing '\n', so split('\n')
        # yields a final empty-string element: 5 real lines + 1 empty = 6.
        assert len(lines) == 6

    def test_no_headers_returns_empty_list(self):
        headers, lines = extract_section_headers("just plain text\nno headers here\n")
        assert headers == []
        assert len(lines) == 3

    def test_empty_content(self):
        headers, lines = extract_section_headers("")
        assert headers == []
        assert lines == [""]

    def test_lowercase_section_name_not_matched(self):
        """Pre-existing quirk: the regex requires [A-Z]+ so lowercase section
        names are NOT matched."""
        headers, _ = extract_section_headers("------ info section (x) ------\n")
        assert headers == []


# ---------------------------------------------------------------------------
# read_from_s3
# ---------------------------------------------------------------------------
class TestReadFromS3:
    def test_returns_decoded_body_on_success(self):
        mock_body = MagicMock()
        mock_body.read.return_value = b"file content here"
        mock_client = MagicMock()
        mock_client.get_object.return_value = {"Body": mock_body}

        with patch("app.utils.file_validation.s3.boto3.client", return_value=mock_client) as mock_boto:
            result = read_from_s3("my-bucket", "key.txt", "AKID", "SECRET")

        assert result == "file content here"
        mock_boto.assert_called_once_with("s3", aws_access_key_id="AKID", aws_secret_access_key="SECRET")
        mock_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="key.txt")

    def test_reraises_on_client_error(self):
        with patch("app.utils.file_validation.s3.boto3.client", side_effect=Exception("no creds")):
            with pytest.raises(Exception, match="no creds"):
                read_from_s3("my-bucket", "key.txt", "AKID", "SECRET")


# ---------------------------------------------------------------------------
# validate_log_file
# ---------------------------------------------------------------------------
class TestValidateLogFile:
    def test_local_file_with_headers_returns_true(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text(SAMPLE_LOG_WITH_HEADERS, encoding="utf-8")
        result = validate_log_file({"storage_type": "local", "file_path": str(f)})
        assert result is True

    def test_local_file_missing_returns_false(self):
        result = validate_log_file({"storage_type": "local", "file_path": "/no/such/file.txt"})
        assert result is False

    def test_local_file_without_headers_returns_false(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("no headers at all\n", encoding="utf-8")
        result = validate_log_file({"storage_type": "local", "file_path": str(f)})
        assert result is False

    def test_s3_missing_params_returns_false(self):
        result = validate_log_file({"storage_type": "cloud", "storage_provider": "s3"})
        assert result is False

    def test_s3_with_headers_returns_true(self):
        with patch("app.utils.file_validation.validators.read_from_s3", return_value=SAMPLE_LOG_WITH_HEADERS):
            result = validate_log_file({
                "storage_type": "cloud",
                "storage_provider": "s3",
                "bucket_name": "b",
                "access_key": "a",
                "secret_key": "s",
                "s3_key": "k",
            })
        assert result is True

    def test_unsupported_storage_type_returns_false(self):
        assert validate_log_file({"storage_type": "ftp"}) is False

    def test_exception_is_swallowed_and_returns_false(self):
        with patch("app.utils.file_validation.validators.os.path.exists", side_effect=OSError("fs error")):
            result = validate_log_file({"storage_type": "local", "file_path": "/x"})
        assert result is False


# ---------------------------------------------------------------------------
# validate_file_content
# ---------------------------------------------------------------------------
class TestValidateFileContent:
    def test_valid_content_with_headers_returns_true(self):
        result = validate_file_content(SAMPLE_LOG_WITH_HEADERS.encode("utf-8"), "test.log")
        assert result is True

    def test_no_headers_and_not_kubernetes_or_cloud_returns_false(self):
        result = validate_file_content(b"plain text, no headers, not a log format", "test.txt")
        assert result is False

    def test_kubernetes_format_without_section_headers_still_valid(self):
        k8s_content = "2024-01-01 00:00:00 - INFO - app.py:42 - started up\n"
        result = validate_file_content(k8s_content.encode("utf-8"), "k8s.log")
        assert result is True

    def test_csv_extension_without_section_headers_still_valid(self):
        result = validate_file_content(b"col1,col2\n1,2\n", "data.csv")
        assert result is True

    def test_invalid_utf8_returns_false(self):
        result = validate_file_content(b"\xff\xfe\x00\x01", "bad.log")
        assert result is False


# ---------------------------------------------------------------------------
# get_validation_summary
# ---------------------------------------------------------------------------
class TestGetValidationSummary:
    def test_summary_for_valid_file(self):
        summary = get_validation_summary(SAMPLE_LOG_WITH_HEADERS.encode("utf-8"), "test.log")
        assert summary["filename"] == "test.log"
        assert summary["is_valid"] is True
        assert summary["section_headers_count"] == 2
        # Trailing '\n' in the sample yields a trailing empty line: 5 + 1 = 6.
        assert summary["total_lines"] == 6

    def test_summary_for_invalid_utf8_returns_error_summary(self):
        summary = get_validation_summary(b"\xff\xfe\x00\x01", "bad.log")
        assert summary["is_valid"] is False
        assert summary["section_headers_count"] == 0
        assert "Validation error" in summary["validation_message"]

    def test_summary_truncates_headers_to_10(self):
        # Pre-existing quirk: the section_pattern requires "[A-Z]+ " (letters
        # then a literal space) right after "------ ", so a section name with
        # a trailing digit directly abutting the space, like "SECTION3 (x)",
        # does NOT match — "SECTION" (all letters) is followed by "3", not a
        # space. Use a space-separated numbered word instead so it matches.
        content = "".join(f"------ SECTION NUM{i} (x) ------\n" for i in range(15))
        summary = get_validation_summary(content.encode("utf-8"), "many.log")
        assert summary["section_headers_count"] == 15
        assert len(summary["section_headers"]) == 10


# ---------------------------------------------------------------------------
# validate_kubernetes_log_file
# ---------------------------------------------------------------------------
class TestValidateKubernetesLogFile:
    def test_valid_kubernetes_format_returns_true(self):
        content = b"2024-01-01 00:00:00 - INFO - app.py:42 - started up\n"
        assert validate_kubernetes_log_file(content, "app.log") is True

    def test_no_matching_lines_returns_false(self):
        content = b"just some random text\nnothing structured\n"
        assert validate_kubernetes_log_file(content, "app.log") is False

    def test_mixed_valid_and_invalid_lines_returns_true(self):
        """any() short-circuits true if at least one line matches."""
        content = b"garbage line\n2024-01-01 00:00:00 - ERROR - app.py:1 - oops\n"
        assert validate_kubernetes_log_file(content, "app.log") is True


# ---------------------------------------------------------------------------
# validate_cloud_log_file
# ---------------------------------------------------------------------------
class TestValidateCloudLogFile:
    def test_csv_filename_returns_true(self):
        assert validate_cloud_log_file(b"anything", "data.csv") is True

    def test_non_csv_filename_returns_false(self):
        assert validate_cloud_log_file(b"anything", "data.log") is False
