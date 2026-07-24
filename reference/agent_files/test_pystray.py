import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

import pystray
from PIL import Image

def create_image():
    # Create an image for the icon
    image = Image.new('RGB', (64, 64), color = (73, 109, 137))
    return image

icon = pystray.Icon("test_icon", create_image(), "Test Icon")
import threading
threading.Thread(target=icon.run).start()

print("Pystray started with GTK4!")
import time
time.sleep(2)
icon.stop()
