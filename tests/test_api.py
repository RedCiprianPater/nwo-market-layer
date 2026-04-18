"""Integration tests for Layer 6 API routes."""
from __future__ import annotations
import os, json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("NWO_IDENTITY_REGISTRY", "0x78455AFd5E5088F8B5fecA0523291A75De1dAfF8")
os.environ.setdefault("NWO_ACCESS_CONTROLLER",  "0x29d177bedaef29304eacdc63b2d0285c459a0f50")
os.environ.setdefault("NWO_PAYMENT_PROCESSOR",  "0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c")
os.environ.setdefault("BASE_RPC_URL", "https://mainnet.base.org")
os.environ.setdefault("CARDIAC_RELAYER_URL", "https://nwo-relayer.onrender.com")
os.environ.setdefault("SIMULATION_API_URL", "http://localhost:8090")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SETTLEMENT_MIN_CREDITS", "50")
os.environ.setdefault("SETTLEMENT_ETH_PER_CREDIT", "0.0001")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from src.api.main import market_app

client = TestClient(market_app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert "contracts" in data
    assert data["contracts"]["chain_id"] == 8453


def test_root_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_credit_rates():
    r = client.get("/v1/market/tokens/rates")
    assert r.status_code == 200
    data = r.json()
    assert "earn" in data
    assert "spend" in data
    assert "settlement" in data
    assert data["settlement"]["min_credits"] == 50
    assert data["settlement"]["chain_id"] == 8453
    assert data["settlement"]["payment_processor"] == os.getenv("NWO_PAYMENT_PROCESSOR")


def test_settle_below_minimum():
    r = client.post("/v1/market/tokens/settle", json={
        "recipient_wallet": "0xWallet",
        "credits": 10,
        "reference_id": "test",
    })
    assert r.status_code == 400
    assert "Minimum" in r.json()["detail"]


def test_simulate_missing_mesh_returns_400():
    r = client.post("/v1/market/simulate", json={
        "simulator": "mujoco",
    })
    assert r.status_code == 400


def test_simulate_with_part_id():
    mock_result = {
        "job_id": "sim-test",
        "status": "complete",
        "passed": True,
        "max_stress_mpa": 15.0,
        "safety_factor": 3.33,
        "warnings": [],
        "recommendations": [],
        "stress_points": [],
    }
    with patch("src.api.routes.submit_simulation", new_callable=AsyncMock) as mock_sim:
        from src.simulation.service import SimulationResult, SimulationStatus
        mock_result_obj = MagicMock()
        mock_result_obj.to_dict.return_value = mock_result
        mock_sim.return_value = mock_result_obj

        r = client.post("/v1/market/simulate", json={
            "part_id": "part-abc123",
            "simulator": "mujoco",
        })

    assert r.status_code == 200
    assert r.json()["passed"] is True


def test_assembly_get_not_found():
    r = client.get("/v1/market/assembly/nonexistent-part-id")
    assert r.status_code == 404
    assert "POST" in r.json()["detail"]


def test_verify_credential_invalid_type():
    with patch("src.api.routes.verify_credential", side_effect=ValueError("Unknown credential type")):
        r = client.post("/v1/market/identity/verify-credential?token_id=1&credential_type=invalid_type")
    assert r.status_code == 400


def test_identity_resolve_not_found():
    with patch("src.api.routes.resolve_identity", new_callable=AsyncMock, return_value=None):
        r = client.get("/v1/market/identity/resolve/99999")
    assert r.status_code == 404


def test_identity_register_robot():
    mock_result = {
        "token_id": 7,
        "tx_hash": "0xabcdef",
        "wallet": "0xRobot",
        "serial_hash": "0x" + "aa" * 32,
        "firmware_hash": "0x" + "bb" * 32,
        "chain_id": 8453,
        "registry": os.getenv("NWO_IDENTITY_REGISTRY"),
        "message": "Robot registered on Base Mainnet. Soul-bound NFT minted.",
    }
    with patch("src.api.routes.register_robot_on_chain", new_callable=AsyncMock, return_value=mock_result):
        r = client.post("/v1/market/identity/register-robot", json={
            "robot_wallet":     "0xRobot",
            "serial_number":    "NWO-001",
            "firmware_version": "v1.0.0",
        })
    assert r.status_code == 200
    data = r.json()
    assert data["token_id"] == 7
    assert data["chain_id"] == 8453
