# SPDX-License-Identifier: LGPL-3.0-only
from odoo import models


class IrUiView(models.Model):
    """Include the view model in this addon's schema initialization.

    An existing database can have required view columns from addons loaded
    later, such as Website's visibility. Registering this extension makes
    Odoo initialize ir.ui.view before loading our XML: its normal
    _check_removed_columns temporarily relaxes constraints for unloaded fields.
    The loader initializes those fields again after their addons are loaded,
    restoring their defaults and required constraints. No Website dependency
    or change to view creation/security is needed.
    """

    _inherit = "ir.ui.view"
