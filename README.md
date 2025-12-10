# LXMFMonero

**Monero transactions over LXMF/Reticulum mesh networks**

LXMFMonero enables Monero wallet operations over Reticulum mesh networks using LXMF (Lightweight Extensible Message Format) for reliable message delivery. This allows financial sovereignty even in environments without traditional internet connectivity.

## Status

**Working** - Full transaction flow verified over 2-hop public testnet (December 10, 2025).

| Feature | Status | Notes |
|---------|--------|-------|
| Balance queries | ✅ Working | 2-4 second round-trip over testnet |
| Export outputs | ✅ Working | ~7 seconds over 2 hops |
| Create unsigned tx | ✅ Working | 6-7KB payloads work |
| Sign transaction | ✅ Working | Cold wallet signing works |
| Submit transaction | ✅ Working | **Broadcast confirmed on mainnet** |
| Key image sync | ✅ Working | Automatic after tx |
| I2P transport | 🔄 Pending | Next test phase |
| LoRa/HF transport | 🔄 Pending | Future testing |

### Verified Transaction

```
TX Hash: 8f0295261a2ec04c6d4dcf0c9cc6b30278ab50caf9f6d27a61b562e6f3ebd761
Route:   Mac → BetweenTheBorders testnet (2 hops) → Pi-1 → monerod
Time:    ~20 seconds total round-trip
```

## Features

- **Cold Signing Workflow**: Private keys never leave your device
- **Any Transport**: Works over HF radio, LoRa, WiFi, I2P, or any Reticulum interface
- **Reliable Delivery**: LXMF handles retries, large payloads, and store-and-forward
- **Simple Architecture**: Stateless messages, no persistent connections required

## Architecture

```
┌─────────────────────┐                    ┌─────────────────────┐
│   COLD CLIENT       │                    │      HUB            │
│                     │                    │                     │
│  - Has spend key    │     LXMF           │  - View-only wallet │
│  - Signs locally    │◄──────────────────►│  - Connected to     │
│  - Air-gapped OK    │   (any transport)  │    monerod          │
│                     │                    │                     │
└─────────────────────┘                    └─────────────────────┘
```

## Installation

```bash
# Clone repository
git clone https://github.com/LFManifesto/LXMFMonero.git
cd LXMFMonero

# Install
pip install -e .
```

## Quick Start

### Hub Setup (View-Only Wallet)

The hub runs alongside a view-only Monero wallet and handles requests from clients.

1. Start `monero-wallet-rpc` with your view-only wallet:
```bash
monero-wallet-rpc --wallet-file /path/to/viewonly-wallet \
    --rpc-bind-port 18082 --disable-rpc-login \
    --daemon-address 127.0.0.1:18083  # Use unrestricted RPC port
```

2. Start the hub:
```bash
lxmfmonero-hub --wallet-rpc http://127.0.0.1:18082/json_rpc
```

3. Note the destination hash printed at startup.

### Client Setup (Cold Wallet)

The client holds the spend key and can be air-gapped.

1. Start `monero-wallet-rpc` with your cold wallet in **offline mode**:
```bash
monero-wallet-rpc --wallet-file /path/to/cold-wallet \
    --rpc-bind-port 18087 --disable-rpc-login --offline
```

2. **TUI Interface (Recommended):**
```bash
lxmfmonero-tui --hub <hub-destination-hash> \
    --cold-wallet http://127.0.0.1:18087/json_rpc
```

3. **CLI - Check balance:**
```bash
lxmfmonero-client --hub <hub-destination-hash> balance
```

4. **CLI - Send XMR:**
```bash
lxmfmonero-client --hub <hub-destination-hash> \
    --cold-wallet http://127.0.0.1:18087/json_rpc \
    send <address> <amount>
```

## TUI Interface

The TUI provides a visual interface for managing Monero transactions:

```
============ LXMFMonero ============ Hub: Connected

WALLET BALANCE

    0.000769280000 XMR
    Block Height: 3562548
    Last Updated: 15s ago

COMMANDS
    [S] Send XMR
    [R] Refresh Balance
    [Q] Quit

Hub: f5ad834014699eada...
```

Features:
- Real-time balance display
- Visual transaction confirmation
- Step-by-step progress for send operations
- Automatic background refresh

## Cold Signing Workflow

The transaction flow ensures private keys never leave the cold wallet:

