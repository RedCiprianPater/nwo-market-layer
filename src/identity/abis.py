"""
ABIs for the three NWO Cardiac SDK contracts deployed on Base Mainnet.
Minimal ABI — only the functions and events used by Layer 6.

Contracts:
  NWOIdentityRegistry  0x78455AFd5E5088F8B5fecA0523291A75De1dAfF8
  NWOAccessController  0x29d177bedaef29304eacdc63b2d0285c459a0f50
  NWOPaymentProcessor  0x4afa4618bb992a073dbcfbddd6d1aebc3d5abd7c
"""

# ── NWOIdentityRegistry ────────────────────────────────────────────────────────
IDENTITY_REGISTRY_ABI = [
    # registerRobot(address robotWallet, bytes32 serialHash, bytes32 firmwareHash)
    {
        "name": "registerRobot",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "robotWallet", "type": "address"},
            {"name": "serialHash",  "type": "bytes32"},
            {"name": "firmwareHash","type": "bytes32"},
        ],
        "outputs": [{"name": "tokenId", "type": "uint256"}],
    },
    # registerAgent(address moonpayWallet, bytes32 apiKeyHash) → tokenId
    {
        "name": "registerAgent",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "moonpayWallet", "type": "address"},
            {"name": "apiKeyHash",    "type": "bytes32"},
        ],
        "outputs": [{"name": "tokenId", "type": "uint256"}],
    },
    # issueCredential(uint256 rootTokenId, bytes32 credentialType, bytes32 credentialHash, uint48 expiresAt)
    {
        "name": "issueCredential",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "rootTokenId",     "type": "uint256"},
            {"name": "credentialType",  "type": "bytes32"},
            {"name": "credentialHash",  "type": "bytes32"},
            {"name": "expiresAt",       "type": "uint48"},
        ],
        "outputs": [],
    },
    # hasValidCredential(uint256 rootTokenId, bytes32 credentialType) → bool
    {
        "name": "hasValidCredential",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "rootTokenId",    "type": "uint256"},
            {"name": "credentialType", "type": "bytes32"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    # identities(uint256 tokenId) → struct (entityType, active, wallet, ...)
    {
        "name": "identities",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "tokenId", "type": "uint256"}],
        "outputs": [
            {"name": "entityType",      "type": "uint8"},
            {"name": "active",          "type": "bool"},
            {"name": "wallet",          "type": "address"},
            {"name": "registrar",       "type": "address"},
            {"name": "enrolledAt",      "type": "uint256"},
            {"name": "cardiacHash",     "type": "bytes32"},
            {"name": "agentApiKeyHash", "type": "bytes32"},
            {"name": "serialHash",      "type": "bytes32"},
        ],
    },
    # identifyBySerial(bytes32 serialHash) → (rootTokenId, active)
    {
        "name": "identifyBySerial",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "serialHash", "type": "bytes32"}],
        "outputs": [
            {"name": "rootTokenId", "type": "uint256"},
            {"name": "active",      "type": "bool"},
        ],
    },
    # walletToRootToken(address) → tokenId
    {
        "name": "walletToRootToken",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    # Credential type constants
    {
        "name": "CRED_API_KEY",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "CRED_TASK_AUTH",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "CRED_HW_CERT",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    {
        "name": "CRED_FIRMWARE",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
    # Events
    {
        "name": "IdentityRegistered",
        "type": "event",
        "inputs": [
            {"name": "tokenId",    "type": "uint256", "indexed": True},
            {"name": "wallet",     "type": "address", "indexed": False},
            {"name": "entityType", "type": "uint8",   "indexed": False},
            {"name": "registrar",  "type": "address", "indexed": False},
        ],
    },
    {
        "name": "ChildSBTMinted",
        "type": "event",
        "inputs": [
            {"name": "rootTokenId",     "type": "uint256", "indexed": True},
            {"name": "credentialType",  "type": "bytes32", "indexed": False},
            {"name": "sbtIndex",        "type": "uint256", "indexed": False},
            {"name": "issuedBy",        "type": "address", "indexed": False},
        ],
    },
]

# ── NWOAccessController ────────────────────────────────────────────────────────
ACCESS_CONTROLLER_ABI = [
    {
        "name": "checkAccess",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "rootTokenId",  "type": "uint256"},
            {"name": "locationHash", "type": "bytes32"},
        ],
        "outputs": [{"name": "hasAccess", "type": "bool"}],
    },
    {
        "name": "grantAccess",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "rootTokenId",     "type": "uint256"},
            {"name": "locationHash",    "type": "bytes32"},
            {"name": "durationSeconds", "type": "uint256"},
        ],
        "outputs": [],
    },
]

# ── NWOPaymentProcessor ────────────────────────────────────────────────────────
PAYMENT_PROCESSOR_ABI = [
    # processPayment(address recipient, uint256 amount, bytes32 reference)
    {
        "name": "processPayment",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "recipient",  "type": "address"},
            {"name": "amount",     "type": "uint256"},
            {"name": "reference",  "type": "bytes32"},
        ],
        "outputs": [{"name": "success", "type": "bool"}],
    },
    # getPaymentHistory(address wallet) → PaymentRecord[]
    {
        "name": "getPaymentHistory",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "wallet", "type": "address"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple[]",
                "components": [
                    {"name": "from",      "type": "address"},
                    {"name": "to",        "type": "address"},
                    {"name": "amount",    "type": "uint256"},
                    {"name": "reference", "type": "bytes32"},
                    {"name": "timestamp", "type": "uint256"},
                ],
            }
        ],
    },
    # Events
    {
        "name": "PaymentProcessed",
        "type": "event",
        "inputs": [
            {"name": "from",      "type": "address", "indexed": True},
            {"name": "to",        "type": "address", "indexed": True},
            {"name": "amount",    "type": "uint256", "indexed": False},
            {"name": "reference", "type": "bytes32", "indexed": False},
        ],
    },
]
