"""
Identity service — integrates the NWO Cardiac SDK with Layer 6.

Responsibilities:
  1. Register robots on Base Mainnet via the Relayer (gasless)
  2. Resolve robot identities from the IdentityRegistry contract
  3. Verify SBT credentials (CRED_API_KEY, CRED_TASK_AUTH, CRED_HW_CERT)
  4. Issue CRED_TASK_AUTH for agent delegation
  5. Attach on-chain rootTokenId to all published parts/skills as provenance

Architecture:
  - Read-only calls go directly to Base Mainnet RPC (fast, free)
  - Write calls go through the Cardiac Relayer (gasless meta-transactions)
  - Oracle is called only for ECG/cardiac validation (not needed for robots)
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

import httpx
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from .abis import ACCESS_CONTROLLER_ABI, IDENTITY_REGISTRY_ABI, PAYMENT_PROCESSOR_ABI

# ── Config ─────────────────────────────────────────────────────────────────────
_RELAYER_URL = os.getenv("CARDIAC_RELAYER_URL", "https://nwo-relayer.onrender.com")
_ORACLE_URL  = os.getenv("CARDIAC_ORACLE_URL",  "https://nwo-oracle.onrender.com")
_RELAYER_SECRET = os.getenv("CARDIAC_RELAYER_SECRET", "")
_ORACLE_SECRET  = os.getenv("CARDIAC_ORACLE_SECRET", "")

_BASE_RPC    = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
_CHAIN_ID    = int(os.getenv("BASE_CHAIN_ID", "8453"))

_REGISTRY_ADDR    = os.getenv("NWO_IDENTITY_REGISTRY", "0x78455AFd5E5088F8B5fecA0523291A75De1dAfF8")
_ACCESS_ADDR      = os.getenv("NWO_ACCESS_CONTROLLER",  "0x29d177bedaef29304eacdc63b2d0285c459a0f50")
_PAYMENT_ADDR     = os.getenv("NWO_PAYMENT_PROCESSOR",  "0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c")

# Entity type enum from contract
_ENTITY_HUMAN = 0
_ENTITY_AGENT = 1
_ENTITY_ROBOT = 2

_ENTITY_NAMES = {0: "human", 1: "agent", 2: "robot"}


@dataclass
class RobotIdentity:
    token_id: int
    wallet: str
    entity_type: str       # "robot"
    active: bool
    serial_hash: str       # hex bytes32
    firmware_hash: str     # hex bytes32 (latest)
    enrolled_at: int       # unix timestamp
    has_api_key: bool
    has_hw_cert: bool
    chain_id: int = 8453
    registry_address: str = _REGISTRY_ADDR


@dataclass
class CredentialCheck:
    token_id: int
    credential_type: str
    is_valid: bool
    checked_at_block: int


# ── Web3 setup ─────────────────────────────────────────────────────────────────

def _get_w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(_BASE_RPC))
    # Base uses PoA consensus — needed for block extra data
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def _get_registry(w3: Web3):
    return w3.eth.contract(
        address=Web3.to_checksum_address(_REGISTRY_ADDR),
        abi=IDENTITY_REGISTRY_ABI,
    )


def _get_payment(w3: Web3):
    return w3.eth.contract(
        address=Web3.to_checksum_address(_PAYMENT_ADDR),
        abi=PAYMENT_PROCESSOR_ABI,
    )


def _serial_to_bytes32(serial: str) -> bytes:
    """Convert a robot serial number string to a bytes32 hash."""
    return hashlib.sha256(serial.encode()).digest()


def _firmware_to_bytes32(firmware_version: str, firmware_hash: str = "") -> bytes:
    """Convert firmware identifier to bytes32."""
    combined = f"{firmware_version}:{firmware_hash}"
    return hashlib.sha256(combined.encode()).digest()


# ── Registration via Relayer ───────────────────────────────────────────────────

async def register_robot_on_chain(
    robot_wallet: str,
    serial_number: str,
    firmware_version: str,
    firmware_hash: str = "",
) -> dict[str, Any]:
    """
    Register a robot on Base Mainnet via the NWO Relayer (gasless).

    The Relayer holds REGISTRAR_ROLE on the IdentityRegistry contract and
    submits the transaction on behalf of the platform. No gas needed from robot.

    Args:
        robot_wallet: The robot's Ethereum wallet address (its on-chain identity)
        serial_number: Physical serial number of the robot
        firmware_version: Current firmware version string
        firmware_hash: Optional SHA-256 of the firmware binary

    Returns:
        Dict with token_id, tx_hash, and identity details
    """
    serial_bytes = _serial_to_bytes32(serial_number)
    fw_bytes = _firmware_to_bytes32(firmware_version, firmware_hash)

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{_RELAYER_URL}/relay/registerRobot",
            headers={"X-Relayer-Secret": _RELAYER_SECRET, "Content-Type": "application/json"},
            json={
                "robotWallet":  robot_wallet,
                "serialHash":   "0x" + serial_bytes.hex(),
                "firmwareHash": "0x" + fw_bytes.hex(),
            },
        )
        r.raise_for_status()
        data = r.json()

    return {
        "token_id":      data.get("rootTokenId") or data.get("tokenId"),
        "tx_hash":       data.get("txHash") or data.get("transactionHash"),
        "wallet":        robot_wallet,
        "serial_hash":   "0x" + serial_bytes.hex(),
        "firmware_hash": "0x" + fw_bytes.hex(),
        "chain_id":      _CHAIN_ID,
        "registry":      _REGISTRY_ADDR,
        "message":       "Robot registered on Base Mainnet. Soul-bound NFT minted.",
    }


async def register_agent_on_chain(
    agent_wallet: str,
    api_key_hash: str,
) -> dict[str, Any]:
    """
    Register an AI agent on Base Mainnet via the Relayer.

    Args:
        agent_wallet: Agent's wallet address
        api_key_hash: hex keccak256 of the agent's API key

    Returns:
        Dict with token_id, tx_hash
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{_RELAYER_URL}/relay/registerAgent",
            headers={"X-Relayer-Secret": _RELAYER_SECRET, "Content-Type": "application/json"},
            json={
                "moonpayWallet": agent_wallet,
                "apiKeyHash":    api_key_hash,
            },
        )
        r.raise_for_status()
        data = r.json()

    return {
        "token_id":  data.get("rootTokenId") or data.get("tokenId"),
        "tx_hash":   data.get("txHash"),
        "wallet":    agent_wallet,
        "chain_id":  _CHAIN_ID,
        "message":   "Agent registered on Base Mainnet.",
    }


