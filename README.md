# ReticulumXMR

**Monero transactions over Reticulum mesh networks**

ReticulumXMR enables off-grid Monero transactions over low-bandwidth mesh networks like HF radio, LoRa, and packet radio using the [Reticulum Network Stack](https://reticulum.network/).

## Status

**Cold Signing Mode: VERIFIED WORKING** - Balance queries and transaction workflows tested on 2025-12-06.

| Feature | Status |
|---------|--------|
| Balance queries over Reticulum | Working |
| Cold signing workflow | Working |
| Transaction broadcast | Working |
| TCP/IP transport | Verified |
| I2P transport | Verified |
| LoRa transport | Untested |
| HF radio transport | Untested |

## Use Case

You're in a remote location with no internet. You have a LoRa radio or HF transceiver connected to your laptop. Back at your base, there's a Raspberry Pi with internet running a Monero node. Using ReticulumXMR, you can:

1. Check your Monero balance
2. Create and sign transactions locally
3. Broadcast them to the network

All communication happens over encrypted Reticulum channels - your private keys never leave your device.

## Privacy

**Both Reticulum and Monero privacy are fully preserved:**

| Layer | Privacy Feature |
|-------|-----------------|
| Reticulum | End-to-end encryption (X25519 + AES-256) |
| Reticulum | No IP addresses in mesh routing |
| Reticulum | Forward secrecy on all links |
| Monero | Private keys stay on your device |
| Monero | View key on hub cannot spend funds |
| Monero | Standard Monero privacy (ring signatures, stealth addresses) |

The hub only has a **view-only wallet** - it can see your balance but cannot spend your funds. Transaction signing happens locally on your client device.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              YOUR SETUP                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────┐        Reticulum Mesh        ┌──────────────────┐    │
│   │   CLIENT (You)   │◄────────────────────────────►│   HUB (Base)     │    │
│   │                  │   LoRa / HF Radio / TCP      │                  │    │
│   │  Terminal 1:     │                              │  - monerod       │    │
│   │   nomadnet       │                              │  - wallet-rpc    │    │
│   │                  │                              │  - view-only     │    │
│   │  Terminal 2:     │                              │    wallet        │    │
│   │   reticulumxmr   │                              │  - Internet      │    │
│   │   client         │                              │                  │    │
│   │                  │                              │                  │    │
│   │  Your wallet     │                              │                  │    │
│   │  (spend key)     │                              │                  │    │
│   └──────────────────┘                              └──────────────────┘    │
│                                                              │               │
│                                                              ▼               │
│                                                     ┌──────────────────┐    │
│                                                     │  Monero Network  │    │
│                                                     └──────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Intended Usage: Two Terminals**
- **Terminal 1**: `nomadnet` or `rnsh` for LXMF messaging and peer coordination
- **Terminal 2**: `reticulumxmr-client` for Monero operations

## Cold Signing Workflow

1. **Client** requests balance from hub
2. **Hub** queries view-only wallet, returns balance
3. **Client** requests transaction (destination, amount)
4. **Hub** creates unsigned transaction (~4 KB)
5. **Client** signs locally with spend key (~3 KB)
6. **Client** sends signed tx to hub
7. **Hub** broadcasts to Monero network
8. **Hub** returns tx hash confirmation

**Total data: ~8 KB per transaction** - feasible over 1200 bps radio links.

## Installation

### Requirements

- Python 3.9+
- Reticulum Network Stack (`pip install rns`)
- Monero daemon (monerod) - hub only
- monero-wallet-rpc - both hub and client

### Install

```bash
git clone https://github.com/LFManifesto/ReticulumXMR.git
cd ReticulumXMR
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

## Hub Setup

The hub runs on a device with internet access (Raspberry Pi recommended).

### 1. Sync monerod

```bash
monerod --data-dir ~/.bitmonero --prune-blockchain
```

### 2. Create view-only wallet

From your main wallet, export the view key:
```bash
monero-wallet-cli
> viewkey
```

Create view-only wallet on hub:
```bash
monero-wallet-cli --generate-from-view-key viewonly_wallet
```

### 3. Start wallet-rpc

```bash
monero-wallet-rpc \
    --wallet-dir ~/.reticulumxmr/wallets \
    --rpc-bind-port 18085 \
    --disable-rpc-login \
    --daemon-address 127.0.0.1:18081
```

Open the wallet:
```bash
curl -X POST http://127.0.0.1:18085/json_rpc -d '{
  "jsonrpc":"2.0","id":"0","method":"open_wallet",
  "params":{"filename":"viewonly_wallet","password":""}
}' -H 'Content-Type: application/json'
```

### 4. Start Reticulum and Hub

```bash
rnsd  # Start Reticulum daemon
python -m reticulumxmr.hub
```

The hub will display its destination hash - clients need this to connect.

## Client Setup

### 1. Start Reticulum

```bash
rnsd
```

### 2. Start wallet-rpc with your full wallet

```bash
monero-wallet-rpc \
    --wallet-file ~/your-wallet \
    --rpc-bind-port 18083 \
    --disable-rpc-login \
    --prompt-for-password
