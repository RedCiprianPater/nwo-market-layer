"""
Token economy — on-chain settlement via NWOPaymentProcessor on Base Mainnet.

The off-chain credit ledger (Layer 5) tracks credits in real time.
This module handles on-chain settlement when agents want to:
  - Withdraw credits as ETH
  - Pay other robots directly (robot-to-robot)
  - Check on-chain payment history

No new contracts are deployed. All calls go through the existing
NWOPaymentProcessor at 0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c

Settlement flow:
  Agent has 500 credits (off-chain ledger)
  Agent calls POST /market/tokens/settle
  → Layer 6 calls NWOPaymentProcessor.processPayment() on Base
  → ETH transferred to agent wallet (at SETTLEMENT_ETH_PER_CREDIT rate)
  → Off-chain ledger debited
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any

import httpx
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from ..identity.abis import PAYMENT_PROCESSOR_ABI

_BASE_RPC    = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
_CHAIN_ID    = int(os.getenv("BASE_CHAIN_ID", "8453"))
_PAYMENT_ADDR = os.getenv("NWO_PAYMENT_PROCESSOR", "0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c")
_RELAYER_URL = os.getenv("CARDIAC_RELAYER_URL", "https://nwo-relayer.onrender.com")
_RELAYER_SECRET = os.getenv("CARDIAC_RELAYER_SECRET", "")

_ETH_PER_CREDIT   = float(os.getenv("SETTLEMENT_ETH_PER_CREDIT", "0.0001"))
_MIN_SETTLEMENT   = int(os.getenv("SETTLEMENT_MIN_CREDITS", "50"))

# Credit rates (mirrors Layer 5 ledger rates)
_RATES = {
    "simulate":        int(os.getenv("SIMULATE_CREDIT_COST", "5")),
    "design":          int(os.getenv("TOKENS_COST_PER_DESIGN", "10")),
    "slice":           int(os.getenv("TOKENS_COST_PER_SLICE", "3")),
    "skill_run":       int(os.getenv("TOKENS_COST_PER_SKILL_RUN", "1")),
    "part_download":   int(os.getenv("TOKENS_PER_PART_DOWNLOAD", "1")),
    "skill_execution": int(os.getenv("TOKENS_PER_SKILL_RUN", "2")),
    "print_job":       int(os.getenv("TOKENS_PER_PRINT_JOB", "5")),
    "registration":    int(os.getenv("AGENT_REGISTRATION_BONUS", "100")),
}


@dataclass
class SettlementResult:
    success: bool
    credits_settled: int
    eth_amount: float
    tx_hash: str | None
    recipient_wallet: str
    reference: str
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success":         self.success,
            "credits_settled": self.credits_settled,
            "eth_amount":      self.eth_amount,
            "tx_hash":         self.tx_hash,
            "recipient_wallet":self.recipient_wallet,
            "reference":       self.reference,
            "error":           self.error,
        }


@dataclass
class PaymentRecord:
    from_wallet: str
    to_wallet: str
    amount_eth: float
    reference: str
    timestamp: int
    tx_hash: str | None = None


def _get_w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(_BASE_RPC))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def _get_payment_contract(w3: Web3):
    return w3.eth.contract(
        address=Web3.to_checksum_address(_PAYMENT_ADDR),
        abi=PAYMENT_PROCESSOR_ABI,
    )


def credits_to_eth(credits: int) -> float:
    """Convert off-chain credits to ETH at the configured rate."""
    return round(credits * _ETH_PER_CREDIT, 8)


def eth_to_credits(eth: float) -> int:
    """Convert ETH to credits (inverse rate)."""
    return int(eth / _ETH_PER_CREDIT)


# ── On-chain settlement ────────────────────────────────────────────────────────

async def settle_credits(
    recipient_wallet: str,
    credits: int,
    reference_id: str,
) -> SettlementResult:
    """
    Settle off-chain credits as ETH via NWOPaymentProcessor on Base Mainnet.

    The Relayer holds the platform's ETH and submits the payment transaction.
    The off-chain ledger must be debited separately (done by the API layer).

    Args:
        recipient_wallet: Robot/agent wallet address to receive ETH
        credits: Number of off-chain credits to settle
        reference_id: Unique reference (part_id, run_id, etc.)

    Returns:
        SettlementResult with tx_hash and ETH amount
    """
    if credits < _MIN_SETTLEMENT:
        return SettlementResult(
            success=False,
            credits_settled=0,
            eth_amount=0.0,
            tx_hash=None,
            recipient_wallet=recipient_wallet,
            reference=reference_id,
            error=f"Minimum settlement is {_MIN_SETTLEMENT} credits. Have: {credits}",
        )

    eth_amount = credits_to_eth(credits)
    eth_wei = Web3.to_wei(eth_amount, "ether")

    # Build reference bytes32 from reference_id
    ref_bytes = "0x" + hashlib.sha256(reference_id.encode()).hexdigest()

    # Call Relayer to process the payment (gasless from platform wallet)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{_RELAYER_URL}/payment/process",
                headers={
                    "X-Relayer-Secret": _RELAYER_SECRET,
                    "Content-Type": "application/json",
                },
                json={
                    "recipient":  recipient_wallet,
                    "amount":     str(eth_wei),
                    "reference":  ref_bytes,
                },
            )
            r.raise_for_status()
            data = r.json()

        return SettlementResult(
            success=True,
            credits_settled=credits,
            eth_amount=eth_amount,
            tx_hash=data.get("txHash") or data.get("transactionHash"),
            recipient_wallet=recipient_wallet,
            reference=reference_id,
        )

    except Exception as e:
        return SettlementResult(
            success=False,
            credits_settled=0,
            eth_amount=0.0,
            tx_hash=None,
            recipient_wallet=recipient_wallet,
            reference=reference_id,
            error=str(e),
        )


# ── Robot-to-robot payment ─────────────────────────────────────────────────────

async def robot_to_robot_payment(
    from_wallet: str,
    to_wallet: str,
    credits: int,
    reference_id: str,
) -> SettlementResult:
    """
    Direct robot-to-robot payment via NWOPaymentProcessor.
    The sending robot must have sufficient ETH in their wallet.
    This call goes through the Relayer for gasless meta-tx.

    Args:
        from_wallet: Sending robot's wallet (must have ETH)
        to_wallet:   Receiving robot's wallet
        credits:     Credits worth of ETH to transfer
        reference_id: Part/skill/service being paid for
    """
    eth_amount = credits_to_eth(credits)
    eth_wei = Web3.to_wei(eth_amount, "ether")
    ref_bytes = "0x" + hashlib.sha256(reference_id.encode()).hexdigest()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{_RELAYER_URL}/payment/robotTransfer",
                headers={
                    "X-Relayer-Secret": _RELAYER_SECRET,
                    "Content-Type": "application/json",
                },
                json={
                    "from":      from_wallet,
                    "to":        to_wallet,
                    "amount":    str(eth_wei),
                    "reference": ref_bytes,
                },
            )
            r.raise_for_status()
            data = r.json()

        return SettlementResult(
            success=True,
            credits_settled=credits,
            eth_amount=eth_amount,
            tx_hash=data.get("txHash"),
            recipient_wallet=to_wallet,
            reference=reference_id,
        )
    except Exception as e:
        return SettlementResult(
            success=False,
            credits_settled=0,
            eth_amount=0.0,
            tx_hash=None,
            recipient_wallet=to_wallet,
            reference=reference_id,
            error=str(e),
        )


# ── On-chain balance read ──────────────────────────────────────────────────────

async def get_onchain_balance(wallet: str) -> float:
    """Return the ETH balance of a wallet on Base Mainnet."""
    try:
        w3 = _get_w3()
        balance_wei = w3.eth.get_balance(Web3.to_checksum_address(wallet))
        return float(Web3.from_wei(balance_wei, "ether"))
    except Exception:
        return 0.0


async def get_payment_history(wallet: str) -> list[PaymentRecord]:
    """
    Read payment history for a wallet from NWOPaymentProcessor.
    Falls back to Relayer API if direct RPC fails.
    """
    # Try Relayer read endpoint first (more convenient)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{_RELAYER_URL}/read/paymentHistory",
                headers={"X-Relayer-Secret": _RELAYER_SECRET, "Content-Type": "application/json"},
                json={"wallet": wallet},
            )
            if r.status_code == 200:
                records = r.json().get("history", [])
                return [
                    PaymentRecord(
                        from_wallet=rec.get("from", ""),
                        to_wallet=rec.get("to", ""),
                        amount_eth=float(Web3.from_wei(int(rec.get("amount", 0)), "ether")),
                        reference=rec.get("reference", ""),
                        timestamp=rec.get("timestamp", 0),
                        tx_hash=rec.get("txHash"),
                    )
                    for rec in records
                ]
    except Exception:
        pass

    # Fallback: read directly from contract
    try:
        w3 = _get_w3()
        contract = _get_payment_contract(w3)
        records = contract.functions.getPaymentHistory(
            Web3.to_checksum_address(wallet)
        ).call()
        return [
            PaymentRecord(
                from_wallet=r[0],
                to_wallet=r[1],
                amount_eth=float(Web3.from_wei(r[2], "ether")),
                reference=r[3].hex(),
                timestamp=r[4],
            )
            for r in records
        ]
    except Exception:
        return []


def get_credit_rates() -> dict[str, int]:
    """Return the current credit rate table."""
    return dict(_RATES)
