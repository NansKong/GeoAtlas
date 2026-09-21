import pytest
from unittest.mock import AsyncMock, patch

from core.firebase_auth import verify_firebase_id_token
from modules.users.schemas import FirebaseLoginRequest


@pytest.mark.asyncio
async def test_verify_empty_or_invalid_token():
    assert await verify_firebase_id_token("") is None
    assert await verify_firebase_id_token(None) is None
    assert await verify_firebase_id_token("invalid.token.structure") is None


@pytest.mark.asyncio
async def test_verify_valid_tokeninfo_response():
    mock_tokeninfo = {
        "aud": "test-geoatlas-project",
        "email": "trader@example.com",
        "sub": "firebase_uid_12345",
        "name": "Jane Doe",
        "picture": "https://example.com/avatar.jpg",
        "email_verified": "true",
    }

    class MockResponse:
        status_code = 200

        def json(self):
            return mock_tokeninfo

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MockResponse()
        with patch("core.firebase_auth.settings.FIREBASE_PROJECT_ID", "test-geoatlas-project"):
            claims = await verify_firebase_id_token("mock_valid_id_token")
            assert claims is not None
            assert claims["email"] == "trader@example.com"
            assert claims["uid"] == "firebase_uid_12345"
            assert claims["name"] == "Jane Doe"
            assert claims["email_verified"] is True


@pytest.mark.asyncio
async def test_verify_audience_mismatch_rejected():
    mock_tokeninfo = {
        "aud": "wrong-project-id",
        "email": "trader@example.com",
        "sub": "firebase_uid_12345",
    }

    class MockResponse:
        status_code = 200

        def json(self):
            return mock_tokeninfo

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = MockResponse()
        with patch("core.firebase_auth.settings.FIREBASE_PROJECT_ID", "expected-project-id"):
            claims = await verify_firebase_id_token("mock_token_wrong_aud")
            assert claims is None


def test_firebase_login_schema():
    req = FirebaseLoginRequest(id_token="header.payload.signature")
    assert req.id_token == "header.payload.signature"
