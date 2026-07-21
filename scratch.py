import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

sg = Gtk.ShortcutsGroup()
print([attr for attr in dir(sg) if 'add' in attr or 'append' in attr])
