"""
linux-iprojection: Epson projector control application.
Part of the iProjection (Unofficial) project by John Varghese (J0X)
https://github.com/John-Varghese-EH
"""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("linux-iprojection")
except importlib.metadata.PackageNotFoundError:
    __version__ = "1.1.0"
