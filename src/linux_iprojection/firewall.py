"""
Firewall configuration utility for linux-iprojection.
Automatically detects and configures UFW or firewalld to allow necessary ports.
"""

import subprocess
import logging

log = logging.getLogger(__name__)

REQUIRED_PORTS = [
    ("3629", "tcp", "ESC/VP.net Projector Control"),
    ("4352", "tcp", "PJLink Control"),
    ("3620", "udp", "EEMP Discovery Broadcast"),
    ("3621", "udp", "EEMP Discovery Response"),
    ("5004", "udp", "RTP Video Stream"),
    ("5006", "udp", "RTP Audio Stream"),
    ("5353", "udp", "mDNS Discovery"),
]

def _run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def is_ufw_active() -> bool:
    code, stdout, _ = _run_cmd(["sudo", "ufw", "status"])
    return code == 0 and "Status: active" in stdout

def is_firewalld_active() -> bool:
    code, stdout, _ = _run_cmd(["systemctl", "is-active", "firewalld"])
    return code == 0 and stdout == "active"

def setup_ufw() -> bool:
    print("Configuring UFW...")
    success = True
    for port, proto, desc in REQUIRED_PORTS:
        print(f"Allowing {port}/{proto} ({desc})...")
        code, _, stderr = _run_cmd(["sudo", "ufw", "allow", f"{port}/{proto}"])
        if code != 0:
            print(f"  Failed: {stderr}")
            success = False
    if success:
        print("UFW configured successfully.")
    return success

def setup_firewalld() -> bool:
    print("Configuring Firewalld...")
    success = True
    for port, proto, desc in REQUIRED_PORTS:
        print(f"Allowing {port}/{proto} ({desc})...")
        code, _, stderr = _run_cmd(["sudo", "firewall-cmd", "--add-port", f"{port}/{proto}", "--permanent"])
        if code != 0:
            print(f"  Failed: {stderr}")
            success = False
    if success:
        print("Reloading firewalld...")
        _run_cmd(["sudo", "firewall-cmd", "--reload"])
        print("Firewalld configured successfully.")
    return success

def configure_firewall() -> bool:
    """Detect active firewall and configure it."""
    # Check if we have sudo privileges first without prompting if possible,
    # but since it's a CLI command, prompting is fine.
    print("Checking firewall status (may prompt for sudo password)...")
    
    if is_ufw_active():
        return setup_ufw()
    elif is_firewalld_active():
        return setup_firewalld()
    else:
        print("No supported active firewall found (UFW or firewalld).")
        print("Please manually allow the following ports:")
        for port, proto, desc in REQUIRED_PORTS:
            print(f"  {port}/{proto} - {desc}")
        return False
