"""
LXMFMonero TUI - Terminal User Interface for LXMFMonero Client

A curses-based interface for managing Monero transactions over LXMF/Reticulum.
"""

import curses
import threading
import time
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum

from .client import MoneroClient

# Suppress logging to console when TUI is active
logging.getLogger("lxmfmonero").setLevel(logging.WARNING)


class Screen(Enum):
    MAIN = "main"
    SEND = "send"
    HISTORY = "history"
    SETTINGS = "settings"
    CONFIRM = "confirm"


@dataclass
class TUIState:
    """Current state of the TUI"""
    screen: Screen = Screen.MAIN
    balance: float = 0.0
    unlocked_balance: float = 0.0
    block_height: int = 0
    hub_connected: bool = False
    last_refresh: float = 0.0
    status_message: str = ""
    status_is_error: bool = False

    # Send form
    send_address: str = ""
    send_amount: str = ""
    send_priority: int = 1
    send_cursor_field: int = 0  # 0=address, 1=amount, 2=priority

    # Transaction result
    last_tx_hash: str = ""
    last_tx_fee: float = 0.0

    # Pending operation
    pending_operation: Optional[str] = None
    pending_progress: str = ""


class LXMFMoneroTUI:
    """Terminal User Interface for LXMFMonero"""

    def __init__(self, client: MoneroClient):
        self.client = client
        self.state = TUIState()
        self.running = False
        self.refresh_thread: Optional[threading.Thread] = None

    def run(self, stdscr):
        """Main TUI loop"""
        self.stdscr = stdscr
        self.running = True

        # Setup curses
        curses.curs_set(0)  # Hide cursor
        curses.start_color()
        curses.use_default_colors()

        # Define color pairs
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Success/balance
        curses.init_pair(2, curses.COLOR_RED, -1)     # Error
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Warning/pending
        curses.init_pair(4, curses.COLOR_CYAN, -1)    # Headers
        curses.init_pair(5, curses.COLOR_MAGENTA, -1) # Highlight

        # Start background refresh
        self.refresh_thread = threading.Thread(target=self._background_refresh, daemon=True)
        self.refresh_thread.start()

        # Initial balance fetch
        self._refresh_balance()

        # Main loop
        while self.running:
            self._draw()
            self._handle_input()

    def _draw(self):
        """Draw the current screen"""
        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()

        # Draw header
        self._draw_header(width)

        # Draw main content based on screen
        if self.state.screen == Screen.MAIN:
            self._draw_main_screen(height, width)
        elif self.state.screen == Screen.SEND:
            self._draw_send_screen(height, width)
        elif self.state.screen == Screen.CONFIRM:
            self._draw_confirm_screen(height, width)

        # Draw status bar
        self._draw_status_bar(height, width)

        self.stdscr.refresh()

    def _draw_header(self, width: int):
        """Draw the header bar"""
        title = " LXMFMonero "
        hub_status = "Connected" if self.state.hub_connected else "Disconnected"
        hub_color = curses.color_pair(1) if self.state.hub_connected else curses.color_pair(2)

        # Title
        self.stdscr.attron(curses.A_BOLD | curses.color_pair(4))
        self.stdscr.addstr(0, 0, "=" * width)
        self.stdscr.addstr(0, (width - len(title)) // 2, title)
        self.stdscr.attroff(curses.A_BOLD | curses.color_pair(4))

        # Hub status on right
        status_text = f" Hub: {hub_status} "
        self.stdscr.attron(hub_color)
        self.stdscr.addstr(0, width - len(status_text) - 1, status_text)
        self.stdscr.attroff(hub_color)

    def _draw_main_screen(self, height: int, width: int):
        """Draw the main balance screen"""
        y = 2

        # Balance section
        self.stdscr.attron(curses.A_BOLD)
        self.stdscr.addstr(y, 2, "WALLET BALANCE")
        self.stdscr.attroff(curses.A_BOLD)
        y += 2

        # Balance display
        balance_str = f"{self.state.balance:.12f} XMR"
        self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
        self.stdscr.addstr(y, 4, balance_str)
        self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
        y += 1

        # Unlocked balance
        if self.state.unlocked_balance != self.state.balance:
            unlocked_str = f"Unlocked: {self.state.unlocked_balance:.12f} XMR"
            self.stdscr.attron(curses.color_pair(3))
            self.stdscr.addstr(y, 4, unlocked_str)
            self.stdscr.attroff(curses.color_pair(3))
            y += 1

        y += 1

        # Block height
        self.stdscr.addstr(y, 4, f"Block Height: {self.state.block_height}")
        y += 1

        # Last refresh
        if self.state.last_refresh > 0:
            elapsed = int(time.time() - self.state.last_refresh)
            self.stdscr.addstr(y, 4, f"Last Updated: {elapsed}s ago")
        y += 2

        # Last transaction
        if self.state.last_tx_hash:
            self.stdscr.attron(curses.A_BOLD)
            self.stdscr.addstr(y, 2, "LAST TRANSACTION")
            self.stdscr.attroff(curses.A_BOLD)
            y += 1
            self.stdscr.attron(curses.color_pair(1))
            self.stdscr.addstr(y, 4, f"TX: {self.state.last_tx_hash[:32]}...")
            self.stdscr.attroff(curses.color_pair(1))
            y += 1
            self.stdscr.addstr(y, 4, f"Fee: {self.state.last_tx_fee:.12f} XMR")
            y += 2

        # Menu
        y = max(y, height - 10)
        self.stdscr.attron(curses.A_BOLD)
        self.stdscr.addstr(y, 2, "COMMANDS")
        self.stdscr.attroff(curses.A_BOLD)
        y += 2

        commands = [
            ("S", "Send XMR"),
            ("R", "Refresh Balance"),
            ("Q", "Quit"),
        ]

        for key, desc in commands:
            self.stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
            self.stdscr.addstr(y, 4, f"[{key}]")
            self.stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
            self.stdscr.addstr(y, 8, f" {desc}")
            y += 1

    def _draw_send_screen(self, height: int, width: int):
        """Draw the send transaction form"""
        y = 2

        self.stdscr.attron(curses.A_BOLD)
        self.stdscr.addstr(y, 2, "SEND XMR")
        self.stdscr.attroff(curses.A_BOLD)
        y += 2

        # Available balance
        self.stdscr.addstr(y, 4, f"Available: {self.state.unlocked_balance:.12f} XMR")
        y += 2

        # Address field
        label = "Address: "
        if self.state.send_cursor_field == 0:
            self.stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
            self.stdscr.addstr(y, 4, "> ")
            self.stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
        else:
            self.stdscr.addstr(y, 4, "  ")
        self.stdscr.addstr(y, 6, label)

        # Show address (truncated if needed)
        addr_display = self.state.send_address or "(enter address)"
        if len(addr_display) > width - 20:
            addr_display = addr_display[:width-23] + "..."
        if self.state.send_cursor_field == 0:
            self.stdscr.attron(curses.A_UNDERLINE)
        self.stdscr.addstr(y, 6 + len(label), addr_display)
        if self.state.send_cursor_field == 0:
            self.stdscr.attroff(curses.A_UNDERLINE)
        y += 2

        # Amount field
        if self.state.send_cursor_field == 1:
            self.stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
            self.stdscr.addstr(y, 4, "> ")
            self.stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
        else:
            self.stdscr.addstr(y, 4, "  ")
        self.stdscr.addstr(y, 6, "Amount:  ")

        amount_display = self.state.send_amount or "0.0"
        if self.state.send_cursor_field == 1:
            self.stdscr.attron(curses.A_UNDERLINE)
        self.stdscr.addstr(y, 15, f"{amount_display} XMR")
        if self.state.send_cursor_field == 1:
            self.stdscr.attroff(curses.A_UNDERLINE)
        y += 2

        # Priority field
        if self.state.send_cursor_field == 2:
            self.stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
            self.stdscr.addstr(y, 4, "> ")
            self.stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)
        else:
            self.stdscr.addstr(y, 4, "  ")
        priority_names = ["Unimportant", "Normal", "Elevated", "Priority"]
        self.stdscr.addstr(y, 6, f"Priority: {priority_names[self.state.send_priority]} ({self.state.send_priority})")
        y += 3

        # Instructions
        self.stdscr.attron(curses.A_DIM)
        self.stdscr.addstr(y, 4, "UP/DOWN: Select field | LEFT/RIGHT: Change priority")
        y += 1
        self.stdscr.addstr(y, 4, "ENTER: Confirm | ESC: Cancel")
        self.stdscr.attroff(curses.A_DIM)

    def _draw_confirm_screen(self, height: int, width: int):
        """Draw transaction confirmation screen"""
        y = 2

        self.stdscr.attron(curses.A_BOLD | curses.color_pair(3))
        self.stdscr.addstr(y, 2, "CONFIRM TRANSACTION")
        self.stdscr.attroff(curses.A_BOLD | curses.color_pair(3))
        y += 2

        # Show pending operation if any
        if self.state.pending_operation:
            self.stdscr.attron(curses.color_pair(3))
            self.stdscr.addstr(y, 4, f">> {self.state.pending_operation}")
            self.stdscr.attroff(curses.color_pair(3))
            y += 1
            if self.state.pending_progress:
                self.stdscr.addstr(y, 4, f"   {self.state.pending_progress}")
            y += 2
        else:
            # Transaction details
            self.stdscr.addstr(y, 4, "Destination:")
            y += 1
            addr = self.state.send_address
            # Word wrap long address
            while addr:
                chunk = addr[:width-8]
                addr = addr[width-8:]
                self.stdscr.addstr(y, 6, chunk)
                y += 1
            y += 1

            try:
                amount = float(self.state.send_amount)
            except:
                amount = 0.0
            self.stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
            self.stdscr.addstr(y, 4, f"Amount: {amount:.12f} XMR")
            self.stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
            y += 2

            priority_names = ["Unimportant", "Normal", "Elevated", "Priority"]
            self.stdscr.addstr(y, 4, f"Priority: {priority_names[self.state.send_priority]}")
            y += 3

            # Confirmation prompt
            self.stdscr.attron(curses.A_BOLD)
            self.stdscr.addstr(y, 4, "Press Y to confirm, N to cancel")
            self.stdscr.attroff(curses.A_BOLD)

    def _draw_status_bar(self, height: int, width: int):
        """Draw the status bar at bottom"""
        y = height - 1

        # Clear the line
        self.stdscr.addstr(y, 0, " " * (width - 1))

        if self.state.status_message:
            color = curses.color_pair(2) if self.state.status_is_error else curses.color_pair(1)
            self.stdscr.attron(color)
            msg = self.state.status_message[:width-2]
            self.stdscr.addstr(y, 1, msg)
            self.stdscr.attroff(color)
        else:
            # Show hub info
            hub_short = self.client.hub_hash.hex()[:16]
            self.stdscr.attron(curses.A_DIM)
            self.stdscr.addstr(y, 1, f"Hub: {hub_short}...")
            self.stdscr.attroff(curses.A_DIM)

    def _handle_input(self):
        """Handle keyboard input"""
        self.stdscr.timeout(100)  # 100ms timeout for getch

        try:
            key = self.stdscr.getch()
        except:
            return

        if key == -1:
            return

        # Global keys
        if key == ord('q') or key == ord('Q'):
            if self.state.screen == Screen.MAIN:
                self.running = False
            else:
                self.state.screen = Screen.MAIN
            return

        if key == 27:  # ESC
            self.state.screen = Screen.MAIN
            self._clear_send_form()
            return

        # Screen-specific handling
        if self.state.screen == Screen.MAIN:
            self._handle_main_input(key)
        elif self.state.screen == Screen.SEND:
            self._handle_send_input(key)
        elif self.state.screen == Screen.CONFIRM:
            self._handle_confirm_input(key)

    def _handle_main_input(self, key: int):
        """Handle input on main screen"""
        if key == ord('s') or key == ord('S'):
            self.state.screen = Screen.SEND
            self._clear_send_form()
        elif key == ord('r') or key == ord('R'):
            self._refresh_balance()

    def _handle_send_input(self, key: int):
        """Handle input on send screen"""
        if key == curses.KEY_UP:
            self.state.send_cursor_field = max(0, self.state.send_cursor_field - 1)
        elif key == curses.KEY_DOWN:
            self.state.send_cursor_field = min(2, self.state.send_cursor_field + 1)
        elif key == curses.KEY_LEFT:
            if self.state.send_cursor_field == 2:
                self.state.send_priority = max(0, self.state.send_priority - 1)
        elif key == curses.KEY_RIGHT:
            if self.state.send_cursor_field == 2:
                self.state.send_priority = min(3, self.state.send_priority + 1)
        elif key == 10 or key == curses.KEY_ENTER:  # Enter
            self._validate_and_confirm()
        elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:
            self._handle_backspace()
        elif 32 <= key <= 126:  # Printable character
            self._handle_char(chr(key))

    def _handle_confirm_input(self, key: int):
        """Handle input on confirm screen"""
        if self.state.pending_operation:
            return  # Can't cancel during operation

        if key == ord('y') or key == ord('Y'):
            self._execute_transaction()
        elif key == ord('n') or key == ord('N'):
            self.state.screen = Screen.SEND

    def _handle_backspace(self):
        """Handle backspace in send form"""
        if self.state.send_cursor_field == 0:
            self.state.send_address = self.state.send_address[:-1]
        elif self.state.send_cursor_field == 1:
            self.state.send_amount = self.state.send_amount[:-1]

    def _handle_char(self, char: str):
        """Handle character input in send form"""
        if self.state.send_cursor_field == 0:
            # Address field - alphanumeric only
            if char.isalnum():
                self.state.send_address += char
        elif self.state.send_cursor_field == 1:
            # Amount field - numbers and decimal only
            if char.isdigit() or (char == '.' and '.' not in self.state.send_amount):
                self.state.send_amount += char

    def _validate_and_confirm(self):
        """Validate send form and show confirmation"""
        # Validate address
        if len(self.state.send_address) < 95:
            self._set_status("Invalid address (too short)", error=True)
            return

        # Validate amount
        try:
            amount = float(self.state.send_amount)
            if amount <= 0:
                raise ValueError()
        except:
            self._set_status("Invalid amount", error=True)
            return

        if amount > self.state.unlocked_balance:
            self._set_status("Insufficient balance", error=True)
            return

        self.state.screen = Screen.CONFIRM

    def _execute_transaction(self):
        """Execute the transaction in background"""
        def tx_thread():
            try:
                amount = float(self.state.send_amount)

                # Step 1: Export outputs
                self.state.pending_operation = "Exporting outputs from hub..."
                self.state.pending_progress = ""
                result = self.client.export_outputs(all_outputs=True)
                if not result.get("success"):
                    raise Exception(f"Export failed: {result.get('error')}")

                # Step 2: Import outputs
                self.state.pending_operation = "Importing outputs to cold wallet..."
                result = self.client.import_outputs_locally(result["outputs_data_hex"])
                if not result.get("success"):
                    raise Exception(f"Import failed: {result.get('error')}")

                # Step 3: Create transaction
                self.state.pending_operation = "Creating unsigned transaction..."
                result = self.client.create_transaction(
                    self.state.send_address, amount, self.state.send_priority
                )
                if not result.get("success"):
                    raise Exception(f"Create tx failed: {result.get('error')}")
                fee = result.get("fee", 0)
                self.state.pending_progress = f"Fee: {fee:.8f} XMR"

                # Step 4: Sign
                self.state.pending_operation = "Signing transaction locally..."
                sign_result = self.client.sign_transaction_locally(result["unsigned_txset"])
                if not sign_result.get("success"):
                    raise Exception(f"Sign failed: {sign_result.get('error')}")

                # Step 5: Submit
                self.state.pending_operation = "Submitting to hub..."
                submit_result = self.client.submit_transaction(sign_result["signed_txset"])
                if not submit_result.get("success"):
                    raise Exception(f"Submit failed: {submit_result.get('error')}")

                tx_hash = submit_result.get("tx_hash", "")

                # Step 6: Key images
                self.state.pending_operation = "Syncing key images..."
                key_result = self.client.export_key_images_locally()
                if key_result.get("success"):
                    self.client.import_key_images_to_hub(key_result["signed_key_images"])

                # Success
                self.state.last_tx_hash = tx_hash
                self.state.last_tx_fee = fee
                self._set_status(f"Transaction sent! TX: {tx_hash[:16]}...", error=False)
                self._refresh_balance()

            except Exception as e:
                self._set_status(str(e), error=True)
            finally:
                self.state.pending_operation = None
                self.state.pending_progress = ""
                self.state.screen = Screen.MAIN
                self._clear_send_form()

        thread = threading.Thread(target=tx_thread, daemon=True)
        thread.start()

    def _refresh_balance(self):
        """Refresh balance from hub"""
        def refresh_thread():
            self._set_status("Refreshing balance...", error=False)
            result = self.client.get_balance()
            if result.get("success"):
                self.state.balance = result["balance"]
                self.state.unlocked_balance = result["unlocked_balance"]
                self.state.block_height = result["block_height"]
                self.state.hub_connected = True
                self.state.last_refresh = time.time()
                self._set_status("Balance updated", error=False)
            else:
                self.state.hub_connected = False
                self._set_status(f"Refresh failed: {result.get('error')}", error=True)

        thread = threading.Thread(target=refresh_thread, daemon=True)
        thread.start()

    def _background_refresh(self):
        """Background thread to periodically refresh"""
        while self.running:
            time.sleep(60)  # Refresh every 60 seconds
            if self.state.screen == Screen.MAIN and not self.state.pending_operation:
                self._refresh_balance()

    def _clear_send_form(self):
        """Clear the send form"""
        self.state.send_address = ""
        self.state.send_amount = ""
        self.state.send_priority = 1
        self.state.send_cursor_field = 0

    def _set_status(self, message: str, error: bool = False):
        """Set status bar message"""
        self.state.status_message = message
        self.state.status_is_error = error

        # Clear status after 5 seconds
        def clear_status():
            time.sleep(5)
            if self.state.status_message == message:
                self.state.status_message = ""

        thread = threading.Thread(target=clear_status, daemon=True)
        thread.start()


def main():
    """Run TUI from command line"""
    import argparse

    parser = argparse.ArgumentParser(description="LXMFMonero TUI")
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
    args = parser.parse_args()

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

    # Create and run TUI
    tui = LXMFMoneroTUI(client)

    try:
        curses.wrapper(tui.run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
