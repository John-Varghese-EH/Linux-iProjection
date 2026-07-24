import pystray
from PIL import Image
from pystray import MenuItem as item

def create_image():
    return Image.new('RGB', (64, 64), color = (73, 109, 137))

def on_click(icon, item):
    print(item.text, flush=True)

menu = (
    item('Hide/Show', on_click),
    item('Freeze', on_click),
    item('Stop Sharing', on_click),
    item('Quit', on_click)
)

icon = pystray.Icon("iprojection-tray", create_image(), "iProjection", menu)
icon.run()
