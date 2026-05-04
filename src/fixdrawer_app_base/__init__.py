"""FixDrawer shared app SDK.

Reusable building blocks for FixDrawer-branded Tk desktop tools
(Seller CSV Fixer, Receipt Fixer, …). Vendor this directory in
each tool until it is published as an installable package.
"""

from fixdrawer_app_base.platform import (
    find_asset,
    folder_open_action,
    open_folder,
)
from fixdrawer_app_base.tk_widgets import ReadOnlyTextPanel

__all__ = [
    "ReadOnlyTextPanel",
    "find_asset",
    "folder_open_action",
    "open_folder",
]
