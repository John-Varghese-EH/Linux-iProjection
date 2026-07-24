import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, AyatanaAppIndicator3
indicator = AyatanaAppIndicator3.Indicator.new(
    "test-indicator",
    "video-display-symbolic",
    AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS
)
indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
print("Indicator created successfully.")
