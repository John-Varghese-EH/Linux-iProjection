"""
linux-iprojection D-Bus session service.
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH

Exposes projector control methods over D-Bus at dev.linux_iprojection.Manager,
allowing shell scripts, desktop extensions, and other applications to control
projectors without launching the GUI.
"""

import asyncio
import logging

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gio, GLib

from .client import ProjectorClient
from .discovery import discover_all
from .config import MacroStore, MacroStep

logger = logging.getLogger(__name__)

INTROSPECTION_XML = """
<node>
  <interface name="dev.linux_iprojection.Manager">
    <method name="Discover">
      <arg direction="out" type="a{ss}" name="devices"/>
    </method>
    <method name="PowerOn">
      <arg direction="in" type="s" name="ip"/>
    </method>
    <method name="PowerOff">
      <arg direction="in" type="s" name="ip"/>
    </method>
    <method name="SetSource">
      <arg direction="in" type="s" name="ip"/>
      <arg direction="in" type="s" name="source"/>
    </method>
    <method name="GetStatus">
      <arg direction="in" type="s" name="ip"/>
      <arg direction="out" type="a{sv}" name="status"/>
    </method>
    <method name="StartCast">
      <arg direction="in" type="s" name="ip"/>
      <arg direction="out" type="b" name="success"/>
    </method>
    <method name="StopCast">
      <arg direction="out" type="b" name="success"/>
    </method>
    <method name="RunMacro">
      <arg direction="in" type="s" name="name"/>
      <arg direction="in" type="s" name="ip"/>
      <arg direction="out" type="b" name="success"/>
    </method>
    <signal name="DeviceFound">
      <arg type="s" name="ip"/>
      <arg type="s" name="name"/>
    </signal>
    <signal name="StatusChanged">
      <arg type="s" name="ip"/>
      <arg type="a{sv}" name="status"/>
    </signal>
    <property name="IsCasting" type="b" access="read"/>
  </interface>
</node>
"""


class ProjectorDBusService:
    def __init__(self):
        self.bus_name = "dev.linux_iprojection.Manager"
        self.object_path = "/dev/linux_iprojection/Manager"
        self.interface_name = "dev.linux_iprojection.Manager"

        self.node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self.interface_info = self.node_info.lookup_interface(self.interface_name)

        self.connection = None
        self.registration_id = None
        self.owner_id = None

        self._is_casting = False

    def start(self):
        self.owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            self.bus_name,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            self._on_name_acquired,
            self._on_name_lost
        )
        logger.info(f"Requested D-Bus name {self.bus_name}")

    def stop(self):
        if self.owner_id:
            Gio.bus_unown_name(self.owner_id)
            self.owner_id = None
        logger.info("D-Bus service stopped")

    def _on_bus_acquired(self, connection, name):
        self.connection = connection
        self.registration_id = connection.register_object(
            self.object_path,
            self.interface_info,
            self._on_method_call,
            self._on_get_property,
            self._on_set_property
        )
        logger.info(f"Bus acquired, registered object at {self.object_path}")

    def _on_name_acquired(self, connection, name):
        logger.info(f"Acquired bus name {name}")

    def _on_name_lost(self, connection, name):
        logger.warning(f"Lost bus name {name}")

    def _on_method_call(self, connection, sender, object_path, interface_name, method_name, parameters, invocation):
        try:
            if method_name == "Discover":
                devices = asyncio.run(discover_all(timeout=3))
                result = {dev.ip: dev.name for dev in devices}
                invocation.return_value(GLib.Variant("(a{ss})", (result,)))

            elif method_name == "PowerOn":
                ip = parameters.unpack()[0]
                asyncio.run(self._power_on(ip))
                invocation.return_value(None)

            elif method_name == "PowerOff":
                ip = parameters.unpack()[0]
                asyncio.run(self._power_off(ip))
                invocation.return_value(None)

            elif method_name == "SetSource":
                ip, source = parameters.unpack()
                asyncio.run(self._set_source(ip, source))
                invocation.return_value(None)

            elif method_name == "GetStatus":
                ip = parameters.unpack()[0]
                status_dict = asyncio.run(self._get_status(ip))
                variant_dict = {
                    k: GLib.Variant(self._get_variant_type(v), v)
                    for k, v in status_dict.items() if v is not None
                }
                invocation.return_value(GLib.Variant("(a{sv})", (variant_dict,)))

            elif method_name == "StartCast":
                ip = parameters.unpack()[0]
                logger.info(f"StartCast placeholder called for {ip}")
                self._is_casting = True
                invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "StopCast":
                logger.info("StopCast placeholder called")
                self._is_casting = False
                invocation.return_value(GLib.Variant("(b)", (False,)))

            elif method_name == "RunMacro":
                name, ip = parameters.unpack()
                success = asyncio.run(self._run_macro(name, ip))
                invocation.return_value(GLib.Variant("(b)", (success,)))

            else:
                invocation.return_error_literal(
                    Gio.DBusError,
                    Gio.DBusError.UNKNOWN_METHOD,
                    f"Unknown method: {method_name}"
                )

        except Exception as e:
            logger.error(f"Error calling {method_name}: {e}", exc_info=True)
            invocation.return_error_literal(Gio.DBusError, Gio.DBusError.FAILED, str(e))

    def _on_get_property(self, connection, sender, object_path, interface_name, property_name):
        if property_name == "IsCasting":
            return GLib.Variant("b", self._is_casting)
        return None

    def _on_set_property(self, connection, sender, object_path, interface_name, property_name, value):
        return False

    async def _power_on(self, ip):
        async with ProjectorClient(ip) as client:
            await client.power_on()

    async def _power_off(self, ip):
        async with ProjectorClient(ip) as client:
            await client.power_off()

    async def _set_source(self, ip, source):
        async with ProjectorClient(ip) as client:
            await client.set_source(source)

    async def _get_status(self, ip):
        async with ProjectorClient(ip) as client:
            return await client.get_status()

    async def _run_macro(self, name, ip):
        store = MacroStore()
        store.load()
        macro = next((m for m in store.macros if m.name == name), None)
        if not macro:
            return False

        async with ProjectorClient(ip) as client:
            for step in macro.steps:
                if step.action == 'power_on':
                    await client.power_on()
                elif step.action == 'power_off':
                    await client.power_off()
                elif step.action == 'set_source':
                    await client.set_source(step.value)
                elif step.action == 'delay':
                    await asyncio.sleep(float(step.value))
        return True

    def _get_variant_type(self, val):
        if isinstance(val, bool):
            return "b"
        if isinstance(val, int):
            return "i"
        if isinstance(val, float):
            return "d"
        if isinstance(val, str):
            return "s"
        return "s"
