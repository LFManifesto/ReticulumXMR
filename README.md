# LXMFMonero

**Monero transactions over LXMF/Reticulum mesh networks**

LXMFMonero enables Monero wallet operations over Reticulum mesh networks using LXMF (Lightweight Extensible Message Format) for reliable message delivery. This allows financial sovereignty even in environments without traditional internet connectivity.

## Status

**Working** - Full transaction flow verified over 2-hop public testnet (December 10, 2025).

| Feature | Status | Notes |
|---------|--------|-------|
| Balance queries | ✅ Working | 2-4 second round-trip over testnet |
| Export outputs | ✅ Working | ~7 seconds over TCP, ~18s over I2P |
| Create unsigned tx | ✅ Working | 6-7KB payloads work |
| Sign transaction | ✅ Working | Cold wallet signing works |
| Submit transaction | ✅ Working | **Broadcast confirmed on mainnet** |
| Key image sync | ✅ Working | Automatic after tx |
| I2P transport | ✅ Working | **Full transaction verified** |
| LoRa/HF transport | 🔄 Pending | Future testing |

### Verified Transactions

**TCP/Testnet (2 hops):**
```
TX Hash: 8f0295261a2ec04c6d4dcf0c9cc6b30278ab50caf9f6d27a61b562e6f3ebd761
Route:   Mac → BetweenTheBorders testnet → Pi-1 → monerod
Time:    ~20 seconds
```

**I2P (anonymous):**
```
TX Hash: a793ff7bd6a0a4b168f72726e2027d283cc5fed0c8c3b1cd6693c6ef7a6fa8ee
Route:   Mac → I2P tunnel → Pi-1 → monerod
Time:    ~35 seconds
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

## Prerequisites

### 1. Install Reticulum

```bash
pip install rns lxmf
```

### 2. Configure Reticulum

Edit `~/.reticulum/config` to connect to a testnet. Example for TCP testnet:

```ini
[interfaces]
  [[RNS Testnet BetweenTheBorders]]
    type = TCPClientInterface
    enabled = yes
    target_host = reticulum.betweentheborders.com
    target_port = 4242
```

For I2P (requires i2pd running):
```ini
  [[I2P Interface]]
    type = I2PInterface
    enabled = yes
    peers = <hub-i2p-b32-address>.b32.i2p
```

### 3. Start Reticulum Daemon

```bash
rnsd &
```

Verify connectivity:
```bash
rnstatus
```

### 4. Install Monero

Download Monero CLI tools from https://getmonero.org/downloads/

You need `monero-wallet-rpc` on both machines (hub and client).

## Installation

```bash
# Clone repository
git clone https://github.com/LFManifesto/LXMFMonero.git
cd LXMFMonero

# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install
pip install -e .
```

## Wallet Setup

### Creating the Wallet Pair

You need two wallets created from the **same seed**:
1. **Cold wallet** (full wallet with spend key) - stays on client machine
2. **View-only wallet** (no spend key) - goes on hub machine

**Step 1: Create or restore the cold wallet**
```bash
monero-wallet-cli --generate-new-wallet /path/to/cold-wallet
# Or restore from seed:
monero-wallet-cli --restore-deterministic-wallet --wallet-file /path/to/cold-wallet
```

**Step 2: Export view-only wallet**
```bash
monero-wallet-cli --wallet-file /path/to/cold-wallet
# In wallet, run:
viewkey
# Note the secret view key
address
# Note the primary address
```

**Step 3: Create view-only wallet on hub machine**
```bash
monero-wallet-cli --generate-from-view-key /path/to/viewonly-wallet \
    --address <your-primary-address> \
    --viewkey <your-secret-view-key>
```

**Important**: Use an empty password or the same password on both wallets for simplicity with wallet-rpc.

## Quick Start

### Hub Setup (Server with monerod)

The hub runs alongside a view-only Monero wallet and handles requests from clients.

**1. Ensure monerod is running and synced**

The hub's wallet-rpc needs to connect to monerod. Use the **unrestricted RPC port** (typically 18083):

```bash
# Check monerod is accessible
curl -s http://127.0.0.1:18083/json_rpc \
  -d '{"jsonrpc":"2.0","id":"0","method":"get_info"}' | jq .result.height
