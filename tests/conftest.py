# linux-iprojection - Built by John Varghese (J0X) | https://github.com/John-Varghese-EH
"""Shared test fixtures for linux-iprojection test suite."""

import asyncio

import pytest


class FakeEscVpServer:
    """A fake ESC/VP.net TCP server for unit testing.

    Implements the handshake and basic command responses without needing
    real projector hardware.
    """

    HANDSHAKE = b"ESC/VP.net\x10\x03\x00\x00\x00\x00"

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port  # 0 = let OS pick a free port
        self._server = None
        self.actual_port: int = 0

        # Configurable responses for testing
        self.power_state = "01"
        self.source_state = "30"
        self.lamp_hours = 1234
        self.mute_state = "OFF"
        self.serial = "TEST123456"
        self.error_state = "00"

        # Test control
        self.reject_handshake = False
        self.bad_handshake_reply = None
        self.hang_on_command = False
        self.connection_count = 0

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.connection_count += 1
        try:
            # Handshake
            data = await asyncio.wait_for(reader.readexactly(16), timeout=5.0)
            if self.reject_handshake:
                writer.close()
                return
            if self.bad_handshake_reply is not None:
                writer.write(self.bad_handshake_reply)
            else:
                writer.write(self.HANDSHAKE)
            await writer.drain()

            # Send prompt
            writer.write(b":")
            await writer.drain()

            # Command loop
            while True:
                try:
                    data = await asyncio.wait_for(reader.readuntil(b"\r"), timeout=10.0)
                except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError):
                    break

                cmd = data.decode("ascii", errors="replace").strip()

                if self.hang_on_command:
                    # Simulate timeout - never respond
                    await asyncio.sleep(60)
                    break

                response = self._process_command(cmd)
                writer.write(response.encode("ascii") + b"\r\n:")
                await writer.drain()

        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

    def _process_command(self, cmd: str) -> str:
        if cmd == "PWR?":
            return f"PWR={self.power_state}"
        elif cmd == "PWR ON":
            self.power_state = "01"
            return "PWR=01"
        elif cmd == "PWR OFF":
            self.power_state = "00"
            return "PWR=00"
        elif cmd == "SOURCE?":
            return f"SOURCE={self.source_state}"
        elif cmd.startswith("SOURCE "):
            self.source_state = cmd.split(" ", 1)[1]
            return f"SOURCE={self.source_state}"
        elif cmd == "LAMP?":
            return f"LAMP={self.lamp_hours} 01"
        elif cmd == "MUTE?":
            return f"MUTE={self.mute_state}"
        elif cmd.startswith("MUTE "):
            self.mute_state = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "SNO?":
            return f"SNO={self.serial}"
        elif cmd == "ERR?":
            return f"ERR={self.error_state}"
        # New Enterprise Commands
        elif cmd == "BRIGHT?":
            return f"BRIGHT={getattr(self, 'brightness', 128)}"
        elif cmd.startswith("BRIGHT "):
            self.brightness = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "CONTRAST?":
            return f"CONTRAST={getattr(self, 'contrast', 128)}"
        elif cmd.startswith("CONTRAST "):
            self.contrast = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "SHARPNESS?":
            return f"SHARPNESS={getattr(self, 'sharpness', 128)}"
        elif cmd.startswith("SHARPNESS "):
            self.sharpness = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "CTEMP?":
            return f"CTEMP={getattr(self, 'ctemp', 7)}"
        elif cmd.startswith("CTEMP "):
            self.ctemp = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "HKEYSTONE?":
            return f"HKEYSTONE={getattr(self, 'hkeystone', 0)}"
        elif cmd.startswith("HKEYSTONE "):
            self.hkeystone = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "VKEYSTONE?":
            return f"VKEYSTONE={getattr(self, 'vkeystone', 0)}"
        elif cmd.startswith("VKEYSTONE "):
            self.vkeystone = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "FILTER?":
            return f"FILTER={getattr(self, 'filter_hours', 500)}"
        elif cmd == "SIGNAL?":
            return f"SIGNAL={getattr(self, 'signal', '00')}"
        elif cmd == "RESOLUTION?":
            return f"RESOLUTION={getattr(self, 'resolution', '1920x1080')}"
        elif cmd == "BADCMD":
            return "ERR=01"
        elif cmd == "":
            # Keepalive empty command
            return ""
        else:
            return "ERR=01"

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
        )
        # Get the actual port assigned
        addr = self._server.sockets[0].getsockname()
        self.actual_port = addr[1]
        return self

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


@pytest.fixture
async def fake_server():
    """Provide a running fake ESC/VP.net server on a random port."""
    server = FakeEscVpServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def bad_handshake_server():
    """Server that sends wrong handshake bytes."""
    server = FakeEscVpServer()
    server.bad_handshake_reply = b"WRONG_HANDSHAKE!"
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def hanging_server():
    """Server that never responds to commands (for timeout testing)."""
    server = FakeEscVpServer()
    server.hang_on_command = True
    await server.start()
    yield server
    await server.stop()
