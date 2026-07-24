from enum import Enum
class Source(str, Enum):
    HDMI1 = "30"
def set_source(s: Source):
    if isinstance(s, Enum):
        print(s.value)
    else:
        print(s)
set_source(Source.HDMI1)
set_source("30")
