"""
Tray icon subprocess for linux-iprojection.
Communicates with the main GTK4 app via standard input/output.
"""
import sys
import threading

import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as item

# Global state updated from main app
state = {
    "connected": False,
    "casting": False
}

icon_ref = None

def create_icon_image():
    width = 64
    height = 64
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.rectangle((8, 16, 56, 48), fill=(53, 132, 228), outline=(255, 255, 255), width=3)
    dc.ellipse((36, 24, 48, 36), fill=(255, 255, 255))
    dc.polygon([(16, 48), (20, 56), (44, 56), (48, 48)], fill=(119, 118, 123))
    return image

def on_click(icon, action_item):
    cmd = ""
    if action_item.text == "Hide / Show Window":
        cmd = "TOGGLE_WINDOW"
    elif action_item.text == "Freeze Image":
        cmd = "FREEZE_TOGGLE"
    elif action_item.text == "Toggle Mute (A/V)":
        cmd = "MUTE_TOGGLE"
    elif action_item.text == "Power Off":
        cmd = "POWER_OFF"
    elif action_item.text == "Stop Sharing":
        cmd = "STOP_SHARING"
    elif action_item.text == "Quit":
        cmd = "QUIT"

    print(cmd, flush=True)

    if cmd == "QUIT":
        icon.stop()

def stdin_listener():
    global icon_ref
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line.startswith("STATE:"):
            key, val = line.split(":", 1)[1].split("=")
            state[key] = (val == "1")
            if icon_ref:
                icon_ref.update_menu()

def main():
    global icon_ref
    
    # Start thread to listen for state updates
    threading.Thread(target=stdin_listener, daemon=True).start()

    menu = (
        item('Hide / Show Window', on_click, default=True),
        pystray.Menu.SEPARATOR,
        item('Toggle Mute (A/V)', on_click, enabled=lambda i: state["connected"]),
        item('Freeze Image', on_click, enabled=lambda i: state["connected"]),
        item('Stop Sharing', on_click, enabled=lambda i: state["casting"]),
        item('Power Off', on_click, enabled=lambda i: state["connected"]),
        pystray.Menu.SEPARATOR,
        item('Quit', on_click)
    )

    icon_ref = pystray.Icon(
        "linux-iprojection-tray",
        create_icon_image(),
        "iProjection",
        menu
    )
    icon_ref.run()

if __name__ == "__main__":
    main()
