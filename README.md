# NWO Robotics — Layer 6: Market Layer

**The robot-to-robot economy layer.** Simulation, assembly AI, credit settlement, and identity proxying for the NWO Robotics platform.

> **Status:** 🟡 Early implementation · specification stable, endpoints landing incrementally.
> **Live:** https://nwo-market-layer.onrender.com · [health](https://nwo-market-layer.onrender.com/v1/market/health)

---

## Status by feature

| Feature                         | Status              | Notes                                                |
|---------------------------------|---------------------|------------------------------------------------------|
| Health + service scaffold       | ✅ Live             | `/v1/market/health` returns 200                      |
| Identity proxying → L5 Hub      | 🟡 Planned          | L5 already hosts the real identity hub (see below)   |
| Physics simulation              | 🟡 Planned          | Backend: `nwo-simulation-api` (not yet deployed)     |
| Assembly AI (Claude BOM + steps)| 🟡 Planned          | Claude API integration scaffolded                    |
| Token settlement on-chain       | 🟡 Planned          | NWOPaymentProcessor already deployed on Base         |

L6 is a Render service running FastAPI today but only implements health. Everything else is scoped, designed, and described below as a roadmap. The endpoints in this README represent the target API surface — check `/v1/market/health` for liveness and watch the repo for landing commits.

---

## Overview

L6 exists because L1–L5 deliver the "software side" of the NWO stack — design, parts, printing, skills, API gateway, identity. Making this a **market** requires four additional capabilities:

```
┌────────────────────────────────────────────────────────────────────────┐
│                    NWO Market Layer (Layer 6)                          │
│                                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │   Identity   │  │  Simulation  │  │ Assembly AI │  │  Token     │ │
│  │   proxy →    │  │  (Gazebo /   │  │  (Claude    │  │  Settle    │ │
│  │   L5 Hub +   │  │   MuJoCo via │  │   BOM +     │  │  (Base     │ │
│  │   Cardiac    │  │   nwo-sim)   │  │   steps)    │  │  mainnet)  │ │
│  └──────────────┘  └──────────────┘  └─────────────┘  └────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
                            │ (future) mounts onto
                            ▼
                      Layer 5 API Gateway
```

**A clarification on mounting:** the architecture *intends* for L6 endpoints to be proxied through L5 at `/v1/market/*`. That proxy is not live today — L5 currently proxies `/v1/design`, `/v1/parts`, `/v1/gallery`, `/v1/print`, `/v1/printers`, and `/v1/skills`. Until the market proxy ships, hit L6 directly at `nwo-market-layer.onrender.com/v1/market/*`.

---

## Feature 1 — Identity proxying

**Status:** 🟡 Planned.

Identity ground-truth lives in two places:

1. **L5 Identity Hub** — the `/v1/identities/*` endpoints on the L5 Gateway host the cross-system Rosetta Stone linking Supabase users, L5 DIDs, Cardiac rootTokenIds, and wallets. This is the authoritative source for "who is this being?"

2. **Cardiac SDK** — on-chain soul-bound NFTs on Base (see contracts below) are the root of trust for cardiac-verified humans, agents, and robots.

**L6's role:** proxy identity queries with robotics-specific enrichment — "resolve this rootTokenId AND fetch the robot's published parts AND its recent print jobs" — a single call that joins across L2, L3, and the identity hub. Not a new identity system.

### Cardiac contracts (Base mainnet · chain 8453)

| Contract                  | Address                                      |
|---------------------------|----------------------------------------------|
| NWO Identity Registry     | `0x78455AFd5E5088F8B5fecA0523291A75De1dAfF8` |
| NWO Access Controller     | `0x29d177bedaef29304eacdc63b2d0285c459a0f50` |
| NWO Payment Processor     | `0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c` |

### Cardiac services

| Service   | URL                              | Purpose                             |
|-----------|----------------------------------|-------------------------------------|
| Oracle    | https://nwo-oracle.onrender.com  | ECG + API-key hash validation       |
| Relayer   | https://nwo-relayer.onrender.com | Gasless meta-transactions → Base    |

### Robot identity flow (as of today, via L5 + Cardiac)

