"""LLMクライアントのプロパティベーステスト

**Feature: magi-core, Property 2: エラーメッセージ生成の一貫性**
**Validates: Requirements 2.3**

For any APIエラー種別に対して、LLM_Clientは対応する適切なエラーメッセージを生成する
"""
import unittest
from hypothesis import given, settings, strategies as st, assume

from magi.llm.client import LLMClient, APIErrorType
from magi.errors import ErrorCode, MagiError


class TestErrorMessageConsistency(unittest.TestCase):
    """エラーメッセージ生成の一貫性テスト

    **Feature: magi-core, Property 2: エラーメッセージ生成の一貫性**
    **Validates: Requirements 2.3**
    """

    @given(error_type=st.sampled_from(APIErrorType))
    @settings(max_examples=100)
    def test_error_type_produces_appropriate_error_code(self, error_type: APIErrorType):
        """各エラータイプに対して適切なエラーコードが生成される

        Property: For any APIエラー種別に対して、対応するErrorCodeが生成される
        """
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(error_type, Exception("test"))

        # エラーが生成されること
        self.assertIsInstance(error, MagiError)
        self.assertIsNotNone(error.code)
        self.assertIsNotNone(error.message)

        # エラータイプとエラーコードの対応を確認
        expected_codes = {
            APIErrorType.TIMEOUT: ErrorCode.API_TIMEOUT.value,
            APIErrorType.RATE_LIMIT: ErrorCode.API_RATE_LIMIT.value,
            APIErrorType.AUTH_ERROR: ErrorCode.API_AUTH_ERROR.value,
            APIErrorType.UNKNOWN: ErrorCode.API_TIMEOUT.value,  # UNKNOWNはタイムアウト扱い
        }
        self.assertEqual(error.code, expected_codes[error_type])

    @given(error_type=st.sampled_from(APIErrorType))
    @settings(max_examples=100)
    def test_error_message_is_not_empty(self, error_type: APIErrorType):
        """各エラータイプに対してメッセージが空でない

        Property: For any APIエラー種別に対して、空でないメッセージが生成される
        """
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(error_type, Exception("test"))

        self.assertIsInstance(error.message, str)
        self.assertTrue(len(error.message) > 0)

    @given(error_type=st.sampled_from(APIErrorType))
    @settings(max_examples=100)
    def test_recoverable_property_is_appropriate(self, error_type: APIErrorType):
        """各エラータイプに対してrecoverableプロパティが適切に設定される

        Property: タイムアウト・レート制限は復旧可能、認証エラーは復旧不可
        """
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(error_type, Exception("test"))

        # 認証エラーのみ復旧不可
        if error_type == APIErrorType.AUTH_ERROR:
            self.assertFalse(error.recoverable)
        else:
            self.assertTrue(error.recoverable)

    @given(error_type=st.sampled_from(APIErrorType))
    @settings(max_examples=100)
    def test_error_type_determines_error_uniquely(self, error_type: APIErrorType):
        """同じエラータイプに対して常に同じエラーコードが生成される

        Property: エラータイプからエラーコードへのマッピングは決定的
        """
        client = LLMClient(api_key="test-key")

        # 同じエラータイプで2回呼び出し
        error1 = client._create_error_for_type(error_type, Exception("test"))
        error2 = client._create_error_for_type(error_type, Exception("test"))

        # エラーコードは同一
        self.assertEqual(error1.code, error2.code)
        # 復旧可能フラグも同一
        self.assertEqual(error1.recoverable, error2.recoverable)

    @given(
        api_key=st.text(min_size=1, max_size=100),
        model=st.text(min_size=1, max_size=100),
        error_type=st.sampled_from(APIErrorType)
    )
    @settings(max_examples=100, deadline=None)
    def test_error_generation_is_independent_of_client_config(
        self,
        api_key: str,
        model: str,
        error_type: APIErrorType
    ):
        """エラー生成はクライアント設定に依存しない

        Property: For any クライアント設定に対して、同じエラータイプは同じエラーコードを生成
        """
        assume(api_key.strip())  # 空白のみのキーは除外
        assume(model.strip())    # 空白のみのモデル名は除外

        client = LLMClient(api_key=api_key, model=model)
        error = client._create_error_for_type(error_type, Exception("test"))

        # デフォルト設定のクライアントと比較
        default_client = LLMClient(api_key="default-key")
        default_error = default_client._create_error_for_type(error_type, Exception("test"))

        # エラーコードは設定に関係なく同一
        self.assertEqual(error.code, default_error.code)
        self.assertEqual(error.recoverable, default_error.recoverable)


class TestRetryBehaviorByErrorType(unittest.TestCase):
    """エラータイプによるリトライ動作のテスト

    **Feature: magi-core, Property 2: エラーメッセージ生成の一貫性**
    **Validates: Requirements 2.2, 2.3**
    """

    @given(error_type=st.sampled_from(APIErrorType))
    @settings(max_examples=100)
    def test_should_retry_is_consistent_with_recoverable(self, error_type: APIErrorType):
        """リトライ判定はrecoverableと一貫している

        Property: 認証エラー以外のrecoverableなエラーはリトライ対象
        認証エラー（AUTH_ERROR）はrecoverableではなく、リトライしない
        """
        client = LLMClient(api_key="test-key")
        error = client._create_error_for_type(error_type, Exception("test"))

        # 認証エラーはrecoverable=Falseで、リトライしない
        if error_type == APIErrorType.AUTH_ERROR:
            self.assertFalse(error.recoverable)
            should_retry = client._should_retry(error_type, attempt=0, retry_count=3)
            self.assertFalse(should_retry)
        else:
            # その他のエラーはrecoverable=Trueで、リトライ回数内ならリトライする
            self.assertTrue(error.recoverable)
            # retry_count=3のとき、attempt=0（まだリトライ可能）
            should_retry = client._should_retry(error_type, attempt=0, retry_count=3)
            self.assertTrue(should_retry)


if __name__ == "__main__":
    unittest.main()
