#!/usr/bin/env bash
# linux-iprojection Test Runner & System Diagnostics Script
# Part of the iProjection (Unofficial) project by John Varghese (J0X)

set -e

GREEN='\033[0;32m'
NC='\033[0m'
BOLD='\033[1m'

echo -e "${BOLD}====================================================${NC}"
echo -e "${BOLD}   Epson iProjection Native Linux Diagnostics & Test   ${NC}"
echo -e "${BOLD}====================================================${NC}\n"

echo -e "${BOLD}[1/4] Environment Diagnostics:${NC}"
if command -v python3 >/dev/null 2>&1; then
    echo -e "  [+] Python 3: $(python3 --version)"
else
    echo -e "  [-] Python 3 not found in PATH"
fi

if command -v gst-launch-1.0 >/dev/null 2>&1; then
    echo -e "  [+] GStreamer 1.0: $(gst-launch-1.0 --version | head -n 1)"
else
    echo -e "  [-] GStreamer 1.0 not found"
fi

if command -v pipewire >/dev/null 2>&1; then
    echo -e "  [+] PipeWire sound/video server detected"
fi

echo -e "\n${BOLD}[2/4] Verifying Python Dependencies:${NC}"
python3 -c "
import sys
modules = ['gi', 'zeroconf', 'psutil', 'pytest']
for m in modules:
    try:
        __import__(m)
        print(f'  [+] {m}: available')
    except ImportError:
        print(f'  [-] {m}: missing')
" || true

echo -e "\n${BOLD}[3/4] Running Automated Unit Tests:${NC}"
if python3 -m pytest -v tests/; then
    echo -e "\n${GREEN}${BOLD}PASSED: All unit tests completed successfully!${NC}"
else
    echo -e "\n[-] Some unit tests failed. Check output above."
fi

echo -e "\n${BOLD}[4/4] Hardware Encoder Inspection:${NC}"
gst-inspect-1.0 vah264enc vaapih264enc nvh264enc x264enc 2>/dev/null | grep -E "Plugin Details|Name" || true

echo -e "\n${GREEN}${BOLD}Diagnostics and Test Run Complete!${NC}"
