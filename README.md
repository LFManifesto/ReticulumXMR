# LXMFMonero

Monero wallet operations over LXMF and the Reticulum Network Stack.

## Overview

LXMFMonero proxies Monero wallet RPC calls over Reticulum using LXMF for message delivery. A "hub" with a view-only wallet connects to monerod. A "client" with a cold wallet signs transactions locally and sends them to the hub for broadcast.

## Test Results

Tested December 2025. Transaction hashes verifiable on Monero blockchain.

### Test Environment

| Component | Specification |
|-----------|---------------|
| Client | MacBook Pro M1, macOS 15.2 |
| Hub | Raspberry Pi 5 (8GB), Debian 12 |
| monerod | v0.18.3.4 (Docker) |
| monero-wallet-rpc | v0.18.3.4 |
| Reticulum | 0.8.4 |
| LXMF | 0.5.4 |
| Python | 3.11 |

### Network Configuration

**TCP Testnet (2 hops):**
```
Mac (cold wallet) -> BetweenTheBorders Testnet -> Pi (hub + monerod)
                     reticulum.betweentheborders.com:4242
```

**I2P (anonymous):**
```
Mac (cold wallet) -> I2P tunnel -> Pi (hub + monerod)
                     kfamlmwnlw3acqfxip4x6kt53i2tr4ksp5h4qxwvxhoq7mchpolq.b32.i2p
```

### Verified Transactions

**TCP/Testnet:**
```
TX Hash: 8f0295261a2ec04c6d4dcf0c9cc6b30278ab50caf9f6d27a61b562e6f3ebd761
Amount:  0.0001 XMR
Fee:     0.000030700000 XMR
Time:    ~20 seconds total
```

**I2P:**
```
TX Hash: a793ff7bd6a0a4b168f72726e2027d283cc5fed0c8c3b1cd6693c6ef7a6fa8ee
Time:    ~35 seconds total
```

### Feature Status

| Feature | Status | Notes |
|---------|--------|-------|
| Balance queries | Pass | 2-4 second round-trip |
| Export outputs | Pass | ~7 seconds TCP, ~18s I2P |
| Create unsigned tx | Pass | 6-7KB payloads |
| Sign transaction | Pass | Local cold wallet signing |
| Submit transaction | Pass | Broadcast confirmed on mainnet |
| Key image sync | Pass | Automatic after transaction |
| I2P transport | Pass | Full transaction verified |
| LoRa/HF transport | Pending | Not yet tested |

### Message Sizes

| Data | Size |
|------|------|
| Balance response | ~500 bytes |
| Export outputs | ~640-820 bytes |
| Unsigned tx | 6-7 KB |
| Signed tx | 12-13 KB |

## Architecture

```
+---------------------+                    +---------------------+
|   COLD CLIENT       |                    |      HUB            |
|                     |                    |                     |
|  - Has spend key    |     LXMF           |  - View-only wallet |
|  - Signs locally    |<------------------>|  - Connected to     |
|  - Air-gapped OK    |   (any transport)  |    monerod          |
|                     |                    |                     |
+---------------------+                    +---------------------+
```

Transaction flow:
1. Client requests balance/tx from Hub (view-only wallet)
2. Hub creates unsigned transaction
3. Client signs locally with spend key
4. Client sends signed transaction to Hub
5. Hub broadcasts to Monero network
6. Client exports key images to Hub for balance sync

## Installation

### Prerequisites

- Python 3.9+
- Reticulum and LXMF: `pip install rns lxmf`
- Monero CLI tools from https://getmonero.org/downloads/

### Install LXMFMonero

```bash
git clone https://github.com/LFManifesto/LXMFMonero.git
cd LXMFMonero
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### Configure Reticulum

Edit `~/.reticulum/config`:

```ini
[interfaces]
  [[RNS Testnet BetweenTheBorders]]
    type = TCPClientInterface
    enabled = yes
    target_host = reticulum.betweentheborders.com
    target_port = 4242
```

Start daemon:
```bash
rnsd &
rnstatus  # verify connectivity
```

### Create Wallet Pair

Cold and view-only wallets must derive from the same seed.

**Create cold wallet:**
```bash
monero-wallet-cli --generate-new-wallet /path/to/cold-wallet
```

**Export view key:**
```bash
monero-wallet-cli --wallet-file /path/to/cold-wallet
# In wallet:
viewkey   # note secret view key
address   # note primary address
```

**Create view-only wallet on hub:**
```bash
monero-wallet-cli --generate-from-view-key /path/to/viewonly-wallet \
    --address <primary-address> \
    --viewkey <secret-view-key>