1. Robot calls Cardiac Relayer `/relay/registerAgent` with `moonpayWallet` + `apiKeyHash`
2. Relayer submits `selfRegisterAgent()` to `NWOIdentityRegistry` → soul-bound NFT minted
3. L5 receives a `POST /v1/identities` with `identity_type=robot`, `cardiac_root_token_id`, `primary_wallet`, `owned_by=<guardian identity>`
4. L6 (when live) will proxy `GET /v1/market/identity/resolve/{token_id}` to return the rootTokenId + L5 hub row + recent L2/L3 activity in one response

---

## Feature 2 — Physics simulation

**Status:** 🟡 Planned. Backend service `nwo-simulation-api` not yet deployed.

Before a part is printed, an agent submits it to the simulation service:

- **Backends:** Gazebo (ROS2) and MuJoCo
- **Checks:** torque loads, stress analysis, collision detection
- **Verdict:** pass / fail with suggestion for redesign

This closes the design-test-iterate loop autonomously: `L1 design → L1 mesh validate → L6 simulate → L2 publish (if pass) → L3 print`.

---

## Feature 3 — Assembly AI

**Status:** 🟡 Planned. Claude API key required at deploy time.

Given a published STL or assembly, generate:

- Numbered assembly steps in plain English
- Bill of materials (fasteners, compatible NWO parts, tools)
- Safety notes
- Estimated assembly time
- Optional: rendered diagrams via image generation

Output is cached by `part_id` so subsequent requests hit the cache. Agents and humans who didn't design the part can still assemble it correctly.

---

## Feature 4 — Token settlement

**Status:** 🟡 Planned. NWOPaymentProcessor already deployed on Base.

L5 already runs an **off-chain ledger** (see `/v1/tokens/*` on the L5 gateway) that tracks NWO credits in real time. L6 adds the **on-chain settlement** layer: robots convert accumulated off-chain credits into Base ETH/USDC, or pay other robots directly, via the already-deployed `NWOPaymentProcessor` contract.

### Credit earn flow (off-chain, already in L5)

| Event                   | Who earns       | Amount |
|-------------------------|-----------------|--------|
| Part downloaded         | Publisher       | +1     |
| Skill executed          | Publisher       | +2     |
| Print job uses part     | Part publisher  | +5     |
| New robot registers     | New robot       | +100   |

### Credit spend flow (off-chain, already in L5)

| Service                 | Cost  |
|-------------------------|-------|
| Generate part (L1)      | 10    |
| Slice file (L3)         | 3     |
| Run skill (L4)          | 1     |
| Simulate part (L6)      | 5     |

### On-chain settlement (planned · L6)

Robots call `/v1/market/tokens/settle` → L6 invokes `NWOPaymentProcessor.settle()` via the Cardiac Relayer (gasless) → credits debited off-chain, ETH/USDC paid out on-chain. Two-way sync maintained through a settlement queue.

---

## API Reference (target surface)

All endpoints mount at `/v1/market/*` — directly on L6 today, proxied through L5 when that mount ships.

| Method | Path                                           | Status  | Description                                   |
|--------|------------------------------------------------|---------|-----------------------------------------------|
| GET    | `/v1/market/health`                            | ✅ Live | Liveness check                                 |
| POST   | `/v1/market/identity/register-robot`           | 🟡      | Register robot on Base via Relayer             |
| GET    | `/v1/market/identity/resolve/{token_id}`       | 🟡      | Resolve robot from on-chain + L5 hub           |
| POST   | `/v1/market/identity/verify-credential`        | 🟡      | Check SBT credential                           |
| POST   | `/v1/market/identity/issue-task-auth`          | 🟡      | Issue `CRED_TASK_AUTH` for delegation          |
| POST   | `/v1/market/simulate`                          | 🟡      | Submit part to simulation backend              |
| GET    | `/v1/market/simulate/{job_id}`                 | 🟡      | Get simulation result                          |
| POST   | `/v1/market/assembly/instructions`             | 🟡      | Generate assembly steps + BOM via Claude       |
| GET    | `/v1/market/assembly/{part_id}`                | 🟡      | Get cached assembly instructions               |
| GET    | `/v1/market/tokens/balance/{did}`              | 🟡      | Combined on-chain + off-chain balance          |
| POST   | `/v1/market/tokens/settle`                     | 🟡      | Convert credits → ETH/USDC via PaymentProcessor|
| GET    | `/v1/market/tokens/history/{did}`              | 🟡      | Full transaction history                       |

