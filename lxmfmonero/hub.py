"""
LXMFMonero Hub - View-only wallet server using LXMF messaging

The hub runs alongside a view-only Monero wallet and handles requests
from cold wallet clients over LXMF. Messages are delivered reliably
over any Reticulum transport (HF radio, LoRa, I2P, etc.).

Architecture:
    Client (cold wallet) <-- LXMF --> Hub (view-only) --> monerod

The hub:
- Creates unsigned transactions for client signing
- Submits signed transactions to the network
- Exports outputs for cold wallet sync
- Imports key images for accurate balance tracking
"""

import RNS
import LXMF
import json
import logging
import time
from pathlib import Path
from typing import Optional, Callable

from .wallet_rpc import WalletRPCClient
from .messages import (
    MessageType,
    parse_message,
    BalanceRequest,
    ExportOutputsRequest,
    CreateTxRequest,
    SubmitTxRequest,
    ImportKeyImagesRequest,
    BalanceResponse,
    ExportOutputsResponse,
    CreateTxResponse,
    SubmitTxResponse,
    ImportKeyImagesResponse,
    ErrorResponse,
)

logger = logging.getLogger(__name__)


class MoneroHub:
    """
    LXMF-based Monero hub server

    Receives requests via LXMF messages and processes them using
    a view-only wallet connected to monerod.
    """

    def __init__(
        self,
        identity_path: str,
        storage_path: str,
        wallet_rpc_url: str = "http://127.0.0.1:18082/json_rpc",
        display_name: str = "MoneroHub",
        announce_interval: int = 600,
    ):
        """
        Initialize MoneroHub

        Args:
            identity_path: Path to identity file (created if not exists)
            storage_path: Path for LXMF storage (messages, ratchets)
            wallet_rpc_url: URL of monero-wallet-rpc
            display_name: Display name for LXMF announcements
            announce_interval: Seconds between announcements (0 to disable)
        """
        self.identity_path = Path(identity_path)
        self.storage_path = Path(storage_path)
        self.wallet_rpc_url = wallet_rpc_url
        self.display_name = display_name
        self.announce_interval = announce_interval

        # Create storage directory
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Initialize Reticulum
        self.reticulum = RNS.Reticulum()

        # Load or create identity
        if self.identity_path.exists():
            self.identity = RNS.Identity.from_file(str(self.identity_path))
            logger.info(f"Loaded identity from {self.identity_path}")
        else:
            self.identity = RNS.Identity()
            self.identity.to_file(str(self.identity_path))
            logger.info(f"Created new identity at {self.identity_path}")

        # Create LXMF router
        self.router = LXMF.LXMRouter(
            identity=self.identity,
            storagepath=str(self.storage_path)
        )

        # Register delivery destination
        self.destination = self.router.register_delivery_identity(
            self.identity,
            display_name=display_name
        )

        # Register message handler
        self.router.register_delivery_callback(self._handle_lxmf_message)

        # Initialize wallet RPC client
        self.wallet_rpc = WalletRPCClient(wallet_rpc_url)

        # Stats
        self.start_time = time.time()
        self.messages_received = 0
        self.messages_sent = 0
        self.last_announce = 0

        # Running state
        self.running = False

        logger.info(f"MoneroHub initialized")
        logger.info(f"  Identity: {RNS.prettyhexrep(self.identity.hash)}")
        logger.info(f"  Destination: {RNS.prettyhexrep(self.destination.hash)}")

    def start(self):
        """Start the hub and announce presence"""
        self.running = True

        # Announce presence
        self._announce()

        logger.info("MoneroHub started")

    def stop(self):
        """Stop the hub"""
        self.running = False
        logger.info("MoneroHub stopped")

    def _announce(self):
        """Announce hub presence on the network"""
        self.router.announce(self.destination.hash)
        self.last_announce = time.time()
        logger.info("Announced hub presence")

    def run(self):
        """Run the hub main loop"""
        self.start()

        try:
            while self.running:
                # Periodic announce
                if self.announce_interval > 0:
                    if time.time() - self.last_announce > self.announce_interval:
                        self._announce()

                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Interrupted")
        finally:
            self.stop()

    def _handle_lxmf_message(self, message: LXMF.LXMessage):
        """
        Handle incoming LXMF message

        Args:
            message: Received LXMF message
        """
        self.messages_received += 1
        source_hash = message.source_hash

        logger.info(f"Received message from {RNS.prettyhexrep(source_hash)}")
        logger.debug(f"Message content: {message.content_as_string()[:100]}...")

        try:
            # Parse the message
            content = message.content_as_string()
            request = parse_message(content)

            logger.info(f"Processing {request.type} request (id: {request.request_id[:8]}...)")

            # Route to handler
            response = self._process_request(request)

            # Send response back
            self._send_response(source_hash, response)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message JSON: {e}")
            self._send_response(source_hash, ErrorResponse(
                request_id="unknown",
                error=f"Invalid JSON: {e}"
            ))
        except ValueError as e:
            logger.error(f"Failed to parse message: {e}")
            self._send_response(source_hash, ErrorResponse(
                request_id="unknown",
                error=str(e)
            ))
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            request_id = getattr(request, 'request_id', 'unknown') if 'request' in dir() else 'unknown'
            self._send_response(source_hash, ErrorResponse(
                request_id=request_id,
                error=str(e)
            ))

    def _process_request(self, request) -> object:
        """
        Process request and return response

        Args:
            request: Parsed request message

        Returns:
            Response message object
        """
        if isinstance(request, BalanceRequest):
            return self._handle_balance(request)
        elif isinstance(request, ExportOutputsRequest):
            return self._handle_export_outputs(request)
        elif isinstance(request, CreateTxRequest):
            return self._handle_create_tx(request)
        elif isinstance(request, SubmitTxRequest):
            return self._handle_submit_tx(request)
        elif isinstance(request, ImportKeyImagesRequest):
            return self._handle_import_key_images(request)
        else:
            return ErrorResponse(
                request_id=request.request_id,
                error=f"Unknown request type: {request.type}"
            )

    def _send_response(self, dest_hash: bytes, response):
        """
        Send response message via LXMF

        Args:
            dest_hash: Destination hash (16 bytes)
            response: Response message object
        """
        # Recall the destination identity
        dest_identity = RNS.Identity.recall(dest_hash)

        if not dest_identity:
            logger.warning(f"Cannot recall identity for {RNS.prettyhexrep(dest_hash)}")
            # Request path and try again later? For now just log
            return

        # Create destination
        destination = RNS.Destination(
            dest_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            "lxmf", "delivery"
        )

        # Create LXMF message
        # Source must be our delivery destination (not identity)
        content = response.to_json()
        lxm = LXMF.LXMessage(
            destination,
            self.destination,
            content=content,
            title="MoneroHub Response"
        )

        # Track delivery
        lxm.register_delivery_callback(self._delivery_callback)

        # Send
        self.router.handle_outbound(lxm)
        self.messages_sent += 1

        logger.info(f"Sent {response.type} response ({len(content)} bytes)")

    def _delivery_callback(self, message: LXMF.LXMessage):
        """Callback for message delivery status"""
        if message.state == LXMF.LXMessage.DELIVERED:
            logger.debug(f"Message delivered: {RNS.prettyhexrep(message.hash)}")
        elif message.state == LXMF.LXMessage.FAILED:
            logger.warning(f"Message delivery failed: {RNS.prettyhexrep(message.hash)}")

    # Request handlers

    def _handle_balance(self, request: BalanceRequest) -> BalanceResponse:
        """Handle balance request"""
        logger.info(f"Balance request from operator: {request.operator_id}")

        # Refresh wallet
        refresh_result = self.wallet_rpc.refresh()
        if "error" in refresh_result:
            logger.warning(f"Refresh warning: {refresh_result['error']}")

        # Get balance
        result = self.wallet_rpc.get_balance()

        if "error" in result:
            error_msg = result["error"].get("message", str(result["error"]))
            return BalanceResponse(
                request_id=request.request_id,
                success=False,
                error=error_msg
            )

        balance_data = result.get("result", {})
        balance_atomic = balance_data.get("balance", 0)
        unlocked_atomic = balance_data.get("unlocked_balance", 0)

        # Get height
        height_result = self.wallet_rpc.get_height()
        height = height_result.get("result", {}).get("height", 0)

        return BalanceResponse(
            request_id=request.request_id,
            success=True,
            balance=balance_atomic / 1e12,
            unlocked_balance=unlocked_atomic / 1e12,
            block_height=height
        )

    def _handle_export_outputs(self, request: ExportOutputsRequest) -> ExportOutputsResponse:
        """Handle export outputs request"""
        logger.info(f"Export outputs request from operator: {request.operator_id}")

        result = self.wallet_rpc.export_outputs(all_outputs=request.all_outputs)

        if "error" in result:
            error_msg = result["error"].get("message", str(result["error"]))
            return ExportOutputsResponse(
                request_id=request.request_id,
                success=False,
                error=error_msg
            )

        outputs_data = result.get("result", {})
        outputs_hex = outputs_data.get("outputs_data_hex", "")

        logger.info(f"Exported outputs: {len(outputs_hex)} chars")

        return ExportOutputsResponse(
            request_id=request.request_id,
            success=True,
            outputs_data_hex=outputs_hex
        )

    def _handle_create_tx(self, request: CreateTxRequest) -> CreateTxResponse:
        """Handle create transaction request"""
        logger.info(f"Create tx: {request.amount} XMR to {request.destination[:20]}...")

        # Convert XMR to atomic units
        amount_atomic = int(request.amount * 1e12)

        result = self.wallet_rpc.transfer(
            destinations=[{
                "amount": amount_atomic,
                "address": request.destination
            }],
            priority=request.priority,
            do_not_relay=True,
            get_tx_metadata=True
        )

        if "error" in result:
            error_msg = result["error"].get("message", str(result["error"]))
            logger.error(f"Failed to create tx: {error_msg}")
            return CreateTxResponse(
                request_id=request.request_id,
                success=False,
                error=error_msg
            )

        tx_data = result.get("result", {})
        unsigned_txset = tx_data.get("unsigned_txset", "")

        if not unsigned_txset:
            # Fallback to tx_metadata
            unsigned_txset = tx_data.get("tx_metadata", "")

        fee_atomic = tx_data.get("fee", 0)

        logger.info(f"Created unsigned tx: {len(unsigned_txset)} chars, fee: {fee_atomic / 1e12} XMR")

        return CreateTxResponse(
            request_id=request.request_id,
            success=True,
            unsigned_txset=unsigned_txset,
            fee=fee_atomic / 1e12,
            amount=request.amount
        )

    def _handle_submit_tx(self, request: SubmitTxRequest) -> SubmitTxResponse:
        """Handle submit signed transaction request"""
        logger.info(f"Submit tx from operator: {request.operator_id}")

        tx_hash = None
        error_msg = None

        # Try submit_transfer first (for cold-signed transactions)
        result = self.wallet_rpc.submit_transfer(request.signed_txset)

        if "error" not in result:
            tx_result = result.get("result", {})
            tx_hash_list = tx_result.get("tx_hash_list", [])
            tx_hash = tx_hash_list[0] if tx_hash_list else ""
        else:
            # Try relay_tx as fallback
            logger.info("submit_transfer failed, trying relay_tx...")
            result = self.wallet_rpc.relay_tx(request.signed_txset)

            if "error" not in result:
                tx_hash = result.get("result", {}).get("tx_hash", "")
            else:
                error_msg = result["error"].get("message", str(result["error"]))
                logger.error(f"Failed to submit tx: {error_msg}")

        if tx_hash:
            logger.info(f"Transaction broadcast: {tx_hash}")
            return SubmitTxResponse(
                request_id=request.request_id,
                success=True,
                tx_hash=tx_hash
            )
        else:
            return SubmitTxResponse(
                request_id=request.request_id,
                success=False,
                error=error_msg or "Unknown error"
            )

    def _handle_import_key_images(self, request: ImportKeyImagesRequest) -> ImportKeyImagesResponse:
        """Handle import key images request"""
        logger.info(f"Import key images from operator: {request.operator_id}")

        result = self.wallet_rpc.import_key_images(
            signed_key_images=request.signed_key_images,
            offset=request.offset
        )

        if "error" in result:
            error_msg = result["error"].get("message", str(result["error"]))
            return ImportKeyImagesResponse(
                request_id=request.request_id,
                success=False,
                error=error_msg
            )

        import_data = result.get("result", {})

        logger.info(f"Imported key images, spent: {import_data.get('spent', 0)}")

        return ImportKeyImagesResponse(
            request_id=request.request_id,
            success=True,
            height=import_data.get("height", 0),
            spent=import_data.get("spent", 0),
            unspent=import_data.get("unspent", 0)
        )

    def get_stats(self) -> dict:
        """Get hub statistics"""
        return {
            "identity": RNS.hexrep(self.identity.hash, delimit=False),
            "destination": RNS.hexrep(self.destination.hash, delimit=False),
            "uptime_seconds": time.time() - self.start_time,
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "wallet_rpc_url": self.wallet_rpc_url,
        }