# ── Identity resolution (read-only) ───────────────────────────────────────────

async def resolve_identity(token_id: int) -> RobotIdentity | None:
    """
    Read identity from the IdentityRegistry contract (no gas, no relayer).

    Args:
        token_id: The rootTokenId (NFT ID) of the robot/agent

    Returns:
        RobotIdentity or None if not found
    """
    try:
        w3 = _get_w3()
        registry = _get_registry(w3)

        identity = registry.functions.identities(token_id).call()
        entity_type, active, wallet, registrar, enrolled_at, cardiac_hash, api_key_hash, serial_hash = identity

        if not active:
            return None

        has_api_key = registry.functions.hasValidCredential(
            token_id,
            registry.functions.CRED_API_KEY().call(),
        ).call()

        has_hw_cert = registry.functions.hasValidCredential(
            token_id,
            registry.functions.CRED_HW_CERT().call(),
        ).call()

        return RobotIdentity(
            token_id=token_id,
            wallet=wallet,
            entity_type=_ENTITY_NAMES.get(entity_type, "unknown"),
            active=active,
            serial_hash=serial_hash.hex(),
            firmware_hash=api_key_hash.hex(),
            enrolled_at=enrolled_at,
            has_api_key=has_api_key,
            has_hw_cert=has_hw_cert,
        )
    except Exception as e:
        raise RuntimeError(f"Failed to resolve identity {token_id} from Base: {e}") from e


async def resolve_by_wallet(wallet: str) -> int | None:
    """Look up a rootTokenId by wallet address."""
    try:
        w3 = _get_w3()
        registry = _get_registry(w3)
        token_id = registry.functions.walletToRootToken(
            Web3.to_checksum_address(wallet)
        ).call()
        return token_id if token_id != 0 else None
    except Exception:
        return None


# ── Credential verification ────────────────────────────────────────────────────

