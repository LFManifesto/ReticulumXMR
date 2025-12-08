"""
LXMFMonero Client - Cold wallet client using LXMF messaging

The client holds the spend key and communicates with a hub (view-only wallet)
over LXMF to perform Monero transactions.

Architecture:
    Client (cold wallet) <-- LXMF --> Hub (view-only) --> monerod

The client:
- Requests balance and transaction creation from hub
- Signs transactions locally with spend key
- Sends signed transactions to hub for broadcast
- Exports key images to hub for accurate balance tracking
"""

import RNS
import LXMF
import json
import logging
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any

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
    is_response,
)

logger = logging.getLogger(__name__)


class MoneroClient:
    """
    LXMF-based Monero client

    Communicates with a MoneroHub via LXMF messages to perform Monero
    transactions using a cold signing workflow.
    """

    def __init__(
        self,
        identity_path: str,
        storage_path: str,
        hub_hash: str,
        cold_wallet_rpc: str = "http://127.0.0.1:18083/json_rpc",
        operator_id: str = "default",
        display_name: str = "MoneroClient",
        default_timeout: int = 300,
    ):
        """
        Initialize MoneroClient

        Args:
            identity_path: Path to identity file (created if not exists)
            storage_path: Path for LXMF storage
            hub_hash: Hex string of hub destination hash (32 chars)
            cold_wallet_rpc: URL of local cold wallet-rpc
            operator_id: Operator identifier for hub
            display_name: Display name for LXMF
            default_timeout: Default request timeout in seconds
        """
        self.identity_path = Path(identity_path)
        self.storage_path = Path(storage_path)
        self.hub_hash = bytes.fromhex(hub_hash)
        self.cold_wallet_rpc = cold_wallet_rpc
        self.operator_id = operator_id
        self.display_name = display_name
        self.default_timeout = default_timeout

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

        # Register to receive responses
        self.destination = self.router.register_delivery_identity(
            self.identity,
            display_name=display_name
        )

        # Register message handler
        self.router.register_delivery_callback(self._handle_lxmf_message)

        # Announce our presence so hub can respond to us
        self.router.announce(self.destination.hash)

        # Pending requests - map request_id to (event, response)
        self.pending: Dict[str, Dict] = {}
        self.pending_lock = threading.Lock()

        # Local cold wallet RPC
        self.cold_wallet = WalletRPCClient(cold_wallet_rpc)

        # Stats
        self.messages_sent = 0
        self.messages_received = 0

        logger.info(f"MoneroClient initialized")
        logger.info(f"  Identity: {RNS.prettyhexrep(self.identity.hash)}")
        logger.info(f"  Hub: {RNS.prettyhexrep(self.hub_hash)}")

    def _handle_lxmf_message(self, message: LXMF.LXMessage):
        """Handle incoming LXMF message (response from hub)"""
        self.messages_received += 1

        try:
            content = message.content_as_string()
            response = parse_message(content)

            logger.debug(f"Received response: {response.type}")

            request_id = response.request_id

            with self.pending_lock:
                if request_id in self.pending:
                    self.pending[request_id]["response"] = response
                    self.pending[request_id]["event"].set()
                else:
                    logger.warning(f"Received response for unknown request: {request_id}")

        except Exception as e:
            logger.error(f"Error handling response: {e}", exc_info=True)

    def _send_request(self, request, timeout: int = None) -> Optional[Any]:
        """
        Send request to hub and wait for response

        Args:
            request: Request message object
            timeout: Timeout in seconds (uses default if not specified)

        Returns:
            Response message or None on timeout
        """
        timeout = timeout or self.default_timeout
        request_id = request.request_id

        # Set up response tracking
        event = threading.Event()
        with self.pending_lock:
            self.pending[request_id] = {"event": event, "response": None}

        try:
            # Get hub identity
            hub_identity = RNS.Identity.recall(self.hub_hash)

            if not hub_identity:
                logger.info("Hub identity not known, requesting path...")
                RNS.Transport.request_path(self.hub_hash)

                # Wait for path (up to 30 seconds)
                for _ in range(30):
                    time.sleep(1)
                    hub_identity = RNS.Identity.recall(self.hub_hash)
                    if hub_identity:
                        break

                if not hub_identity:
                    logger.error("Could not resolve hub identity")
                    return None

            # Create destination
            destination = RNS.Destination(
                hub_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "lxmf", "delivery"
            )

            # Create LXMF message
            # Source must be our delivery destination (not identity)
            content = request.to_json()
            lxm = LXMF.LXMessage(
                destination,
                self.destination,
                content=content,
                title="MoneroClient Request"
            )

            # Send
            self.router.handle_outbound(lxm)
            self.messages_sent += 1

            logger.info(f"Sent {request.type} request ({len(content)} bytes)")

            # Wait for response
            if event.wait(timeout):
                with self.pending_lock:
                    response = self.pending[request_id]["response"]
                return response
            else:
                logger.warning(f"Request timed out after {timeout}s")
                return None

        finally:
            # Cleanup
            with self.pending_lock:
                self.pending.pop(request_id, None)

    # High-level operations

    def get_balance(self, timeout: int = None) -> Dict[str, Any]:
        """
        Get wallet balance from hub

        Returns:
            Dict with balance info or error
        """
        request = BalanceRequest(operator_id=self.operator_id)
        response = self._send_request(request, timeout)

        if response is None:
            return {"success": False, "error": "Request timed out"}

        if isinstance(response, BalanceResponse):
            if response.success:
                return {
                    "success": True,
                    "balance": response.balance,
                    "unlocked_balance": response.unlocked_balance,
                    "block_height": response.block_height,
                }
            else:
                return {"success": False, "error": response.error}
        else:
            return {"success": False, "error": f"Unexpected response: {response.type}"}

    def export_outputs(self, all_outputs: bool = True, timeout: int = None) -> Dict[str, Any]:
        """
        Request outputs export from hub

        Returns:
            Dict with outputs_data_hex or error
        """
        request = ExportOutputsRequest(
            operator_id=self.operator_id,
            all_outputs=all_outputs
        )
        response = self._send_request(request, timeout)

        if response is None:
            return {"success": False, "error": "Request timed out"}

        if isinstance(response, ExportOutputsResponse):
            if response.success:
                return {
                    "success": True,
                    "outputs_data_hex": response.outputs_data_hex,
                }
            else:
                return {"success": False, "error": response.error}
        else:
            return {"success": False, "error": f"Unexpected response: {response.type}"}

    def import_outputs_locally(self, outputs_data_hex: str) -> Dict[str, Any]:
        """
        Import outputs into local cold wallet

        Args:
            outputs_data_hex: Hex-encoded outputs from hub

        Returns:
            Dict with result or error
        """
        result = self.cold_wallet.import_outputs(outputs_data_hex)

        if "error" in result:
            return {"success": False, "error": result["error"].get("message", str(result["error"]))}

        return {
            "success": True,
            "num_imported": result.get("result", {}).get("num_imported", 0)
        }

    def create_transaction(self, destination: str, amount: float,
                           priority: int = 1, timeout: int = None) -> Dict[str, Any]:
        """
        Request unsigned transaction creation from hub

        Args:
            destination: Destination Monero address
            amount: Amount in XMR
            priority: Transaction priority (0-3)
            timeout: Request timeout

        Returns:
            Dict with unsigned_txset or error
        """
        request = CreateTxRequest(
            operator_id=self.operator_id,
            destination=destination,
            amount=amount,
            priority=priority
        )
        response = self._send_request(request, timeout)

        if response is None:
            return {"success": False, "error": "Request timed out"}

        if isinstance(response, CreateTxResponse):
            if response.success:
                return {
                    "success": True,
                    "unsigned_txset": response.unsigned_txset,
                    "fee": response.fee,
                    "amount": response.amount,
                }
            else:
                return {"success": False, "error": response.error}
        else:
            return {"success": False, "error": f"Unexpected response: {response.type}"}

    def sign_transaction_locally(self, unsigned_txset: str) -> Dict[str, Any]:
        """
        Sign transaction with local cold wallet

        Args:
            unsigned_txset: Unsigned transaction from hub

        Returns:
            Dict with signed_txset or error
        """
        result = self.cold_wallet.sign_transfer(unsigned_txset)

        if "error" in result:
            return {"success": False, "error": result["error"].get("message", str(result["error"]))}

        sign_result = result.get("result", {})
        return {
            "success": True,
            "signed_txset": sign_result.get("signed_txset", ""),
            "tx_hash_list": sign_result.get("tx_hash_list", []),
        }

    def submit_transaction(self, signed_txset: str, timeout: int = None) -> Dict[str, Any]:
        """
        Submit signed transaction to hub for broadcast

        Args:
            signed_txset: Signed transaction data
            timeout: Request timeout

        Returns:
            Dict with tx_hash or error
        """
        request = SubmitTxRequest(
            operator_id=self.operator_id,
            signed_txset=signed_txset
        )
        response = self._send_request(request, timeout)

        if response is None:
            return {"success": False, "error": "Request timed out"}

        if isinstance(response, SubmitTxResponse):
            if response.success:
                return {
                    "success": True,
                    "tx_hash": response.tx_hash,
                }
            else:
                return {"success": False, "error": response.error}
        else:
            return {"success": False, "error": f"Unexpected response: {response.type}"}

    def export_key_images_locally(self, all_images: bool = True) -> Dict[str, Any]:
        """
        Export key images from local cold wallet

        Returns:
            Dict with signed_key_images or error
        """
        result = self.cold_wallet.export_key_images(all_images)

        if "error" in result:
            return {"success": False, "error": result["error"].get("message", str(result["error"]))}

        return {
            "success": True,
            "signed_key_images": result.get("result", {}).get("signed_key_images", []),
        }

    def import_key_images_to_hub(self, signed_key_images: list,
                                  offset: int = 0, timeout: int = None) -> Dict[str, Any]:
        """
        Send key images to hub for import

        Args:
            signed_key_images: List of key image dicts
            offset: Starting offset
            timeout: Request timeout

        Returns:
            Dict with import result or error
        """
        request = ImportKeyImagesRequest(
            operator_id=self.operator_id,
            signed_key_images=signed_key_images,
            offset=offset
        )
        response = self._send_request(request, timeout)

        if response is None:
            return {"success": False, "error": "Request timed out"}

        if isinstance(response, ImportKeyImagesResponse):
            if response.success:
                return {
                    "success": True,
                    "height": response.height,
                    "spent": response.spent,
                    "unspent": response.unspent,
                }
            else:
                return {"success": False, "error": response.error}
        else:
            return {"success": False, "error": f"Unexpected response: {response.type}"}

    # Complete transaction workflow

    def send_transaction(self, destination: str, amount: float,
                         priority: int = 1, timeout: int = None) -> Dict[str, Any]:
        """
        Complete cold signing transaction workflow

        This performs the full sequence:
        1. Export outputs from hub
        2. Import outputs to local cold wallet
        3. Create unsigned tx on hub
        4. Sign locally
        5. Submit to hub for broadcast
        6. Export key images and send to hub

        Args:
            destination: Destination Monero address
            amount: Amount in XMR
            priority: Transaction priority
            timeout: Timeout for each step

        Returns:
            Dict with tx_hash and fee, or error
        """
        logger.info(f"Starting transaction: {amount} XMR to {destination[:20]}...")

        # Step 1: Export outputs from hub
        logger.info("Step 1/6: Exporting outputs from hub...")
        outputs_result = self.export_outputs(all_outputs=True, timeout=timeout)
        if not outputs_result.get("success"):
            return {"success": False, "error": f"Export outputs failed: {outputs_result.get('error')}"}

        # Step 2: Import outputs to local wallet
        logger.info("Step 2/6: Importing outputs to cold wallet...")
        import_result = self.import_outputs_locally(outputs_result["outputs_data_hex"])
        if not import_result.get("success"):
            return {"success": False, "error": f"Import outputs failed: {import_result.get('error')}"}

        # Step 3: Create unsigned tx on hub
        logger.info("Step 3/6: Creating unsigned transaction...")
        create_result = self.create_transaction(destination, amount, priority, timeout)
        if not create_result.get("success"):
            return {"success": False, "error": f"Create tx failed: {create_result.get('error')}"}

        fee = create_result.get("fee", 0)
        logger.info(f"Transaction fee: {fee} XMR")

        # Step 4: Sign locally
        logger.info("Step 4/6: Signing transaction locally...")
        sign_result = self.sign_transaction_locally(create_result["unsigned_txset"])
        if not sign_result.get("success"):
            return {"success": False, "error": f"Sign tx failed: {sign_result.get('error')}"}

        # Step 5: Submit to hub
        logger.info("Step 5/6: Submitting transaction to hub...")
        submit_result = self.submit_transaction(sign_result["signed_txset"], timeout)
        if not submit_result.get("success"):
            return {"success": False, "error": f"Submit tx failed: {submit_result.get('error')}"}

        tx_hash = submit_result.get("tx_hash", "")
        logger.info(f"Transaction broadcast: {tx_hash}")

        # Step 6: Export key images and send to hub
        logger.info("Step 6/6: Syncing key images...")
        key_images_result = self.export_key_images_locally()
        if key_images_result.get("success"):
            self.import_key_images_to_hub(
                key_images_result["signed_key_images"],
                timeout=timeout
            )
        else:
            logger.warning(f"Key image export failed (non-critical): {key_images_result.get('error')}")

        return {
            "success": True,
            "tx_hash": tx_hash,
            "fee": fee,
            "amount": amount,
        }

    def get_stats(self) -> dict:
        """Get client statistics"""
        return {
            "identity": RNS.hexrep(self.identity.hash, delimit=False),
            "hub": RNS.hexrep(self.hub_hash, delimit=False),
            "operator_id": self.operator_id,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
        }