```

## Usage

### Hub Setup

1. Verify monerod is accessible (use unrestricted RPC port 18083):
```bash
curl -s http://127.0.0.1:18083/json_rpc \
  -d '{"jsonrpc":"2.0","id":"0","method":"get_info"}' | jq .result.height
```

2. Start wallet-rpc with view-only wallet:
```bash
monero-wallet-rpc \
    --wallet-file /path/to/viewonly-wallet \
    --password '' \
    --rpc-bind-port 18085 \
    --disable-rpc-login \
    --daemon-address 127.0.0.1:18083
```

3. Start hub:
```bash
lxmfmonero-hub --wallet-rpc http://127.0.0.1:18085/json_rpc
```

Note the destination hash printed at startup.

### Client Setup

1. Start wallet-rpc with cold wallet (offline mode):
```bash
monero-wallet-rpc \
    --wallet-file /path/to/cold-wallet \
    --password '' \
    --rpc-bind-port 18087 \
    --disable-rpc-login \
    --offline
```

2. Verify path to hub:
```bash
rnpath <hub-destination-hash>
# Expected: "Path found, destination is X hops away"
```

3. Check balance:
```bash
lxmfmonero-client --hub <hub-destination-hash> balance
```

4. Send XMR:
```bash
lxmfmonero-client --hub <hub-destination-hash> \
    --cold-wallet http://127.0.0.1:18087/json_rpc \
    send <destination-address> <amount>
```

5. TUI interface:
```bash
lxmfmonero-tui --hub <hub-destination-hash> \
    --cold-wallet http://127.0.0.1:18087/json_rpc
```

### Command Options

**Hub:**
```
--identity, -i    Identity file path (default: ~/.lxmfmonero/hub/identity)
--storage, -s     LXMF storage path (default: ~/.lxmfmonero/hub/storage)
--wallet-rpc, -w  wallet-rpc URL (default: http://127.0.0.1:18082/json_rpc)
--name, -n        Display name for announcements
--announce-interval, -a  Seconds between announces (0 to disable)
```

**Client:**
```
--identity, -i    Identity file path
--storage, -s     LXMF storage path
--hub, -H         Hub destination hash (required)
--cold-wallet, -c Cold wallet-rpc URL (default: http://127.0.0.1:18083/json_rpc)
--timeout, -t     Request timeout seconds (default: 300)
```

## Troubleshooting

### "Key image already spent in blockchain"

The view-only wallet is out of sync with the cold wallet. Export key images from cold wallet and import to view-only:

```bash
# Export from cold wallet
curl -s http://127.0.0.1:18087/json_rpc \
  -d '{"jsonrpc":"2.0","id":"0","method":"export_key_images","params":{"all":true}}'

# Import to view-only wallet (on hub)
curl -s http://127.0.0.1:18085/json_rpc \
  -d '{"jsonrpc":"2.0","id":"0","method":"import_key_images","params":{"signed_key_images":[...]}}'
```

### "Request timed out"

1. Check Reticulum connectivity: `rnpath <hub-hash>`
2. Verify hub is running and announcing
3. Check if path exists through testnet

### "Insufficient balance"

- Balance may include locked outputs
- Wait for outputs to unlock (10 blocks after receiving)
- Check `unlocked_balance` vs `balance`

### "Transaction rejected by daemon"

1. Enable monerod logging:
```bash
curl http://127.0.0.1:18083/set_log_level -d '{"level":2}'
```
2. Check monerod logs for rejection reason
3. Common causes: double spend, invalid ring members, key images already spent

### Wallet Setup Issues

- Cold and view-only wallets must derive from same seed
- View-only wallet needs secret view key (not spend key)
- Cold wallet must start with `--offline` flag
- View-only wallet connects to monerod on unrestricted RPC port (18083, not 18081)

## Security

- Hub has view-only access only; cannot spend funds
- Client holds spend key; signs transactions locally
- All communication encrypted by Reticulum (X25519 ECDH, AES-256)
- LXMF provides forward secrecy

## References

- Reticulum Network Stack: https://reticulum.network/ (accessed December 2025)
- Reticulum Manual: https://markqvist.github.io/Reticulum/manual/ (accessed December 2025)
- LXMF Protocol: https://github.com/markqvist/LXMF (accessed December 2025)
- Monero: https://getmonero.org/ (accessed December 2025)
- Monero RPC Documentation: https://www.getmonero.org/resources/developer-guides/wallet-rpc.html (accessed December 2025)

## License

MIT License - See LICENSE file

## Author

Light Fighter Manifesto L.L.C.
https://lightfightermanifesto.org
