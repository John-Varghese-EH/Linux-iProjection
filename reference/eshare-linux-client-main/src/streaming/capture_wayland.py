"""
capture_wayland.py — xdg-desktop-portal ScreenCast helper
=========================================================

Requests a screen-capture PipeWire node from the Freedesktop
xdg-desktop-portal.  The returned node ID is passed to ``pipewiresrc``
in the GStreamer pipeline.

DBus interface: org.freedesktop.portal.ScreenCast
Portal spec: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html

Flow
----
1. Open a session         → session handle
2. SelectSources          → choose monitor / window / virtual
3. Start                  → triggers user permission dialog
4. OpenPipeWireRemote     → get a PipeWire fd
5. Connect via pw_context → enumerate streams → get node id

The final PipeWire node ID (an integer) is what GStreamer's pipewiresrc
``path`` property expects.

Requirements
------------
- xdg-desktop-portal ≥ 0.15 (GNOME/KDE ship this)
- PipeWire ≥ 0.3
- Python: ``dasbus`` (pip install dasbus)  or dbus-python

Usage
-----
    from src.streaming.capture_wayland import WaylandCapture

    async def main():
        cap = WaylandCapture()
        node_id = await cap.request_node()
        print("PipeWire node:", node_id)
        # Build pipeline: pipewiresrc path={node_id} ! ...
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import subprocess
from typing import Optional

log = logging.getLogger(__name__)

# ── OS detection ────────────────────────────────────────────────────────────
IS_WINDOWS: bool = (
    platform.system() == "Windows"
    or os.environ.get("LINUX_IPROJECTION_MOCK_PIPELINE", "") == "1"
)

if IS_WINDOWS:
    log.warning(
        "[WINDOWS MODE] xdg-desktop-portal / PipeWire unavailable. "
        "WaylandCapture will return a dummy node ID (-1) for mock pipeline use."
    )


class WaylandCaptureError(Exception):
    """Raised when the portal interaction fails."""


class WaylandCapture:
    """
    Acquires a PipeWire screencast node via xdg-desktop-portal.

    This is an ``asyncio``-based helper because the portal request
    involves user-visible permission dialogs and round-trips to DBus.

    Parameters
    ----------
    cursor_mode:
        0 = hidden, 1 = embedded, 2 = metadata.
    source_types:
        Bitmask: 1 = monitor, 2 = window, 4 = virtual.
        Default 1 (full monitor capture).
    persist:
        0 = don't persist, 1 = until revoked, 2 = until next boot.
    """

    PORTAL_BUS_NAME  = "org.freedesktop.portal.Desktop"
    PORTAL_OBJECT    = "/org/freedesktop/portal/desktop"
    SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"

    def __init__(
        self,
        cursor_mode:  int = 2,
        source_types: int = 1,
        persist:      int = 0,
    ) -> None:
        self._cursor_mode  = cursor_mode
        self._source_types = source_types
        self._persist      = persist
        self._node_id: Optional[int] = None

    # ── Public API ────────────────────────────────────────────────────────

    async def request_node(self) -> int:
        """
        Walk through the portal flow and return the PipeWire node ID.
        Raises WaylandCaptureError on failure.

        On Windows, returns -1 immediately (the mock pipeline ignores node IDs).
        """
        if IS_WINDOWS:
            log.warning(
                "[WINDOWS MODE] Skipping xdg-desktop-portal — returning dummy node ID -1. "
                "The pipeline will use videotestsrc instead."
            )
            self._node_id = -1
            return -1

        try:
            from dasbus.connection import SessionMessageBus  # type: ignore
        except ImportError as exc:
            raise WaylandCaptureError(
                "dasbus is required for Wayland capture.  "
                "Run: pip install dasbus"
            ) from exc

        log.info("Requesting ScreenCast portal …")
        bus = SessionMessageBus()
        portal = bus.get_proxy(self.PORTAL_BUS_NAME, self.PORTAL_OBJECT)

        try:
            # ── Step 1: CreateSession ──────────────────────────────────────
            session_handle = await self._create_session(portal, bus)
            log.debug("Session handle: %s", session_handle)

            # ── Step 2: SelectSources ──────────────────────────────────────
            await self._select_sources(portal, bus, session_handle)

            # ── Step 3: Start ──────────────────────────────────────────────
            streams = await self._start(portal, bus, session_handle)
            if not streams:
                raise WaylandCaptureError("Portal returned no streams.")

            # ── Step 4: Extract node ID ────────────────────────────────────
            node_id = streams[0][0]   # first stream, node_id field
            self._node_id = int(node_id)
            log.info("PipeWire node ID: %d", self._node_id)
            return self._node_id

        except WaylandCaptureError:
            raise
        except Exception as exc:
            raise WaylandCaptureError(f"Portal interaction failed: {exc}") from exc

    @property
    def node_id(self) -> Optional[int]:
        """The acquired node ID, or None if not yet requested."""
        return self._node_id

    # ── Internal portal steps ─────────────────────────────────────────────

    async def _create_session(self, portal, bus) -> str:
        """
        Call org.freedesktop.portal.ScreenCast.CreateSession.
        Returns the session object path.
        """
        token = f"lp_session_{os.getpid()}"
        opts  = {
            "session_handle_token": ("s", token),
            "handle_token":         ("s", f"lp_req_{os.getpid()}_1"),
        }
        result = await self._call_with_response(portal, bus, "CreateSession", opts)
        session_handle = result.get("session_handle", "")
        if not session_handle:
            raise WaylandCaptureError("CreateSession did not return session_handle.")
        return session_handle

    async def _select_sources(self, portal, bus, session_handle: str) -> None:
        """Call SelectSources with monitor type and cursor mode."""
        opts = {
            "handle_token": ("s", f"lp_req_{os.getpid()}_2"),
            "types":        ("u", self._source_types),
            "cursor_mode":  ("u", self._cursor_mode),
            "persist_mode": ("u", self._persist),
        }
        await self._call_with_response(portal, bus, "SelectSources",
                                        opts, session_handle)

    async def _start(self, portal, bus, session_handle: str) -> list:
        """Call Start and return the streams list."""
        opts = {
            "handle_token": ("s", f"lp_req_{os.getpid()}_3"),
        }
        result = await self._call_with_response(portal, bus, "Start",
                                                opts, session_handle)
        return result.get("streams", [])

    async def _call_with_response(self, portal, bus, method: str,
                                   opts: dict, session_handle: str = "") -> dict:
        """
        Generic portal request helper.
        Portal methods return a request handle; we subscribe to its Response
        signal to get the actual result.

        NOTE: This is a simplified skeleton.  Full implementation requires
        listening to org.freedesktop.portal.Request.Response using the
        GLib main loop or an asyncio-DBus bridge.  This will be fleshed out
        in Phase 5 when the GTK4 main loop is available.
        """
        log.debug("Portal call: %s %r", method, opts)
        # TODO: implement full async signal-based portal request in Phase 5
        raise NotImplementedError(
            f"Portal method {method!r} not yet wired up.  "
            "This stub will be completed in Phase 5 (GTK4 main loop)."
        )


# ── CLI helper: use pw-cli to find existing PipeWire nodes ─────────────────

def list_pipewire_nodes() -> list[dict]:
    """
    Use ``pw-cli list-objects`` to enumerate PipeWire nodes.
    Returns a list of dicts with 'id', 'name', 'media_class' keys.
    This can be used to pick a node without going through the portal.

    On Windows, always returns an empty list.
    """
    if IS_WINDOWS:
        log.info("[WINDOWS MODE] pw-cli not available on Windows — returning empty node list.")
        return []
    try:
        out = subprocess.check_output(
            ["pw-cli", "list-objects"], stderr=subprocess.DEVNULL, text=True
        )
    except FileNotFoundError:
        log.warning("pw-cli not found — PipeWire may not be installed.")
        return []
    except subprocess.CalledProcessError as exc:
        log.warning("pw-cli error: %s", exc)
        return []

    nodes: list[dict] = []
    current: dict = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("id "):
            if current:
                nodes.append(current)
            current = {"id": line.split()[1].rstrip(",")}
        elif "node.name" in line:
            current["name"] = line.split("=", 1)[-1].strip().strip('"')
        elif "media.class" in line:
            current["media_class"] = line.split("=", 1)[-1].strip().strip('"')
    if current:
        nodes.append(current)
    return nodes


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    print("PipeWire nodes on this system:\n")
    for node in list_pipewire_nodes():
        print(f"  id={node.get('id')}  class={node.get('media_class','?'):<35}  {node.get('name','')}")