def main():
    """Run client CLI"""
    import argparse

    parser = argparse.ArgumentParser(description="LXMFMonero Client")
    parser.add_argument("--identity", "-i", default="~/.lxmfmonero/client/identity",
                        help="Path to identity file")
    parser.add_argument("--storage", "-s", default="~/.lxmfmonero/client/storage",
                        help="Path to LXMF storage directory")
    parser.add_argument("--hub", "-H", required=True,
                        help="Hub destination hash (32 hex chars)")
    parser.add_argument("--cold-wallet", "-c", default="http://127.0.0.1:18083/json_rpc",
                        help="Cold wallet-rpc URL")
    parser.add_argument("--operator", "-o", default="default",
                        help="Operator ID for hub")
    parser.add_argument("--timeout", "-t", type=int, default=300,
                        help="Request timeout in seconds")
    parser.add_argument("--debug", "-d", action="store_true",
                        help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Balance command
    subparsers.add_parser("balance", help="Get wallet balance")

    # Send command
    send_parser = subparsers.add_parser("send", help="Send XMR")
    send_parser.add_argument("destination", help="Destination address")
    send_parser.add_argument("amount", type=float, help="Amount in XMR")
    send_parser.add_argument("--priority", "-p", type=int, default=1,
                             help="Transaction priority (0-3)")

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

    # Create client
    client = MoneroClient(
        identity_path=str(identity_path),
        storage_path=str(storage_path),
        hub_hash=args.hub,
        cold_wallet_rpc=args.cold_wallet,
        operator_id=args.operator,
        default_timeout=args.timeout
    )

    # Execute command
    if args.command == "balance":
        print("Requesting balance...")
        result = client.get_balance()
        if result.get("success"):
            print(f"\nBalance:   {result['balance']:.12f} XMR")
            print(f"Unlocked:  {result['unlocked_balance']:.12f} XMR")
            print(f"Height:    {result['block_height']}")
        else:
            print(f"Error: {result.get('error')}")

    elif args.command == "send":
        print(f"Sending {args.amount} XMR to {args.destination}...")
        result = client.send_transaction(
            destination=args.destination,
            amount=args.amount,
            priority=args.priority
        )
        if result.get("success"):
            print(f"\nTransaction broadcast!")
            print(f"TX Hash: {result['tx_hash']}")
            print(f"Fee:     {result['fee']:.12f} XMR")
        else:
            print(f"Error: {result.get('error')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
