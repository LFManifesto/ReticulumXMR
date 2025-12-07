#!/usr/bin/env python3
"""
ReticulumXMR TUI Client
Terminal interface for Monero transactions over Reticulum
"""
import curses
import threading
import time
import sys
import logging
from typing import Optional
from pathlib import Path

from .client import ReticulumXMRClient
from .config import Config

# Suppress all logging in TUI mode
logging.getLogger().setLevel(logging.CRITICAL)
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)


class ReticulumXMRTUI:
    """Terminal UI for ReticulumXMR client"""

    def __init__(self, hub_destination: str, operator_id: str = "default",
                 local_wallet_rpc: str = "http://127.0.0.1:18083/json_rpc"):
        self.hub_destination = hub_destination
        self.operator_id = operator_id
        self.local_wallet_rpc = local_wallet_rpc

        # Initialize client in main thread (RNS needs main thread for signals)
        self.client = ReticulumXMRClient(
            hub_destination=self.hub_destination,
            operator_id=self.operator_id,
            local_wallet_rpc=self.local_wallet_rpc
        )
        self.connected = False
        self.connecting = False

        # State
        self.balance = None
        self.unlocked_balance = None
        self.block_height = None
        self.last_error = None
        self.last_tx_hash = None
        self.status_message = ""

        # Input state
        self.input_mode = None  # None, 'address', 'amount', 'confirm'
        self.send_address = ""
        self.send_amount = ""
        self.cursor_pos = 0

        # Screen
        self.stdscr = None
        self.running = False

    def connect(self):
        """Connect to hub in background"""
        self.connecting = True
        self.status_message = "Connecting to hub..."

        def do_connect():
            try:
                if self.client.connect(timeout=60):
                    self.connected = True
                    self.status_message = "Connected"
                    self.refresh_balance()
                else:
                    self.last_error = "Failed to connect to hub"
                    self.status_message = "Connection failed"
            except Exception as e:
                self.last_error = str(e)
                self.status_message = f"Error: {e}"
            finally:
                self.connecting = False

        thread = threading.Thread(target=do_connect, daemon=True)
        thread.start()

    def refresh_balance(self):
        """Refresh balance from hub"""
        if not self.connected or not self.client:
            return

        self.status_message = "Refreshing balance..."

        def do_refresh():
            try:
                result = self.client.get_balance(timeout=30)
                if "error" in result:
                    self.last_error = result["error"]
                    self.status_message = f"Error: {result['error']}"
                else:
                    self.balance = result.get("balance", 0)
                    self.unlocked_balance = result.get("unlocked_balance", 0)
                    self.block_height = result.get("block_height", 0)
                    self.status_message = f"Balance updated (block {self.block_height})"
            except Exception as e:
                self.last_error = str(e)
                self.status_message = f"Error: {e}"

        thread = threading.Thread(target=do_refresh, daemon=True)
        thread.start()

    def send_transaction(self):
        """Send XMR transaction"""
        if not self.connected or not self.client:
            self.last_error = "Not connected"
            return

        try:
            amount = float(self.send_amount)
        except ValueError:
            self.last_error = "Invalid amount"
            return

        address = self.send_address.strip()
        if len(address) < 95:
            self.last_error = "Invalid address"
            return

        self.status_message = f"Sending {amount} XMR..."
        self.input_mode = None

        def do_send():
            try:
                result = self.client.create_and_sign_transaction(
                    destination=address,
                    amount=amount,
                    priority=1,
                    timeout=180
                )
                if "error" in result:
                    self.last_error = result["error"]
                    self.status_message = f"TX Failed: {result['error']}"
                else:
                    self.last_tx_hash = result.get("tx_hash", "")
                    fee = result.get("fee", 0)
                    self.status_message = f"TX Sent! Fee: {fee:.12f} XMR"
                    self.refresh_balance()
            except Exception as e:
                self.last_error = str(e)
                self.status_message = f"Error: {e}"

        thread = threading.Thread(target=do_send, daemon=True)
        thread.start()

        # Clear input
        self.send_address = ""
        self.send_amount = ""

    def draw(self):
        """Draw the UI"""
        if not self.stdscr:
            return

        self.stdscr.clear()
        height, width = self.stdscr.getmaxyx()

        # Title bar
        title = " ReticulumXMR "
        self.stdscr.attron(curses.A_REVERSE)
        self.stdscr.addstr(0, 0, " " * width)
        self.stdscr.addstr(0, (width - len(title)) // 2, title)
        self.stdscr.attroff(curses.A_REVERSE)

        # Connection status
        y = 2
        if self.connecting:
            status = "CONNECTING..."
            self.stdscr.addstr(y, 2, f"Status: ", curses.A_BOLD)
            self.stdscr.addstr(status, curses.color_pair(3))
        elif self.connected:
            status = "CONNECTED"
            self.stdscr.addstr(y, 2, f"Status: ", curses.A_BOLD)
            self.stdscr.addstr(status, curses.color_pair(2))
        else:
            status = "DISCONNECTED"
            self.stdscr.addstr(y, 2, f"Status: ", curses.A_BOLD)
            self.stdscr.addstr(status, curses.color_pair(1))

        hub_display = self.hub_destination[:16] + "..."
        self.stdscr.addstr(y, 30, f"Hub: {hub_display}")

        # Balance section
        y = 4
        self.stdscr.addstr(y, 2, "=" * (width - 4))
        y += 1

        if self.balance is not None:
            self.stdscr.addstr(y, 2, "Balance:  ", curses.A_BOLD)
            self.stdscr.addstr(f"{self.balance:.12f} XMR", curses.color_pair(2) | curses.A_BOLD)
            y += 1
            self.stdscr.addstr(y, 2, "Unlocked: ", curses.A_BOLD)
            self.stdscr.addstr(f"{self.unlocked_balance:.12f} XMR")
            y += 1
            self.stdscr.addstr(y, 2, f"Block: {self.block_height}")
        else:
            self.stdscr.addstr(y, 2, "Balance: ", curses.A_BOLD)
            self.stdscr.addstr("--", curses.A_DIM)

        y += 2
        self.stdscr.addstr(y, 2, "=" * (width - 4))

        # Send section or input
        y += 2
        if self.input_mode == 'address':
            self.stdscr.addstr(y, 2, "Enter recipient address:", curses.A_BOLD)
            y += 1
            addr_display = self.send_address + "_"
            if len(addr_display) > width - 6:
                addr_display = "..." + addr_display[-(width - 9):]
            self.stdscr.addstr(y, 4, addr_display, curses.color_pair(3))
            y += 2
            self.stdscr.addstr(y, 2, "[Enter] Next  [Esc] Cancel", curses.A_DIM)

        elif self.input_mode == 'amount':
            self.stdscr.addstr(y, 2, "To: ", curses.A_BOLD)
            addr_short = self.send_address[:20] + "..." + self.send_address[-8:]
            self.stdscr.addstr(addr_short)
            y += 2
            self.stdscr.addstr(y, 2, "Enter amount (XMR):", curses.A_BOLD)
            y += 1
            self.stdscr.addstr(y, 4, self.send_amount + "_", curses.color_pair(3))
            y += 2
            self.stdscr.addstr(y, 2, "[Enter] Confirm  [Esc] Cancel", curses.A_DIM)

        elif self.input_mode == 'confirm':
            self.stdscr.addstr(y, 2, "CONFIRM TRANSACTION", curses.A_BOLD | curses.color_pair(3))
            y += 2
            self.stdscr.addstr(y, 2, "To: ")
            addr_short = self.send_address[:24] + "..." + self.send_address[-12:]
            self.stdscr.addstr(addr_short)
            y += 1
            self.stdscr.addstr(y, 2, "Amount: ", curses.A_BOLD)
            self.stdscr.addstr(f"{self.send_amount} XMR", curses.color_pair(2))
            y += 2
            self.stdscr.addstr(y, 2, "[Y] Send  [N] Cancel", curses.A_BOLD)

        else:
            # Normal menu
            self.stdscr.addstr(y, 2, "Commands:", curses.A_BOLD)
            y += 1
            self.stdscr.addstr(y, 4, "[R] Refresh balance")
            y += 1
            self.stdscr.addstr(y, 4, "[S] Send XMR")
            y += 1
            self.stdscr.addstr(y, 4, "[Q] Quit")

        # Last TX
        if self.last_tx_hash:
            y = height - 6
            self.stdscr.addstr(y, 2, "Last TX: ", curses.A_BOLD)
            tx_display = self.last_tx_hash[:32] + "..."
            self.stdscr.addstr(tx_display, curses.color_pair(2))

        # Status bar
        y = height - 3
        self.stdscr.addstr(y, 2, "-" * (width - 4))
        y += 1
        if self.status_message:
            msg = self.status_message[:width - 4]
            self.stdscr.addstr(y, 2, msg)

        # Error display
        if self.last_error:
            y = height - 2
            err = f"Error: {self.last_error}"[:width - 4]
            self.stdscr.addstr(y, 2, err, curses.color_pair(1))

        self.stdscr.refresh()

    def handle_input(self, key):
        """Handle keyboard input"""
        if self.input_mode == 'address':
            if key == 27:  # Escape
                self.input_mode = None
                self.send_address = ""
            elif key == 10 or key == 13:  # Enter
                if len(self.send_address) >= 95:
                    self.input_mode = 'amount'
                else:
                    self.last_error = "Address too short"
            elif key == curses.KEY_BACKSPACE or key == 127:
                self.send_address = self.send_address[:-1]
            elif 32 <= key <= 126:
                self.send_address += chr(key)

        elif self.input_mode == 'amount':
            if key == 27:  # Escape
                self.input_mode = None
                self.send_address = ""
                self.send_amount = ""
            elif key == 10 or key == 13:  # Enter
                try:
                    float(self.send_amount)
                    self.input_mode = 'confirm'
                except ValueError:
                    self.last_error = "Invalid amount"
            elif key == curses.KEY_BACKSPACE or key == 127:
                self.send_amount = self.send_amount[:-1]
            elif chr(key) in "0123456789.":
                self.send_amount += chr(key)

        elif self.input_mode == 'confirm':
            if key in (ord('y'), ord('Y')):
                self.send_transaction()
            elif key in (ord('n'), ord('N'), 27):
                self.input_mode = None
                self.send_address = ""
                self.send_amount = ""

        else:
            # Normal mode
            if key in (ord('q'), ord('Q')):
                self.running = False
            elif key in (ord('r'), ord('R')):
                self.last_error = None
                self.refresh_balance()
            elif key in (ord('s'), ord('S')):
                if self.connected:
                    self.last_error = None
                    self.input_mode = 'address'
                else:
                    self.last_error = "Not connected to hub"

    def run(self, stdscr):
        """Main TUI loop"""
        self.stdscr = stdscr
        self.running = True

        # Setup colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_RED, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)

        # Non-blocking input
        stdscr.nodelay(True)
        stdscr.timeout(100)

        # Hide cursor
        curses.curs_set(0)

        # Connect on startup
        self.connect()

        while self.running:
            try:
                self.draw()
                key = stdscr.getch()
                if key != -1:
                    self.handle_input(key)
            except curses.error:
                pass
            except KeyboardInterrupt:
                break

        # Cleanup
        if self.client:
            self.client.disconnect()


def main():
    """CLI entry point for TUI"""
    import argparse

    parser = argparse.ArgumentParser(
        description="ReticulumXMR TUI Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  reticulumxmr-tui 70200bc639ee7cc0f385d6d4ca1c4afd
  reticulumxmr-tui <hub-hash> -w http://127.0.0.1:18083/json_rpc
"""
    )
    parser.add_argument("hub", help="Hub destination hash")
    parser.add_argument("-o", "--operator", default="default",
                        help="Operator ID (default: default)")
    parser.add_argument("-w", "--wallet-rpc",
                        default="http://127.0.0.1:18083/json_rpc",
                        help="Local wallet-rpc URL for signing")

    args = parser.parse_args()

    tui = ReticulumXMRTUI(
        hub_destination=args.hub,
        operator_id=args.operator,
        local_wallet_rpc=args.wallet_rpc
    )

    try:
        curses.wrapper(tui.run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