```

**2. Start wallet-rpc with view-only wallet**
```bash
monero-wallet-rpc \
    --wallet-file /path/to/viewonly-wallet \
    --password '' \
    --rpc-bind-port 18085 \
    --disable-rpc-login \
    --daemon-address 127.0.0.1:18083
```

**3. Start the hub**
```bash
lxmfmonero-hub --wallet-rpc http://127.0.0.1:18085/json_rpc
```

**4. Note the destination hash** printed at startup (e.g., `f5ad834014699eadaf90685d141d89b1`)

### Client Setup (Cold Wallet Machine)

The client holds the spend key and can be air-gapped from the internet (only needs Reticulum connectivity).

**1. Start wallet-rpc in offline mode**
```bash
monero-wallet-rpc \
    --wallet-file /path/to/cold-wallet \
    --password '' \
    --rpc-bind-port 18087 \
    --disable-rpc-login \
    --offline
```

**2. Verify path to hub**
```bash
rnpath <hub-destination-hash>
# Should show: "Path found, destination is X hops away"
```

**3. Check balance (verifies full connectivity)**
```bash
lxmfmonero-client --hub <hub-destination-hash> balance
```

**4. Send XMR**
```bash
lxmfmonero-client --hub <hub-destination-hash> \
    --cold-wallet http://127.0.0.1:18087/json_rpc \
    send <destination-address> <amount>
```

**5. TUI Interface (Recommended for regular use)**
```bash
lxmfmonero-tui --hub <hub-destination-hash> \
    --cold-wallet http://127.0.0.1:18087/json_rpc
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

**TCP Testnet:**
- Transport: TCPInterface to reticulum.betweentheborders.com:4242
- Round-trip: ~20 seconds for full transaction
- Balance queries: 2-4 seconds

**I2P (Anonymous):**
- Transport: I2PInterface peer-to-peer
- Round-trip: ~35 seconds for full transaction
- Requires i2pd running on client

**Performance:**
- Large payloads: 12KB+ signed transactions delivered reliably
- Mainnet: Multiple transactions successfully broadcast and confirmed

## Example End-to-End Walkthrough

This example shows the complete setup we used for testing.

### Hub Machine (Raspberry Pi with monerod)

```bash
# 1. monerod running in Docker (or natively)
# Exposes unrestricted RPC on port 18083 (localhost only)

# 2. Start view-only wallet-rpc
monero-wallet-rpc \
    --wallet-file ~/.lxmfmonero/wallets/viewonly \
    --password '' \
    --rpc-bind-port 18085 \
    --disable-rpc-login \
    --daemon-address 127.0.0.1:18083

# 3. Start hub (in another terminal)
cd ~/LXMFMonero
source venv/bin/activate
lxmfmonero-hub --wallet-rpc http://127.0.0.1:18085/json_rpc --debug

# Hub announces: f5ad834014699eadaf90685d141d89b1
```

### Client Machine (Mac with cold wallet)

```bash
# 1. Start Reticulum daemon
source ~/venv/bin/activate
rnsd &

# 2. Verify testnet connectivity
rnstatus
# Should show TCPInterface connected

# 3. Start cold wallet-rpc (offline mode)
monero-wallet-rpc \
    --wallet-file ~/.lxmfmonero/cold-wallet \
    --password '' \
    --rpc-bind-port 18087 \
    --disable-rpc-login \
    --offline

# 4. Verify path to hub
rnpath f5ad834014699eadaf90685d141d89b1
# "Path found, destination is 2 hops away"

# 5. Check balance
lxmfmonero-client --hub f5ad834014699eadaf90685d141d89b1 balance
# Balance: 0.00086928 XMR

# 6. Send transaction
lxmfmonero-client \
    --hub f5ad834014699eadaf90685d141d89b1 \
    --cold-wallet http://127.0.0.1:18087/json_rpc \
    send 44Z5ZjuEiZrgTKJxXC3wMbRybZ9FHUDvA2HehTZF7ECK9xTBEkuoYjef2Yp9BJGriq13YzMusvz8u3A9X9XHQjtcJzEBJDZ 0.0001

# Transaction broadcast!
# TX Hash: 8f0295261a2ec04c6d4dcf0c9cc6b30278ab50caf9f6d27a61b562e6f3ebd761
```

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
