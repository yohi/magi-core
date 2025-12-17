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

    def test_plugin_load_timeout(self):
        """PLUGIN_LOAD_TIMEOUTが定義されていること"""
        from magi.errors import ErrorCode
        self.assertEqual(ErrorCode.PLUGIN_LOAD_TIMEOUT.value, "PLUGIN_004")

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


class TestErrorFactories(unittest.TestCase):
    """エラーファクトリ関数のテスト"""

    def test_create_config_error(self):
        """create_config_errorが正しいMagiErrorを作成すること"""
        from magi.errors import (
            create_config_error,
            MagiError,
            ErrorCode
        )
        message = "APIキーが設定されていません"
        details = {"key": "api_key"}
        error = create_config_error(message, details=details)

        # 返り値がMagiErrorのインスタンスであることを確認
        self.assertIsInstance(error, MagiError)

        # 属性が正しく設定されていることを確認
        self.assertEqual(error.message, message)
        self.assertEqual(error.code, ErrorCode.CONFIG_MISSING_API_KEY.value)
        self.assertEqual(error.details, details)
        self.assertFalse(error.recoverable)

    def test_create_api_error(self):
        """create_api_errorが正しいMagiErrorを作成すること"""
        from magi.errors import (
            create_api_error,
            MagiError,
            ErrorCode
        )
        code = ErrorCode.API_TIMEOUT
        message = "APIタイムアウトが発生しました"
        details = {"timeout": 60}
        recoverable = True
        error = create_api_error(code, message, details=details, recoverable=recoverable)

        # 返り値がMagiErrorのインスタンスであることを確認
        self.assertIsInstance(error, MagiError)

        # 属性が正しく設定されていることを確認
        self.assertEqual(error.message, message)
        self.assertEqual(error.code, code.value)
        self.assertEqual(error.details, details)
        self.assertTrue(error.recoverable)

    def test_create_plugin_error(self):
        """create_plugin_errorが正しいMagiErrorを作成すること"""
        from magi.errors import (
            create_plugin_error,
            MagiError,
            ErrorCode
        )
        code = ErrorCode.PLUGIN_YAML_PARSE_ERROR
        message = "YAMLの解析に失敗しました"
        details = {"file": "plugin.yaml", "line": 10}
        error = create_plugin_error(code, message, details=details)

        # 返り値がMagiErrorのインスタンスであることを確認
        self.assertIsInstance(error, MagiError)

        # 属性が正しく設定されていることを確認
        self.assertEqual(error.message, message)
        self.assertEqual(error.code, code.value)
        self.assertEqual(error.details, details)
        self.assertFalse(error.recoverable)

    def test_create_agent_error(self):
        """create_agent_errorが正しいMagiErrorを作成すること"""
        from magi.errors import (
            create_agent_error,
            MagiError,
            ErrorCode
        )
        message = "エージェントの思考処理に失敗しました"
        details = {"agent_id": "agent_001", "step": "thinking"}
        error = create_agent_error(message, details=details)

        # 返り値がMagiErrorのインスタンスであることを確認
        self.assertIsInstance(error, MagiError)

        # 属性が正しく設定されていることを確認
        self.assertEqual(error.message, message)
        self.assertEqual(error.code, ErrorCode.AGENT_THINKING_FAILED.value)
        self.assertEqual(error.details, details)
        self.assertTrue(error.recoverable)


if __name__ == "__main__":
    unittest.main()