async def verify_credential(token_id: int, credential_type: str) -> CredentialCheck:
    """
    Verify that a robot/agent holds a valid (non-expired, non-revoked) credential.

    Args:
        token_id: rootTokenId
        credential_type: "api_key" | "task_auth" | "hw_cert" | "firmware" | "access" | "payment"

    Returns:
        CredentialCheck with is_valid and current block number
    """
    # Map string name to bytes32 constant function name on the contract
    cred_fn_map = {
        "api_key":   "CRED_API_KEY",
        "task_auth": "CRED_TASK_AUTH",
        "hw_cert":   "CRED_HW_CERT",
        "firmware":  "CRED_FIRMWARE",
        "access":    "CRED_ACCESS",
        "payment":   "CRED_PAYMENT",
        "capability":"CRED_CAPABILITY",
    }

    fn_name = cred_fn_map.get(credential_type.lower())
    if not fn_name:
        # Try direct bytes32 hex
        if credential_type.startswith("0x"):
            cred_bytes = bytes.fromhex(credential_type[2:])
        else:
            raise ValueError(f"Unknown credential type: {credential_type}")
    else:
        w3 = _get_w3()
        registry = _get_registry(w3)
        cred_bytes = getattr(registry.functions, fn_name)().call()

    w3 = _get_w3()
    registry = _get_registry(w3)
    is_valid = registry.functions.hasValidCredential(token_id, cred_bytes).call()
    block = w3.eth.block_number

    return CredentialCheck(
        token_id=token_id,
        credential_type=credential_type,
        is_valid=is_valid,
        checked_at_block=block,
    )


# ── Credential issuance via Relayer ───────────────────────────────────────────

async def issue_task_auth(
    root_token_id: int,
    task_id: str,
    duration_hours: int = 1,
) -> dict[str, Any]:
    """
    Issue a CRED_TASK_AUTH SBT to a robot/agent, allowing it to execute
    a specific task on behalf of its owner.

    Calls the Relayer's /relay/issueCredential endpoint.

    Args:
        root_token_id: The identity token that should receive the credential
        task_id: Platform task ID being authorized
        duration_hours: How long the credential is valid

    Returns:
        Dict with tx_hash and sbt_index
    """
    import time
    expires_at = int(time.time()) + duration_hours * 3600
    cred_hash = "0x" + hashlib.sha256(task_id.encode()).hexdigest()

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            f"{_RELAYER_URL}/relay/issueCredential",
            headers={"X-Relayer-Secret": _RELAYER_SECRET, "Content-Type": "application/json"},
            json={
                "rootTokenId":    root_token_id,
                "credentialType": "0x" + hashlib.sha256(b"task_authorization").hexdigest(),
                "credentialHash": cred_hash,
                "expiresAt":      expires_at,
            },
        )
        r.raise_for_status()
        data = r.json()

    return {
        "root_token_id": root_token_id,
        "task_id":       task_id,
        "expires_at":    expires_at,
        "tx_hash":       data.get("txHash"),
        "sbt_index":     data.get("sbtIndex"),
        "message":       f"CRED_TASK_AUTH issued for task {task_id}",
    }


# ── DID document builder ──────────────────────────────────────────────────────

def build_did_document(identity: RobotIdentity) -> dict[str, Any]:
    """
    Build a W3C DID Document for a robot identity from on-chain data.
    Format: did:nwo:base:{token_id}
    """
    did = f"did:nwo:base:{identity.token_id}"
    return {
        "@context": [
            "https://www.w3.org/ns/did/v1",
            "https://nworobotics.cloud/did/v1",
        ],
        "id": did,
        "entity_type": identity.entity_type,
        "verificationMethod": [
            {
                "id": f"{did}#key-1",
                "type": "EthereumEOA",
                "controller": did,
                "blockchainAccountId": f"eip155:{_CHAIN_ID}:{identity.wallet}",
            }
        ],
        "authentication": [f"{did}#key-1"],
        "credentials": {
            "api_key_valid": identity.has_api_key,
            "hw_cert_valid": identity.has_hw_cert,
        },
        "service": [
            {
                "id": f"{did}#nwo-registry",
                "type": "NWOIdentityRegistry",
                "serviceEndpoint": f"https://basescan.org/token/{_REGISTRY_ADDR}?a={identity.token_id}",
            },
            {
                "id": f"{did}#nwo-robotics",
                "type": "NWORoboticsAPI",
                "serviceEndpoint": "https://nworobotics.cloud",
            },
        ],
        "nwo": {
            "chain_id":         _CHAIN_ID,
            "registry":         _REGISTRY_ADDR,
            "token_id":         identity.token_id,
            "serial_hash":      identity.serial_hash,
            "enrolled_at":      identity.enrolled_at,
            "active":           identity.active,
        },
    }