def main():
    """Run hub from command line"""
    import argparse

    parser = argparse.ArgumentParser(description="LXMFMonero Hub")
    parser.add_argument("--identity", "-i", default="~/.lxmfmonero/hub/identity",
                        help="Path to identity file")
    parser.add_argument("--storage", "-s", default="~/.lxmfmonero/hub/storage",
                        help="Path to LXMF storage directory")
    parser.add_argument("--wallet-rpc", "-w", default="http://127.0.0.1:18082/json_rpc",
                        help="wallet-rpc URL")
    parser.add_argument("--name", "-n", default="MoneroHub",
                        help="Display name for announcements")
    parser.add_argument("--announce-interval", "-a", type=int, default=600,
                        help="Announce interval in seconds (0 to disable)")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    # Expand paths
    identity_path = Path(args.identity).expanduser()
    storage_path = Path(args.storage).expanduser()

    # Create hub
    hub = MoneroHub(
        identity_path=str(identity_path),
        storage_path=str(storage_path),
        wallet_rpc_url=args.wallet_rpc,
        display_name=args.name,
        announce_interval=args.announce_interval
    )

    # Print info
    print(f"\nLXMFMonero Hub")
    print(f"=" * 40)
    stats = hub.get_stats()
    print(f"Identity:    {stats['identity']}")
    print(f"Destination: {stats['destination']}")
    print(f"Wallet RPC:  {stats['wallet_rpc_url']}")
    print(f"=" * 40)
    print(f"\nPress Ctrl+C to stop\n")

    # Run
    hub.run()


if __name__ == "__main__":
    main()