1. **Client** requests balance/transaction from **Hub** (view-only)
2. **Hub** creates unsigned transaction
3. **Client** signs locally with spend key
4. **Client** sends signed transaction to **Hub**
5. **Hub** broadcasts to Monero network
6. **Client** exports key images for balance sync

Each step is an independent LXMF message - no persistent connection required.

## Configuration

### Hub Options

```
--identity, -i    Path to identity file (default: ~/.lxmfmonero/hub/identity)
--storage, -s     Path to LXMF storage (default: ~/.lxmfmonero/hub/storage)
--wallet-rpc, -w  wallet-rpc URL (default: http://127.0.0.1:18082/json_rpc)
--name, -n        Display name for announcements
--announce-interval, -a  Seconds between announces (0 to disable)
```

### Client Options

```
--identity, -i    Path to identity file
--storage, -s     Path to LXMF storage
--hub, -H         Hub destination hash (required)
--cold-wallet, -c Cold wallet-rpc URL (default: http://127.0.0.1:18083/json_rpc)
--operator, -o    Operator ID for hub
--timeout, -t     Request timeout in seconds (default: 300)
```

## Message Sizes

All data sizes are compatible with LXMF's automatic Resource handling:

| Data | Size | Verified |
|------|------|----------|
| Balance response | ~500 bytes | ✅ |
| Export outputs | ~640-820 bytes | ✅ |
| Unsigned tx | 6-7 KB | ✅ |
| Signed tx | 12-13 KB | ✅ |
| Key images | ~500 bytes per | - |

## Tested Configuration

Successfully tested over Reticulum public testnet (December 2025):

```
Mac (cold wallet) → BetweenTheBorders Testnet → Pi-1 (hub + monerod)
                           2 hops
```

- **Transport**: TCPInterface to reticulum.betweentheborders.com:4242
- **Round-trip**: ~20 seconds for full transaction (balance: 2-4 seconds)
- **Large payloads**: 12KB+ signed transactions delivered reliably
- **Mainnet**: Transaction successfully broadcast and confirmed

## Critical Procedures

### Key Image Synchronization

**IMPORTANT**: After every successful transaction, key images must be synced from the cold wallet to the view-only wallet. The client does this automatically in step 6, but if interrupted:

```bash
# Export from cold wallet
curl -s http://127.0.0.1:18087/json_rpc \
  -d '{"jsonrpc":"2.0","id":"0","method":"export_key_images","params":{"all":true}}'

# Import to view-only wallet (on hub machine)
curl -s http://127.0.0.1:18085/json_rpc \
  -d '{"jsonrpc":"2.0","id":"0","method":"import_key_images","params":{"signed_key_images":[...]}}'
```

If key images are out of sync, the view-only wallet will show incorrect balance and transactions will fail with "double spend" errors.

### Troubleshooting

**"Key image already spent in blockchain"**
- The view-only wallet is out of sync with the cold wallet
- Solution: Export key images from cold wallet and import to view-only

**"Request timed out"**
- Check Reticulum connectivity: `rnpath <hub-hash>`
- Verify hub is running and announcing
- Check if path exists through testnet

**"Insufficient balance"**
- Balance may include locked outputs
- Wait for outputs to unlock (10 blocks after receiving)
- Check `unlocked_balance` vs `balance`

**"Transaction rejected by daemon"**
- Enable monerod logging: `curl http://127.0.0.1:18083/set_log_level -d '{"level":2}'`
- Check monerod logs for specific rejection reason
- Common causes: double spend, invalid ring members, key images already spent

### Wallet Setup Requirements

1. **Cold and view-only wallets must be created from the same seed**
2. View-only wallet needs the **secret view key** (not spend key)
3. Cold wallet must be started with `--offline` flag
4. View-only wallet connects to monerod on **unrestricted RPC port** (18083, not 18081)

## Security Notes

- The **Hub** only has view-only access - it cannot spend funds
- The **Client** has the spend key and signs transactions locally
- All communication is end-to-end encrypted by Reticulum
- LXMF provides forward secrecy

## Requirements

- Python 3.9+
- Reticulum Network Stack (`rns`)
- LXMF (`lxmf`)
- Monero (`monero-wallet-rpc`)

## License

MIT License - See LICENSE file

## Credits

Built on:
- [Reticulum](https://reticulum.network/) - Cryptographic networking stack
- [LXMF](https://github.com/markqvist/LXMF) - Message format for Reticulum
- [Monero](https://getmonero.org/) - Private, decentralized cryptocurrency

Developed by [Light Fighter Manifesto L.L.C.](https://lightfightermanifesto.org)