```

### 3. Connect to hub

```bash
# Check balance
python -m reticulumxmr.client <hub-destination-hash> balance

# Send XMR
python -m reticulumxmr.client <hub-destination-hash> send <address> <amount>
```

## CLI Usage

```bash
# Get balance
$ reticulumxmr-client <hub-hash> balance
Balance: 0.008969260000 XMR
Unlocked: 0.008969260000 XMR
Block height: 3559948

# Send transaction
$ reticulumxmr-client <hub-hash> send 4Bxxx... 0.001
Creating transaction:
  To: 4Bxxx...
  Amount: 0.001 XMR
  Priority: 1

Transaction broadcast!
  TX Hash: b9b45d1be49ee...
  Fee: 0.000021 XMR

# Export outputs (for cold wallet sync)
$ reticulumxmr-client <hub-hash> export-outputs
```

## Data Sizes

Optimized for low-bandwidth mesh links:

| Operation | Size | Time @ 1200 bps | Time @ 300 bps |
|-----------|------|-----------------|----------------|
| Balance query | ~500 B | <1 sec | ~13 sec |
| Unsigned tx | ~4 KB | ~27 sec | ~107 sec |
| Signed tx | ~3 KB | ~20 sec | ~80 sec |
| **Full transaction** | **~8 KB** | **~53 sec** | **~3.5 min** |

## Reticulum Configuration

Ensure your Reticulum config (`~/.reticulum/config`) has appropriate interfaces:

```ini
# For TCP (testing/local)
[[TCP Interface]]
  type = TCPClientInterface
  enabled = yes
  target_host = your-hub-ip
  target_port = 4242

# For LoRa
[[LoRa Interface]]
  type = RNodeInterface
  port = /dev/ttyUSB0
  frequency = 915000000
  bandwidth = 125000
  txpower = 17
```

## Protocol Messages

| Message | Direction | Purpose |
|---------|-----------|---------|
| ModeSelectionMessage | Client→Hub | Select cold_signing mode |
| BalanceRequestMessage | Client→Hub | Request balance |
| BalanceResponseMessage | Hub→Client | Return balance info |
| CreateTransactionMessage | Client→Hub | Request unsigned tx |
| UnsignedTransactionMessage | Hub→Client | Return unsigned tx |
| SignedTransactionMessage | Client→Hub | Submit for broadcast |
| TransactionResultMessage | Hub→Client | Broadcast confirmation |

## Security Model

- **Private keys**: Never leave client device
- **View key**: Hub can see balance, cannot spend
- **Transport**: End-to-end encrypted via Reticulum
- **Signing**: All transactions signed locally
- **No trust required**: Hub cannot steal funds

## Tested Transactions

| Date | TX Hash | Transport |
|------|---------|-----------|
| 2025-12-03 | `b9b45d1be49ee963...` | TCP via Reticulum |
| 2025-12-06 | Balance queries verified | TCP + I2P |

## Roadmap

- [x] Cold signing workflow
- [x] Balance queries
- [x] Transaction broadcast
- [ ] TUI client interface
- [ ] LoRa transport testing
- [ ] HF radio transport testing
- [ ] Multi-operator support
- [ ] Automatic key image sync

## Dependencies

- [Reticulum](https://github.com/markqvist/Reticulum) - Cryptographic mesh networking
- [msgpack](https://msgpack.org/) - Efficient message serialization
- [requests](https://requests.readthedocs.io/) - HTTP client for wallet-rpc

## License

MIT License - See LICENSE file

## Contributing

Pull requests welcome. Testing on actual mesh hardware (LoRa, HF radio) especially appreciated.

## Acknowledgments

- [Monero Project](https://getmonero.org/) - Private digital currency
- [Mark Qvist](https://github.com/markqvist) - Reticulum creator
- Light Fighter Manifesto L.L.C.