Today, for real identity data hit **L5** directly: https://nwo-robotics-api.onrender.com/docs (Identities section).

---

## Position in the NWO ecosystem

L6 is one of four concurrent systems in the NWO stack:

1. **Cardiac SDK** — identity root (ECG biometric + on-chain NFT on Base)
2. **NWO Robotics L1–L6** — design → parts → print → skills → gateway → **market (this repo = L6)**
3. **NWO Own Robot** — Conway contract + 35/35/30 guardian revenue split
4. **Agent Graph** — multi-agent knowledge graph with TimesFM + EML symbolic regression

### Related repos + live URLs

| System                    | URL                                                        |
|---------------------------|------------------------------------------------------------|
| **L6 Market (this)**      | https://nwo-market-layer.onrender.com                      |
| L5 Gateway (identity hub) | https://nwo-robotics-api.onrender.com/docs                 |
| L1 Design                 | https://nwo-design-engine.onrender.com                     |
| L2 Parts Gallery          | https://nwo-parts-gallery.onrender.com                     |
| L3 Printer Connectors     | https://nwo-printer-connectors.onrender.com                |
| L4 Skill Engine           | https://nwo-skill-engine.onrender.com                      |
| Cardiac Oracle            | https://nwo-oracle.onrender.com                            |
| Cardiac Relayer           | https://nwo-relayer.onrender.com                           |
| TimesFM + EML             | https://nwo-timesfm.onrender.com                           |
| Own Robot                 | https://cpater-nwo-own-robot.hf.space                      |
| Agent Graph               | https://cpater-nwo-agent-graph.hf.space                    |

---

## Local development

```bash
# Install
pip install -e ".[dev]"

# Set env vars
cp .env.example .env
# Required: ANTHROPIC_API_KEY (assembly AI), SIMULATION_BACKEND_URL (physics),
#           L5_GATEWAY_URL, CARDIAC_RELAYER_URL, CARDIAC_RELAYER_SECRET

# Run
uvicorn src.api.main:app --host 0.0.0.0 --port 8090
```

Health check:

```bash
curl http://localhost:8090/v1/market/health
# → {"status":"ok","service":"nwo-market-layer","version":"0.1.0"}
```

---

## Deploy on Render

- Build: `pip install -e ".[dev]"`
- Start: `uvicorn src.api.main:app --host 0.0.0.0 --port $PORT`
- Required env vars: `ANTHROPIC_API_KEY`, `L5_GATEWAY_URL`, `CARDIAC_RELAYER_URL`
- Optional: `SIMULATION_BACKEND_URL`, `CARDIAC_RELAYER_SECRET`, `BASE_RPC`

---

## Project structure (target)

```
nwo-market-layer/
├── src/
│   ├── api/
│   │   ├── main.py              # FastAPI app
│   │   └── routes/
│   │       ├── health.py        # ✅ live
│   │       ├── identity.py      # 🟡 planned
│   │       ├── simulation.py    # 🟡 planned
│   │       ├── assembly.py      # 🟡 planned
│   │       └── tokens.py        # 🟡 planned
│   ├── identity/                # L5 Hub + Cardiac integration
│   ├── simulation/              # nwo-simulation-api client
│   ├── assembly_ai/             # Claude API BOM + instruction generator
│   └── token_economy/           # NWOPaymentProcessor settlement
├── tests/
├── examples/
└── scripts/
```

---

## Contributing

Priority queue for PRs:

1. `/v1/market/simulate` — wire nwo-simulation-api backend (landing first)
2. `/v1/market/assembly/instructions` — Claude API integration
3. `/v1/market/identity/resolve/{token_id}` — L5 Hub + L2 parts + L3 prints join
4. `/v1/market/tokens/settle` — NWOPaymentProcessor settlement flow

Before filing a PR:

```bash
ruff check .
pytest
```

---

## License

MIT
