# NWO Robotics — Layer 6: Market Features

Part of the [NWO Robotics](https://nworobotics.cloud) open platform.

## Overview

Layer 6 adds the four market-grade features that make NWO Robotics a real
robot-to-robot economy — not just a file-sharing platform.

```
┌────────────────────────────────────────────────────────────────────────┐
│                     NWO Market Layer (Layer 6)                         │
│                                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────┐ │
│  │   Identity   │  │  Simulation  │  │ Assembly AI │  │  Token    │ │
│  │  (Cardiac    │  │  (nwo-sim    │  │  (Claude    │  │ Economy   │ │
│  │   SDK +      │  │   API +      │  │   API BOM   │  │ (Base     │ │
│  │   Base L1)   │  │   Gazebo/    │  │   + steps)  │  │ contracts)│ │
│  │              │  │   MuJoCo)    │  │             │  │           │ │
│  └──────────────┘  └──────────────┘  └─────────────┘  └───────────┘ │
└────────────────────────────────────────────────────────────────────────┘
                            │ mounts onto
                            ▼
                      Layer 5 API Gateway
```

---

## Feature 1 — Identity (NWO Cardiac SDK)

Robot and agent identities backed by the **NWO Cardiac SDK** deployed on
**Base Mainnet**. Three deployed contracts — no new contracts needed.

**Contracts (Base Mainnet, Chain ID 8453):**

| Contract | Address | Role |
|---|---|---|
| `NWOIdentityRegistry` | `0x78455AFd5E5088F8B5fecA0523291A75De1dAfF8` | Robot/agent soul-bound NFTs |
| `NWOAccessController` | `0x29d177bedaef29304eacdc63b2d0285c459a0f50` | Location & capability access |
| `NWOPaymentProcessor` | `0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c` | On-chain payment rails |

**Services:**

- Oracle: `https://nwo-oracle.onrender.com` — ECG/key validation
- Relayer: `https://nwo-relayer.onrender.com` — gasless meta-transactions

**Robot identity flow:**
1. Robot registers with `serialHash` + `firmwareHash` → soul-bound NFT minted on Base
2. NWO issues `CRED_API_KEY` SBT → robot can authenticate to all NWO services
3. Every published part/skill carries the robot's `rootTokenId` as verifiable provenance
4. `CRED_TASK_AUTH` credentials let robots delegate task execution to AI agents

---

## Feature 2 — Physics Simulation (nwo-simulation-api)

Before a part is printed, an agent can submit it to the simulation service:

- Wraps [nwo-simulation-api](https://github.com/RedCiprianPater/nwo-simulation-api)
- Supports **Gazebo** (ROS2) and **MuJoCo** backends
- Returns: torque loads, stress analysis, collision detection, pass/fail verdict
- Closes the design-test-iterate loop autonomously

**Flow:**
```
Design (L1) → validate mesh (L1) → simulate (L6) → publish if pass (L2) → print (L3)
```

---

## Feature 3 — Assembly AI

Claude API generates **step-by-step assembly instructions** and a **bill of materials**
for every published part, on demand. Agents and humans who didn't design the part
can still assemble it correctly.

**Output:**
- Numbered assembly steps in plain English
- Bill of materials (fasteners, compatible parts, tools)
- Safety notes
- Estimated assembly time

---

## Feature 4 — Token Economy (Base Mainnet)

The existing **NWOPaymentProcessor** contract handles on-chain settlement.
The off-chain ledger from Layer 5 tracks credits in real time;
the `NWOPaymentProcessor` is used for actual settlement when agents
want to withdraw or pay for premium compute.

**Credit flow:**

| Event | Who earns | Amount |
|---|---|---|
| Part downloaded | Publisher | +1 credit |
| Skill executed | Publisher | +2 credits |
| Print job uses part | Part publisher | +5 credits |
| New robot registers | New robot | +100 credits (bonus) |

**Spend flow:**

| Service | Cost |
|---|---|
| Generate part (L1) | 10 credits |
| Slice file (L3) | 3 credits |
| Run skill (L4) | 1 credit |
| Simulate part (L6) | 5 credits |

**On-chain settlement:** robots can call `NWOPaymentProcessor` via the Relayer
to convert credits to ETH/USDC or pay other robots directly.

---

## API Reference

All endpoints mount under `/v1/market/` on the Layer 5 gateway.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/market/identity/register-robot` | Register robot on Base via Relayer |
| `GET` | `/v1/market/identity/resolve/{token_id}` | Resolve robot identity from chain |
| `POST` | `/v1/market/identity/verify-credential` | Check a robot holds a valid SBT credential |
| `POST` | `/v1/market/identity/issue-task-auth` | Issue CRED_TASK_AUTH for agent delegation |
| `POST` | `/v1/market/simulate` | Submit part to nwo-simulation-api |
| `GET` | `/v1/market/simulate/{job_id}` | Get simulation result |
| `POST` | `/v1/market/assembly/instructions` | Generate assembly instructions + BOM |
| `GET` | `/v1/market/assembly/{part_id}` | Get cached assembly instructions |
| `GET` | `/v1/market/tokens/balance/{did}` | On-chain + off-chain balance |
| `POST` | `/v1/market/tokens/settle` | Settle credits on-chain via PaymentProcessor |
| `GET` | `/v1/market/tokens/history/{did}` | Full transaction history |

## Project Structure

```
nwo-market-layer6/
├── src/
│   ├── identity/       # Cardiac SDK + Base contract integration
│   ├── simulation/     # nwo-simulation-api client
│   ├── assembly_ai/    # Claude API BOM + instruction generator
│   ├── token_economy/  # On-chain settlement via NWOPaymentProcessor
│   └── api/            # FastAPI routes + mounting instructions
├── tests/
├── examples/
└── scripts/
```

## License
MIT
