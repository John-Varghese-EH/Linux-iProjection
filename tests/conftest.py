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
            return f"CTEMP={getattr(self, 'ctemp', '00')}"
        elif cmd.startswith("CTEMP "):
            self.ctemp = cmd.split(" ", 1)[1]
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
        elif cmd == "PNAME?":
            return f"PNAME={getattr(self, 'projector_name', 'EPSON Projector')}"
        elif cmd == "VOL?":
            return f"VOL={getattr(self, 'volume', 10)}"
        elif cmd.startswith("VOL "):
            self.volume = int(cmd.split(" ", 1)[1])
            return ""
        elif cmd == "FREEZE?":
            return f"FREEZE={getattr(self, 'freeze', 'OFF')}"
        elif cmd.startswith("FREEZE "):
            self.freeze = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "CMODE?":
            return f"CMODE={getattr(self, 'cmode', '06')}"
        elif cmd.startswith("CMODE "):
            self.cmode = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "ASPECT?":
            return f"ASPECT={getattr(self, 'aspect', '30')}"
        elif cmd.startswith("ASPECT "):
            self.aspect = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "LUMINANCE?":
            return f"LUMINANCE={getattr(self, 'luminance', '00')}"
        elif cmd.startswith("LUMINANCE "):
            self.luminance = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "TINT?":
            return f"TINT={getattr(self, 'tint', 128)}"
        elif cmd == "HREVERSE?":
            return f"HREVERSE={getattr(self, 'hreverse', 'OFF')}"
        elif cmd == "VREVERSE?":
            return f"VREVERSE={getattr(self, 'vreverse', 'OFF')}"
        elif cmd == "BADCMD":
            return "ERR=01"
        elif cmd == "":
            # Keepalive empty command
            return ""
        # Enterprise commands (MODERATOR, WBSHARE, FCN, ENCRYPT)
        elif cmd.startswith("MODERATOR "):
            self.moderator = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "MODERATOR?":
            return f"MODERATOR={getattr(self, 'moderator', 'OFF')}"
        elif cmd.startswith("WBSHARE "):
            self.wbshare = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "WBSHARE?":
            return f"WBSHARE={getattr(self, 'wbshare', 'OFF')}"
        elif cmd.startswith("FCN "):
            self.fcn = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "FCN?":
            return f"FCN={getattr(self, 'fcn', 'OFF')}"
        elif cmd.startswith("ENCRYPT "):
            self.encrypt = cmd.split(" ", 1)[1]
            return ""
        elif cmd == "ENCRYPT?":
            return f"ENCRYPT={getattr(self, 'encrypt', 'OFF')}"
        elif cmd.startswith("AUTOSOURCE "):
            return ""
        elif cmd.startswith("KEY "):
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


class FakePJLinkServer:
    """A fake PJLink TCP server for unit testing.

    Implements the PJLink greeting and basic command responses.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0, password: str = ""):
        self.host = host
        self.port = port
        self.password = password
        self._server = None
        self.actual_port: int = 0

        self.power_state = "1"
        self.input_code = "31"
        self.lamp_hours = 5000
        self.name = "EPSON EB-TEST"
        self.manufacturer = "EPSON"
        self.model = "EB-TEST"

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Send greeting
            if self.password:
                import hashlib
                salt = "abcd1234"
                writer.write(f"%1PJLINK 1 {salt}\r".encode())
            else:
                writer.write(b"%1PJLINK 0\r")
            await writer.drain()

            if self.password:
                # Read and validate auth hash
                auth_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                # For testing, just accept any auth

            # Command loop
            while True:
                try:
                    data = await asyncio.wait_for(reader.readline(), timeout=10.0)
                except (asyncio.IncompleteReadError, asyncio.TimeoutError):
                    break

                cmd = data.decode("ascii", errors="replace").strip()
                # Strip auth hash prefix if present
                if cmd.startswith("%"):
                    pass
                else:
                    # Auth hash prefix before %
                    pct_idx = cmd.find("%")
                    if pct_idx > 0:
                        cmd = cmd[pct_idx:]

                response = self._process_pjlink(cmd)
                writer.write(response.encode("ascii") + b"\r")
                await writer.drain()

        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except OSError:
                pass

    def _process_pjlink(self, cmd: str) -> str:
        # cmd looks like "%1POWR ?"
        if "POWR ?" in cmd:
            return f"%1POWR={self.power_state}"
        elif "POWR 1" in cmd:
            self.power_state = "1"
            return "%1POWR=OK"
        elif "POWR 0" in cmd:
            self.power_state = "0"
            return "%1POWR=OK"
        elif "INPT ?" in cmd:
            return f"%1INPT={self.input_code}"
        elif "LAMP ?" in cmd:
            return f"%1LAMP={self.lamp_hours} 1"
        elif "ERST ?" in cmd:
            return "%1ERST=000000"
        elif "NAME ?" in cmd:
            return f"%1NAME={self.name}"
        elif "INF1 ?" in cmd:
            return f"%1INF1={self.manufacturer}"
        elif "INF2 ?" in cmd:
            return f"%1INF2={self.model}"
        elif "CLSS ?" in cmd:
            return "%1CLSS=2"
        elif "SNUM ?" in cmd:
            return "%1SNUM=TEST456"
        elif "IRES ?" in cmd:
            return "%1IRES=1920x1080"
        elif "FILT ?" in cmd:
            return "%1FILT=300"
        elif "INST ?" in cmd:
            return "%1INST=11 31 32 51"
        elif "FREZ ?" in cmd:
            return "%1FREZ=0"
        elif "SVER ?" in cmd:
            return "%1SVER=1.05"
        elif "RRES ?" in cmd:
            return "%1RRES=1920x1080"
        else:
            return "%1XXXX=ERR3"

    async def start(self):
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        addr = self._server.sockets[0].getsockname()
        self.actual_port = addr[1]
        return self

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


@pytest.fixture
async def fake_pjlink_server():
    """Provide a running fake PJLink server on a random port."""
    server = FakePJLinkServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def fake_pjlink_server_with_password():
    """Provide a running fake PJLink server that requires a password."""
    server = FakePJLinkServer(password="testpass")
    await server.start()
    yield server
    await server.stop()
