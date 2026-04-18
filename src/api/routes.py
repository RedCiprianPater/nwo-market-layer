"""
FastAPI routes for the NWO Market Layer (Layer 6).
All endpoints mount under /v1/market/ on the Layer 5 gateway.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..assembly_ai.cache import get_cached, set_cached
from ..assembly_ai.service import generate_assembly_instructions
from ..identity.service import (
    build_did_document,
    issue_task_auth,
    register_agent_on_chain,
    register_robot_on_chain,
    resolve_by_wallet,
    resolve_identity,
    verify_credential,
)
from ..simulation.service import SimulationScenario, get_simulation_status, submit_simulation
from ..token_economy.settlement import (
    get_credit_rates,
    get_onchain_balance,
    get_payment_history,
    robot_to_robot_payment,
    settle_credits,
    credits_to_eth,
)

router = APIRouter(prefix="/v1/market")

_LAYER2_URL = os.getenv("LAYER2_URL", "http://localhost:8001")


# ── Request / response models ─────────────────────────────────────────────────

class RegisterRobotRequest(BaseModel):
    robot_wallet: str = Field(..., description="Robot's Ethereum wallet address on Base")
    serial_number: str = Field(..., description="Physical serial number")
    firmware_version: str = Field(..., description="Current firmware version string")
    firmware_hash: str = Field(default="", description="Optional SHA-256 of firmware binary")


class RegisterAgentRequest(BaseModel):
    agent_wallet: str
    api_key_hash: str = Field(..., description="hex keccak256 of the agent's API key")


class IssueTaskAuthRequest(BaseModel):
    root_token_id: int = Field(..., description="rootTokenId from NWOIdentityRegistry")
    task_id: str = Field(..., description="Platform task ID to authorize")
    duration_hours: int = Field(default=1, ge=1, le=168)


class SimulateRequest(BaseModel):
    mesh_url: str | None = None
    part_id: str | None = None
    simulator: str = Field(default="mujoco", pattern="^(mujoco|gazebo)$")
    applied_force_n: float = Field(default=10.0, ge=0.1)
    applied_torque_nm: float = Field(default=2.0, ge=0.0)
    material_density_kg_m3: float = Field(default=1240.0)
    youngs_modulus_gpa: float = Field(default=3.5)
    simulation_steps: int = Field(default=1000, ge=100, le=10000)


class AssemblyRequest(BaseModel):
    part_id: str
    force_regenerate: bool = False


class SettleRequest(BaseModel):
    recipient_wallet: str = Field(..., description="Base Mainnet wallet to receive ETH")
    credits: int = Field(..., ge=50, description="Credits to settle (minimum 50)")
    reference_id: str = Field(default="manual_settlement")


class RobotPaymentRequest(BaseModel):
    from_wallet: str
    to_wallet: str
    credits: int = Field(..., ge=1)
    reference_id: str


# ── Identity endpoints ─────────────────────────────────────────────────────────

@router.post("/identity/register-robot", tags=["Identity"])
async def register_robot(req: RegisterRobotRequest):
    """
    Register a robot on Base Mainnet via the NWO Cardiac Relayer (gasless).
    Mints a soul-bound NFT (NWOID) on the NWOIdentityRegistry contract.
    Returns the rootTokenId — store this as the robot's on-chain identity.
    """
    try:
        result = await register_robot_on_chain(
            robot_wallet=req.robot_wallet,
            serial_number=req.serial_number,
            firmware_version=req.firmware_version,
            firmware_hash=req.firmware_hash,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Registration failed: {e}")


@router.post("/identity/register-agent", tags=["Identity"])
async def register_agent(req: RegisterAgentRequest):
    """Register an AI agent on Base Mainnet."""
    try:
        return await register_agent_on_chain(req.agent_wallet, req.api_key_hash)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Agent registration failed: {e}")


@router.get("/identity/resolve/{token_id}", tags=["Identity"])
async def resolve_robot_identity(token_id: int):
    """
    Resolve a robot identity from the NWOIdentityRegistry contract on Base.
    Returns the full DID document + on-chain credential status.
    """
    try:
        identity = await resolve_identity(token_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Chain read failed: {e}")

    if not identity:
        raise HTTPException(status_code=404, detail=f"Token {token_id} not found or inactive")

    did_doc = build_did_document(identity)
    return {
        "did_document": did_doc,
        "identity": {
            "token_id":    identity.token_id,
            "wallet":      identity.wallet,
            "entity_type": identity.entity_type,
            "active":      identity.active,
            "has_api_key": identity.has_api_key,
            "has_hw_cert": identity.has_hw_cert,
            "enrolled_at": identity.enrolled_at,
        },
    }


@router.get("/identity/resolve-wallet/{wallet}", tags=["Identity"])
async def resolve_by_wallet_address(wallet: str):
    """Look up a rootTokenId by Ethereum wallet address."""
    token_id = await resolve_by_wallet(wallet)
    if not token_id:
        raise HTTPException(status_code=404, detail=f"No identity found for wallet {wallet}")
    return {"wallet": wallet, "token_id": token_id}


@router.post("/identity/verify-credential", tags=["Identity"])
async def verify_robot_credential(
    token_id: int = Query(...),
    credential_type: str = Query(..., description="api_key|task_auth|hw_cert|firmware|access|payment"),
):
    """
    Verify that a robot/agent holds a valid SBT credential on-chain.
    Reads directly from Base Mainnet — no relayer needed.
    """
    try:
        result = await verify_credential(token_id, credential_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Credential check failed: {e}")

    return {
        "token_id":        result.token_id,
        "credential_type": result.credential_type,
        "is_valid":        result.is_valid,
        "checked_at_block": result.checked_at_block,
        "chain_id":        8453,
        "registry":        os.getenv("NWO_IDENTITY_REGISTRY"),
    }


@router.post("/identity/issue-task-auth", tags=["Identity"])
async def issue_task_authorization(req: IssueTaskAuthRequest):
    """
    Issue a CRED_TASK_AUTH SBT to authorize a robot to execute a specific task.
    Allows an agent to act on behalf of a robot for a bounded time window.
    """
    try:
        return await issue_task_auth(req.root_token_id, req.task_id, req.duration_hours)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Credential issuance failed: {e}")


# ── Simulation endpoints ───────────────────────────────────────────────────────

@router.post("/simulate", tags=["Simulation"])
async def simulate_part(req: SimulateRequest):
    """
    Submit a part to the nwo-simulation-api for physics analysis.
    Returns pass/fail verdict + safety factor before printing.
    Costs SIMULATE_CREDIT_COST credits (deducted from caller's L5 balance).
    """
    if not req.mesh_url and not req.part_id:
        raise HTTPException(status_code=400, detail="Provide mesh_url or part_id")

    scenario = SimulationScenario(
        simulator=req.simulator,
        applied_force_n=req.applied_force_n,
        applied_torque_nm=req.applied_torque_nm,
        material_density_kg_m3=req.material_density_kg_m3,
        youngs_modulus_gpa=req.youngs_modulus_gpa,
        simulation_steps=req.simulation_steps,
    )

    try:
        result = await submit_simulation(
            mesh_url=req.mesh_url,
            part_id=req.part_id,
            scenario=scenario,
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Simulation API error: {e}")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Simulation failed: {e}")

    return result.to_dict()


@router.post("/simulate/file", tags=["Simulation"])
async def simulate_uploaded_file(
    file: UploadFile = File(...),
    simulator: str = Query(default="mujoco"),
    applied_force_n: float = Query(default=10.0),
    applied_torque_nm: float = Query(default=2.0),
):
    """Submit an uploaded STL/3MF file directly for simulation."""
    import tempfile
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "part.stl").suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    scenario = SimulationScenario(
        simulator=simulator,
        applied_force_n=applied_force_n,
        applied_torque_nm=applied_torque_nm,
    )

    try:
        result = await submit_simulation(mesh_path=tmp_path, scenario=scenario)
    finally:
        tmp_path.unlink(missing_ok=True)

    return result.to_dict()


@router.get("/simulate/{job_id}", tags=["Simulation"])
async def get_simulation(job_id: str):
    """Poll simulation result by job ID."""
    try:
        result = await get_simulation_status(job_id)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# ── Assembly AI endpoints ─────────────────────────────────────────────────────

@router.post("/assembly/instructions", tags=["Assembly AI"])
async def generate_instructions(req: AssemblyRequest):
    """
    Generate step-by-step assembly instructions and BOM for a part.
    Fetches part metadata from Layer 2 gallery, then calls Claude API.
    Results are cached for ASSEMBLY_CACHE_TTL_HOURS hours.
    """
    # Check cache first
    if not req.force_regenerate:
        cached = await get_cached(req.part_id, 0)   # version 0 = any latest
        if cached:
            return {**cached, "cached": True}

    # Fetch part metadata from Layer 2
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{_LAYER2_URL}/parts/{req.part_id}")
            if r.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Part {req.part_id} not found in gallery")
            r.raise_for_status()
            part = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Could not fetch part from gallery: {e}")

    # Generate instructions
    try:
        instructions = await generate_assembly_instructions(
            part_id=req.part_id,
            part_name=part.get("name", "Unknown Part"),
            part_version=part.get("version", 1),
            description=part.get("description"),
            category=part.get("category", "other"),
            body_zone=part.get("body_zone"),
            material_hints=part.get("material_hints", []),
            print_settings={
                "infill_pct":       part.get("infill_pct"),
                "supports_required":part.get("supports_required", False),
                "layer_height_mm":  part.get("layer_height_mm"),
            },
            connector_standard=part.get("connector_standard"),
            bounding_box_mm=part.get("bounding_box_mm"),
            mesh_vertices=part.get("mesh_vertices"),
            source_prompt=part.get("source_prompt"),
            validation_report=part.get("validation_report"),
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Assembly AI generation failed: {e}")

    result = instructions.to_dict()

    # Cache result
    await set_cached(req.part_id, instructions.part_version, result)

    return {**result, "cached": False}


@router.get("/assembly/{part_id}", tags=["Assembly AI"])
async def get_assembly_instructions(part_id: str):
    """
    Get cached assembly instructions for a part.
    Returns 404 if not yet generated — call POST /assembly/instructions to generate.
    """
    cached = await get_cached(part_id, 0)
    if not cached:
        raise HTTPException(
            status_code=404,
            detail=f"No assembly instructions for part {part_id}. "
                   f"POST /v1/market/assembly/instructions to generate.",
        )
    return {**cached, "cached": True}


# ── Token economy endpoints ────────────────────────────────────────────────────

@router.get("/tokens/rates", tags=["Token Economy"])
async def credit_rates():
    """Return current credit earn/spend rates for all platform actions."""
    rates = get_credit_rates()
    return {
        "earn": {
            "part_downloaded":  rates["part_download"],
            "skill_executed":   rates["skill_execution"],
            "print_job_used":   rates["print_job"],
            "registration_bonus": rates["registration"],
        },
        "spend": {
            "generate_part":    rates["design"],
            "slice_file":       rates["slice"],
            "run_skill":        rates["skill_run"],
            "simulate_part":    rates["simulate"],
        },
        "settlement": {
            "min_credits":              int(os.getenv("SETTLEMENT_MIN_CREDITS", "50")),
            "eth_per_credit":           float(os.getenv("SETTLEMENT_ETH_PER_CREDIT", "0.0001")),
            "payment_processor":        os.getenv("NWO_PAYMENT_PROCESSOR"),
            "chain_id":                 8453,
        },
    }


@router.get("/tokens/balance/{wallet}", tags=["Token Economy"])
async def token_balance(wallet: str):
    """
    Return on-chain ETH balance + equivalent credit value for a wallet on Base Mainnet.
    The off-chain credit balance lives in Layer 5 (/v1/tokens/balance/{did}).
    """
    eth_balance = await get_onchain_balance(wallet)
    credit_equivalent = int(eth_balance / float(os.getenv("SETTLEMENT_ETH_PER_CREDIT", "0.0001")))
    return {
        "wallet":               wallet,
        "chain_id":             8453,
        "eth_balance":          eth_balance,
        "credit_equivalent":    credit_equivalent,
        "payment_processor":    os.getenv("NWO_PAYMENT_PROCESSOR"),
        "note": "Off-chain credit balance: GET /v1/tokens/balance/{did} on the Layer 5 gateway",
    }


@router.post("/tokens/settle", tags=["Token Economy"])
async def settle_to_eth(req: SettleRequest):
    """
    Settle off-chain credits to ETH on Base Mainnet via NWOPaymentProcessor.
    Minimum settlement: 50 credits.
    The off-chain ledger must be debited separately by the caller's integration.
    """
    result = await settle_credits(
        recipient_wallet=req.recipient_wallet,
        credits=req.credits,
        reference_id=req.reference_id,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.to_dict()


@router.post("/tokens/robot-payment", tags=["Token Economy"])
async def robot_payment(req: RobotPaymentRequest):
    """
    Direct robot-to-robot payment via NWOPaymentProcessor on Base.
    The sending robot must have sufficient ETH balance on Base.
    """
    result = await robot_to_robot_payment(
        from_wallet=req.from_wallet,
        to_wallet=req.to_wallet,
        credits=req.credits,
        reference_id=req.reference_id,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.to_dict()


@router.get("/tokens/history/{wallet}", tags=["Token Economy"])
async def payment_history(wallet: str):
    """
    Get on-chain payment history for a wallet from NWOPaymentProcessor.
    """
    records = await get_payment_history(wallet)
    return {
        "wallet": wallet,
        "chain_id": 8453,
        "payment_processor": os.getenv("NWO_PAYMENT_PROCESSOR"),
        "history": [
            {
                "from":       r.from_wallet,
                "to":         r.to_wallet,
                "amount_eth": r.amount_eth,
                "credits_equivalent": int(r.amount_eth / float(os.getenv("SETTLEMENT_ETH_PER_CREDIT", "0.0001"))),
                "reference":  r.reference,
                "timestamp":  r.timestamp,
                "tx_hash":    r.tx_hash,
            }
            for r in records
        ],
    }


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["System"])
async def market_health():
    """Check Layer 6 service health including chain connectivity."""
    chain_ok = False
    block = None
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(os.getenv("BASE_RPC_URL", "https://mainnet.base.org")))
        block = w3.eth.block_number
        chain_ok = block > 0
    except Exception:
        pass

    relayer_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{os.getenv('CARDIAC_RELAYER_URL', 'https://nwo-relayer.onrender.com')}/health")
            relayer_ok = r.status_code == 200
    except Exception:
        pass

    sim_ok = False
    sim_url = os.getenv("SIMULATION_API_URL", "")
    if sim_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{sim_url}/health")
                sim_ok = r.status_code == 200
        except Exception:
            pass

    return {
        "status": "ok" if chain_ok else "degraded",
        "services": {
            "base_mainnet":   {"ok": chain_ok, "latest_block": block, "chain_id": 8453},
            "cardiac_relayer": {"ok": relayer_ok, "url": os.getenv("CARDIAC_RELAYER_URL")},
            "simulation_api":  {"ok": sim_ok, "url": sim_url or "not configured"},
            "assembly_ai":    {"ok": bool(os.getenv("ANTHROPIC_API_KEY")), "model": os.getenv("ASSEMBLY_AI_MODEL")},
        },
        "contracts": {
            "NWOIdentityRegistry": os.getenv("NWO_IDENTITY_REGISTRY"),
            "NWOAccessController": os.getenv("NWO_ACCESS_CONTROLLER"),
            "NWOPaymentProcessor": os.getenv("NWO_PAYMENT_PROCESSOR"),
        },
    }
