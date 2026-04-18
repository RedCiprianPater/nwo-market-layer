"""Tests for simulation, assembly AI, and token economy services."""
from __future__ import annotations
import os, json, pytest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SIMULATION_API_URL", "http://localhost:8090")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("NWO_PAYMENT_PROCESSOR", "0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c")
os.environ.setdefault("BASE_RPC_URL", "https://mainnet.base.org")
os.environ.setdefault("CARDIAC_RELAYER_URL", "https://nwo-relayer.onrender.com")
os.environ.setdefault("SETTLEMENT_MIN_CREDITS", "50")
os.environ.setdefault("SETTLEMENT_ETH_PER_CREDIT", "0.0001")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


# ── Simulation ─────────────────────────────────────────────────────────────────

class TestSimulation:

    def test_parse_result_passed(self):
        from src.simulation.service import _parse_result
        data = {
            "job_id": "sim-001",
            "status": "complete",
            "passed": True,
            "max_stress_mpa": 20.0,
            "yield_strength_mpa": 50.0,
        }
        result = _parse_result(data, "mujoco")
        assert result.job_id == "sim-001"
        assert result.passed is True
        assert result.safety_factor == pytest.approx(2.5)
        assert result.simulator == "mujoco"

    def test_parse_result_fails_on_low_safety_factor(self):
        from src.simulation.service import _parse_result
        data = {
            "job_id": "sim-002",
            "status": "complete",
            "passed": True,  # API says pass, but safety factor overrides
            "max_stress_mpa": 40.0,
            "yield_strength_mpa": 50.0,
        }
        result = _parse_result(data, "gazebo")
        assert result.safety_factor == pytest.approx(1.25)
        assert result.passed is False  # safety factor < 1.5 → fail

    def test_parse_result_with_stress_points(self):
        from src.simulation.service import _parse_result
        data = {
            "job_id": "sim-003",
            "status": "complete",
            "max_stress_mpa": 10.0,
            "stress_points": [
                {"location": [10.0, 5.0, 2.0], "stress_mpa": 8.0, "is_critical": False},
                {"location": [20.0, 1.0, 0.5], "stress_mpa": 10.0, "is_critical": True},
            ],
        }
        result = _parse_result(data, "mujoco")
        assert len(result.stress_points) == 2
        assert result.stress_points[1].is_critical is True

    def test_simulation_scenario_defaults(self):
        from src.simulation.service import SimulationScenario
        sc = SimulationScenario()
        assert sc.simulator == "mujoco"
        assert sc.gravity_ms2 == 9.81
        assert sc.applied_force_n == 10.0

    @pytest.mark.asyncio
    async def test_submit_raises_without_mesh(self):
        from src.simulation.service import submit_simulation
        with pytest.raises(ValueError, match="One of mesh_path"):
            await submit_simulation()


# ── Assembly AI ────────────────────────────────────────────────────────────────

class TestAssemblyAI:

    def test_fallback_instructions_structure(self):
        from src.assembly_ai.service import _fallback_instructions
        instructions = _fallback_instructions("part-001", "MG996R Bracket", 1, "joint")
        assert instructions.part_id == "part-001"
        assert instructions.part_name == "MG996R Bracket"
        assert len(instructions.steps) > 0
        assert len(instructions.bill_of_materials) > 0
        assert instructions.estimated_time_min > 0

    def test_fallback_to_dict(self):
        from src.assembly_ai.service import _fallback_instructions
        d = _fallback_instructions("p1", "Test Part", 1, "frame").to_dict()
        assert "steps" in d
        assert "bill_of_materials" in d
        assert "safety_notes" in d
        assert all(isinstance(s["step"], int) for s in d["steps"])

    @pytest.mark.asyncio
    async def test_generate_calls_claude_api(self):
        """generate_assembly_instructions calls Claude and parses the JSON response."""
        from src.assembly_ai.service import generate_assembly_instructions

        mock_json = {
            "estimated_time_min": 20,
            "difficulty": "medium",
            "tools_required": ["M3 hex key", "caliper"],
            "steps": [
                {"step": 1, "title": "Inspect", "description": "Check part", "tools": [], "torque_nm": None, "warnings": []}
            ],
            "bill_of_materials": [
                {"item": "Printed bracket", "quantity": 1, "specification": "PLA 30%", "source": "3d_printed"}
            ],
            "safety_notes": ["Wear gloves"],
            "compatible_parts": [],
            "storage_notes": "Keep dry",
        }

        mock_content = [{"type": "text", "text": json.dumps(mock_json)}]
        mock_response = {"content": mock_content}

        with patch("src.assembly_ai.service.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                )
            )
            result = await generate_assembly_instructions(
                part_id="p1", part_name="Test", part_version=1,
                description="A test part", category="joint", body_zone="arm",
                material_hints=["PLA"], print_settings={"infill_pct": 30},
                connector_standard="M3", bounding_box_mm=[50.0, 30.0, 20.0],
                mesh_vertices=1200, source_prompt=None, validation_report=None,
            )

        assert result.estimated_time_min == 20
        assert len(result.steps) == 1
        assert result.steps[0].title == "Inspect"
        assert result.bill_of_materials[0].source == "3d_printed"


# ── Token Economy ──────────────────────────────────────────────────────────────

class TestTokenEconomy:

    def test_credits_to_eth(self):
        from src.token_economy.settlement import credits_to_eth
        assert credits_to_eth(100) == pytest.approx(0.01)
        assert credits_to_eth(50) == pytest.approx(0.005)

    def test_eth_to_credits(self):
        from src.token_economy.settlement import eth_to_credits
        assert eth_to_credits(0.01) == 100
        assert eth_to_credits(0.005) == 50

    def test_credits_to_eth_inverse(self):
        from src.token_economy.settlement import credits_to_eth, eth_to_credits
        original = 250
        eth = credits_to_eth(original)
        back = eth_to_credits(eth)
        assert back == original

    def test_get_credit_rates_returns_all_keys(self):
        from src.token_economy.settlement import get_credit_rates
        rates = get_credit_rates()
        assert "simulate" in rates
        assert "design" in rates
        assert "part_download" in rates
        assert "skill_execution" in rates
        assert "print_job" in rates

    @pytest.mark.asyncio
    async def test_settle_below_minimum_fails(self):
        from src.token_economy.settlement import settle_credits
        result = await settle_credits("0xWallet", 10, "ref-test")  # 10 < 50 minimum
        assert result.success is False
        assert "Minimum" in result.error

    @pytest.mark.asyncio
    async def test_settle_calls_relayer(self):
        from src.token_economy.settlement import settle_credits
        mock_response = {"txHash": "0xsettlement123"}
        with patch("src.token_economy.settlement.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=MagicMock(
                    status_code=200,
                    json=lambda: mock_response,
                    raise_for_status=lambda: None,
                )
            )
            result = await settle_credits("0xWallet123", 100, "test-settlement")

        assert result.success is True
        assert result.credits_settled == 100
        assert result.eth_amount == pytest.approx(0.01)
        assert result.tx_hash == "0xsettlement123"
