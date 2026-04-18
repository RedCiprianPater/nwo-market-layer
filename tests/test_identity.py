"""Tests for the identity service (mocked chain calls)."""
from __future__ import annotations
import os, hashlib, pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NWO_IDENTITY_REGISTRY", "0x78455AFd5E5088F8B5fecA0523291A75De1dAfF8")
os.environ.setdefault("NWO_PAYMENT_PROCESSOR", "0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c")
os.environ.setdefault("BASE_RPC_URL", "https://mainnet.base.org")
os.environ.setdefault("CARDIAC_RELAYER_URL", "https://nwo-relayer.onrender.com")


def test_serial_to_bytes32():
    from src.identity.service import _serial_to_bytes32
    result = _serial_to_bytes32("NWO-ROBOT-001")
    assert len(result) == 32
    assert isinstance(result, bytes)
    # Same input = same hash
    assert _serial_to_bytes32("NWO-ROBOT-001") == result


def test_firmware_to_bytes32():
    from src.identity.service import _firmware_to_bytes32
    result = _firmware_to_bytes32("v1.2.3", "abc123")
    assert len(result) == 32
    assert _firmware_to_bytes32("v1.2.3", "abc123") == result
    assert _firmware_to_bytes32("v1.2.4", "abc123") != result


def test_build_did_document():
    from src.identity.service import RobotIdentity, build_did_document
    identity = RobotIdentity(
        token_id=42,
        wallet="0xABCDEF0123456789" * 2 + "00",
        entity_type="robot",
        active=True,
        serial_hash="deadbeef" * 8,
        firmware_hash="cafebabe" * 8,
        enrolled_at=1700000000,
        has_api_key=True,
        has_hw_cert=True,
    )
    doc = build_did_document(identity)
    assert doc["id"] == "did:nwo:base:42"
    assert "@context" in doc
    assert "verificationMethod" in doc
    assert doc["nwo"]["token_id"] == 42
    assert doc["nwo"]["chain_id"] == 8453
    assert doc["credentials"]["api_key_valid"] is True


@pytest.mark.asyncio
async def test_register_robot_calls_relayer():
    from src.identity.service import register_robot_on_chain
    mock_response = {"rootTokenId": 99, "txHash": "0xabc123"}
    with patch("src.identity.service.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=MagicMock(status_code=200, json=lambda: mock_response, raise_for_status=lambda: None)
        )
        result = await register_robot_on_chain("0xWallet", "SN-001", "v1.0.0")
    assert result["token_id"] == 99
    assert result["tx_hash"] == "0xabc123"
    assert result["chain_id"] == 8453


@pytest.mark.asyncio
async def test_issue_task_auth_calls_relayer():
    from src.identity.service import issue_task_auth
    mock_response = {"txHash": "0xdef456", "sbtIndex": 3}
    with patch("src.identity.service.httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=MagicMock(status_code=200, json=lambda: mock_response, raise_for_status=lambda: None)
        )
        result = await issue_task_auth(42, "task-abc", duration_hours=2)
    assert result["root_token_id"] == 42
    assert result["task_id"] == "task-abc"
    assert result["tx_hash"] == "0xdef456"


def test_abis_are_valid():
    """All three contract ABIs are valid dicts with required fields."""
    from src.identity.abis import (
        IDENTITY_REGISTRY_ABI, ACCESS_CONTROLLER_ABI, PAYMENT_PROCESSOR_ABI
    )
    for abi in [IDENTITY_REGISTRY_ABI, ACCESS_CONTROLLER_ABI, PAYMENT_PROCESSOR_ABI]:
        assert isinstance(abi, list)
        assert len(abi) > 0
        for entry in abi:
            assert "name" in entry
            assert "type" in entry
