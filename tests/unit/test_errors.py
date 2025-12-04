"""
エラー定義のユニットテスト

設計ドキュメントに基づいたエラー処理の検証
"""

import unittest


class TestErrorCode(unittest.TestCase):
    """ErrorCode列挙型のテスト"""

    def test_config_missing_api_key(self):
        """CONFIG_MISSING_API_KEYが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.CONFIG_MISSING_API_KEY.value, "CONFIG_001")

    def test_config_invalid_value(self):
        """CONFIG_INVALID_VALUEが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.CONFIG_INVALID_VALUE.value, "CONFIG_002")

    def test_api_timeout(self):
        """API_TIMEOUTが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.API_TIMEOUT.value, "API_001")

    def test_api_rate_limit(self):
        """API_RATE_LIMITが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.API_RATE_LIMIT.value, "API_002")

    def test_api_auth_error(self):
        """API_AUTH_ERRORが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.API_AUTH_ERROR.value, "API_003")

    def test_plugin_yaml_parse_error(self):
        """PLUGIN_YAML_PARSE_ERRORが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.PLUGIN_YAML_PARSE_ERROR.value, "PLUGIN_001")

    def test_plugin_command_failed(self):
        """PLUGIN_COMMAND_FAILEDが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.PLUGIN_COMMAND_FAILED.value, "PLUGIN_002")

    def test_plugin_command_timeout(self):
        """PLUGIN_COMMAND_TIMEOUTが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.PLUGIN_COMMAND_TIMEOUT.value, "PLUGIN_003")

    def test_agent_thinking_failed(self):
        """AGENT_THINKING_FAILEDが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.AGENT_THINKING_FAILED.value, "AGENT_001")


class TestMagiError(unittest.TestCase):
    """MagiErrorデータクラスのテスト"""

    def test_magi_error_creation(self):
        """MagiErrorが正しく作成されること"""
        from magi.errors import MagiError
        error = MagiError(
            code="CONFIG_001",
            message="APIキーが設定されていません"
        )
        self.assertEqual(error.code, "CONFIG_001")
        self.assertEqual(error.message, "APIキーが設定されていません")
        self.assertIsNone(error.details)
        self.assertFalse(error.recoverable)

    def test_magi_error_with_details(self):
        """MagiErrorがdetailsを含めて作成できること"""
        from magi.errors import MagiError
        error = MagiError(
            code="API_001",
            message="APIタイムアウト",
            details={"timeout": 60, "endpoint": "https://api.anthropic.com"},
            recoverable=True
        )
        self.assertEqual(error.code, "API_001")
        self.assertEqual(error.details["timeout"], 60)
        self.assertTrue(error.recoverable)


class TestMagiException(unittest.TestCase):
    """MagiException例外クラスのテスト"""

    def test_magi_exception_creation(self):
        """MagiExceptionが正しく作成されること"""
        from magi.errors import MagiException, MagiError
        error = MagiError(code="CONFIG_001", message="APIキーが設定されていません")
        exception = MagiException(error)
        self.assertEqual(exception.error.code, "CONFIG_001")
        self.assertIn("CONFIG_001", str(exception))

    def test_magi_exception_is_exception(self):
        """MagiExceptionがExceptionを継承していること"""
        from magi.errors import MagiException, MagiError
        error = MagiError(code="CONFIG_001", message="テスト")
        exception = MagiException(error)
        self.assertIsInstance(exception, Exception)


if __name__ == "__main__":
    unittest.main()
