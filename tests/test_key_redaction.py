"""
Unit tests for API key redaction functionality
"""

import unittest
import logging
from unittest.mock import patch, MagicMock

from app.utils.helpers import redact_key_for_logging
from app.log.logger import AccessLogFormatter


class TestKeyRedaction(unittest.TestCase):
    """Test cases for the redact_key_for_logging function"""

    def test_valid_long_key_redaction(self):
        """Test redaction of valid long API keys"""
        # Test Google/Gemini API key
        # This value is a random generated string for testing
        gemini_key = "AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI"
        result = redact_key_for_logging(gemini_key)
        expected = "AIzaSy...xDfGhI"
        self.assertEqual(result, expected)

        # Test OpenAI API key
        # This value is a random generated string for testing
        openai_key = "sk-1234567890abcdef1234567890abcdef1234567890abcdef"
        result = redact_key_for_logging(openai_key)
        expected = "sk-123...abcdef"
        self.assertEqual(result, expected)

    def test_short_key_handling(self):
        """Test handling of short keys"""
        short_key = "short"
        result = redact_key_for_logging(short_key)
        self.assertEqual(result, "[SHORT_KEY]")

        # Test exactly 12 characters (boundary case)
        boundary_key = "123456789012"
        result = redact_key_for_logging(boundary_key)
        self.assertEqual(result, "[SHORT_KEY]")

    def test_empty_and_none_keys(self):
        """Test handling of empty and None keys"""
        # Test empty string
        result = redact_key_for_logging("")
        self.assertEqual(result, "[INVALID_KEY]")

        # Test None
        result = redact_key_for_logging(None)
        self.assertEqual(result, "[INVALID_KEY]")

    def test_invalid_input_types(self):
        """Test handling of invalid input types"""
        # Test integer
        result = redact_key_for_logging(123)
        self.assertEqual(result, "[INVALID_KEY]")

        # Test list
        result = redact_key_for_logging(["key"])
        self.assertEqual(result, "[INVALID_KEY]")

        # Test dict
        result = redact_key_for_logging({"key": "value"})
        self.assertEqual(result, "[INVALID_KEY]")

    def test_boundary_cases(self):
        """Test boundary cases for key length"""
        # Test 13 characters (just above the threshold)
        key_13 = "1234567890123"
        result = redact_key_for_logging(key_13)
        expected = "123456...890123"
        self.assertEqual(result, expected)

        # Test very long key
        long_key = "a" * 100
        result = redact_key_for_logging(long_key)
        expected = "aaaaaa...aaaaaa"
        self.assertEqual(result, expected)


class TestAccessLogFormatter(unittest.TestCase):
    """Test cases for the AccessLogFormatter class"""

    def setUp(self):
        """Set up test fixtures"""
        self.formatter = AccessLogFormatter()

    def test_gemini_key_redaction_in_url(self):
        """Test redaction of Gemini API keys in URLs"""
        log_message = (
            'POST /verify-key/AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI HTTP/1.1" 200'
        )
        result = self.formatter._redact_api_keys_in_message(log_message)
        self.assertIn("AIzaSy...xDfGhI", result)
        self.assertNotIn("AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI", result)

    def test_openai_key_redaction_in_url(self):
        """Test redaction of OpenAI API keys in URLs"""
        log_message = 'GET /api/models?key=sk-1234567890abcdef1234567890abcdef1234567890abcdef HTTP/1.1" 200'
        result = self.formatter._redact_api_keys_in_message(log_message)
        self.assertIn("sk-123...abcdef", result)
        self.assertNotIn("sk-1234567890abcdef1234567890abcdef1234567890abcdef", result)

    def test_multiple_keys_in_message(self):
        """Test redaction of multiple API keys in a single message"""
        log_message = "Request with keys: AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI and sk-1234567890abcdef1234567890abcdef1234567890abcdef"
        result = self.formatter._redact_api_keys_in_message(log_message)
        self.assertIn("AIzaSy...xDfGhI", result)
        self.assertIn("sk-123...abcdef", result)
        self.assertNotIn("AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI", result)
        self.assertNotIn("sk-1234567890abcdef1234567890abcdef1234567890abcdef", result)

    def test_no_keys_in_message(self):
        """Test that messages without API keys are unchanged"""
        log_message = 'GET /api/health HTTP/1.1" 200'
        result = self.formatter._redact_api_keys_in_message(log_message)
        self.assertEqual(result, log_message)

    def test_partial_key_patterns_not_redacted(self):
        """Test that partial key patterns are not redacted"""
        log_message = "Message with partial patterns: AIza sk- incomplete"
        result = self.formatter._redact_api_keys_in_message(log_message)
        self.assertEqual(result, log_message)

    def test_error_handling_in_redaction(self):
        """Test error handling in the redaction process"""
        # Test by directly calling _redact_api_keys_in_message with a broken pattern
        original_patterns = self.formatter.compiled_patterns
        # Create a mock pattern that will raise an exception
        mock_pattern = MagicMock()
        mock_pattern.sub.side_effect = Exception("Regex error")
        self.formatter.compiled_patterns = [mock_pattern]

        try:
            log_message = (
                'POST /verify-key/AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI HTTP/1.1" 200'
            )
            result = self.formatter._redact_api_keys_in_message(log_message)
            self.assertEqual(result, "[LOG_REDACTION_ERROR]")
        finally:
            # Restore original patterns
            self.formatter.compiled_patterns = original_patterns

    def test_format_method(self):
        """Test the format method of AccessLogFormatter"""
        # Create a mock log record
        record = MagicMock()
        record.getMessage.return_value = (
            'POST /verify-key/AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI HTTP/1.1" 200'
        )

        # Mock the parent format method
        with patch(
            "logging.Formatter.format",
            return_value='2025-01-01 12:00:00 | INFO | POST /verify-key/AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI HTTP/1.1" 200',
        ):
            result = self.formatter.format(record)
            self.assertIn("AIzaSy...xDfGhI", result)
            self.assertNotIn("AIzaSyDhKGfJ8xYzQwErTyUiOpLkMnBvCxDfGhI", result)

    def test_regex_patterns_compilation(self):
        """Test that regex patterns are properly compiled"""
        formatter = AccessLogFormatter()
        self.assertEqual(len(formatter.compiled_patterns), 2)
        self.assertTrue(
            all(hasattr(pattern, "sub") for pattern in formatter.compiled_patterns)
        )

    def test_flexible_openai_pattern(self):
        """Test the flexible OpenAI pattern matches various formats"""
        test_cases = [
            "sk-1234567890abcdef1234567890abcdef1234567890abcdef",  # Standard 48 chars
            "sk-proj-1234567890abcdef1234567890abcdef1234567890abcdef",  # Project key
            "sk-1234567890abcdef_1234567890abcdef-1234567890abcdef",  # With underscores/hyphens
            "sk-12345678901234567890",  # Shorter key (20 chars)
        ]

        for test_key in test_cases:
            log_message = f"Request with key: {test_key}"
            result = self.formatter._redact_api_keys_in_message(log_message)
            self.assertNotIn(test_key, result)
            self.assertIn("sk-", result)  # Should still contain the prefix


if __name__ == "__main__":
    unittest.main()
