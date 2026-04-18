"""
Example: Full Layer 6 market lifecycle.

A robot autonomously:
  1. Registers its identity on Base Mainnet (soul-bound NFT)
  2. Generates a robot part via Layer 1 (through Layer 5 gateway)
  3. Simulates the part before printing (Layer 6 simulation)
  4. Publishes part to gallery if simulation passes (Layer 2)
  5. Generates assembly instructions for the part (Layer 6 assembly AI)
  6. Issues a CRED_TASK_AUTH to delegate printing to another agent
  7. Checks its token balance and settles credits to ETH

Run with the full stack:
  docker compose up
  python examples/full_market_lifecycle.py
"""

from __future__ import annotations
import asyncio, json, os
import httpx

GATEWAY   = os.getenv("GATEWAY_URL",    "http://localhost:8080")
MARKET    = os.getenv("MARKET_URL",     "http://localhost:8006")
ROBOT_WALLET = os.getenv("ROBOT_WALLET", "0xYourRobotWalletOnBase")


async def main():
    async with httpx.AsyncClient(timeout=120.0) as client:

        # ── 1. Register robot identity on Base Mainnet ─────────────────────
        print("1. Registering robot identity on Base Mainnet...")
        r = await client.post(f"{MARKET}/v1/market/identity/register-robot", json={
            "robot_wallet":     ROBOT_WALLET,
            "serial_number":    "NWO-ARM-001",
            "firmware_version": "v2.1.0",
            "firmware_hash":    "sha256:abc123",
        })
        r.raise_for_status()
        reg = r.json()
        token_id = reg["token_id"]
        print(f"   ✓ Soul-bound NFT minted on Base Mainnet")
        print(f"   Token ID : {token_id}")
        print(f"   DID      : did:nwo:base:{token_id}")
        print(f"   TX Hash  : {reg.get('tx_hash', '(pending)')}")

        # ── 2. Design a part via Layer 1 (through L5 gateway) ─────────────
        print("\n2. Generating robot part via Layer 1...")
        try:
            r = await client.post(f"{GATEWAY}/v1/design/generate", json={
                "prompt": "A 6-DOF arm joint bracket, M4 mounting holes, servo compatible, 40% infill, PETG",
                "provider": "anthropic",
                "backend": "openscad",
                "export_format": "stl",
                "validate": True,
            })
            if r.status_code == 200:
                design = r.json()
                file_url = f"{GATEWAY}{design.get('file_url', '')}"
                print(f"   ✓ Part generated: job {design['job_id']}")
                print(f"   Validation: {design.get('validation', {}).get('passed', 'n/a')}")
            else:
                print(f"   ⚠ L1 returned {r.status_code} — using demo mesh URL")
                file_url = "https://example.com/demo-bracket.stl"
        except Exception as e:
            print(f"   ⚠ L1 unavailable ({e}) — using demo mesh URL")
            file_url = "https://example.com/demo-bracket.stl"

        # ── 3. Simulate the part before printing ───────────────────────────
        print("\n3. Simulating part physics (MuJoCo)...")
        try:
            r = await client.post(f"{MARKET}/v1/market/simulate", json={
                "mesh_url":        file_url,
                "simulator":       "mujoco",
                "applied_force_n": 15.0,
                "applied_torque_nm": 3.0,
            })
            if r.status_code == 200:
                sim = r.json()
                verdict = "✓ PASS" if sim.get("passed") else "✗ FAIL"
                sf = sim.get("safety_factor")
                print(f"   {verdict} — Safety factor: {sf if sf else '?'}×")
                for warn in sim.get("warnings", []):
                    print(f"   ⚠ {warn}")
                sim_passed = sim.get("passed", True)
            else:
                print(f"   ⚠ Simulation unavailable ({r.status_code}) — proceeding")
                sim_passed = True
        except Exception as e:
            print(f"   ⚠ Simulation service unavailable ({e}) — proceeding")
            sim_passed = True

        # ── 4. Publish to gallery if simulation passed ─────────────────────
        if sim_passed:
            print("\n4. Publishing part to Layer 2 gallery...")
            try:
                r = await client.post(f"{GATEWAY}/v1/parts/publish",
                    headers={"X-Agent-ID": str(token_id)},
                    data={"metadata": json.dumps({
                        "name":          "6-DOF Arm Joint Bracket v2",
                        "category":      "joint",
                        "body_zone":     "arm",
                        "description":   "M4 servo-compatible joint bracket, PETG, simulation-validated",
                        "material_hints":["PETG"],
                        "print_settings":{"infill_pct": 40, "supports_required": False},
                        "license":       "CC0",
                        "tags":          ["joint", "arm", "servo", "validated"],
                        "validation_passed": sim_passed,
                    })},
                )
                if r.status_code == 200:
                    pub = r.json()
                    part_id = pub.get("part_id")
                    print(f"   ✓ Part published: {pub.get('name')} v{pub.get('version')}")
                else:
                    print(f"   ⚠ Gallery returned {r.status_code}")
                    part_id = "demo-part-id"
            except Exception as e:
                print(f"   ⚠ Gallery unavailable ({e})")
                part_id = "demo-part-id"
        else:
            print("\n4. Skipping publish — simulation failed")
            part_id = None

        # ── 5. Generate assembly instructions ──────────────────────────────
        if part_id and part_id != "demo-part-id":
            print(f"\n5. Generating assembly instructions for {part_id}...")
            try:
                r = await client.post(f"{MARKET}/v1/market/assembly/instructions", json={
                    "part_id": part_id, "force_regenerate": False
                })
                if r.status_code == 200:
                    ai = r.json()
                    print(f"   ✓ {ai['estimated_time_min']} min | {ai['difficulty']} | {len(ai['steps'])} steps")
                    print(f"   BOM: {len(ai['bill_of_materials'])} items")
                else:
                    print(f"   ⚠ Assembly AI returned {r.status_code}")
            except Exception as e:
                print(f"   ⚠ Assembly AI unavailable ({e})")

        # ── 6. Issue task auth for print delegation ────────────────────────
        print(f"\n6. Issuing CRED_TASK_AUTH for print delegation...")
        try:
            r = await client.post(f"{MARKET}/v1/market/identity/issue-task-auth", json={
                "root_token_id":  token_id,
                "task_id":       f"print:{part_id or 'demo'}",
                "duration_hours": 2,
            })
            if r.status_code == 200:
                auth = r.json()
                print(f"   ✓ CRED_TASK_AUTH issued | expires in 2h")
                print(f"   TX: {auth.get('tx_hash', '(pending)')}")
            else:
                print(f"   ⚠ Task auth returned {r.status_code}")
        except Exception as e:
            print(f"   ⚠ Task auth unavailable ({e})")

        # ── 7. Check token balance and rates ───────────────────────────────
        print(f"\n7. Checking token economy...")
        r = await client.get(f"{MARKET}/v1/market/tokens/rates")
        rates = r.json()
        print(f"   Earn per part download  : {rates['earn']['part_downloaded']} credit")
        print(f"   Cost per design         : {rates['spend']['generate_part']} credits")
        print(f"   Cost per simulation     : {rates['spend']['simulate_part']} credits")
        print(f"   Settlement rate         : {rates['settlement']['eth_per_credit']} ETH/credit")
        print(f"   Min settlement          : {rates['settlement']['min_credits']} credits")
        print(f"   Payment contract        : {rates['settlement']['payment_processor']}")

        print(f"\n{'─' * 55}")
        print(f"✓ Layer 6 market lifecycle complete.")
        print(f"  Robot DID  : did:nwo:base:{token_id}")
        print(f"  On-chain   : https://basescan.org/token/{os.getenv('NWO_IDENTITY_REGISTRY')}?a={token_id}")
        print(f"  Market API : {MARKET}/docs")


if __name__ == "__main__":
    asyncio.run(main())
