# SPDX-License-Identifier: LGPL-3.0-only
from odoo import models
from odoo.exceptions import ValidationError

BACKENDS = ("personal_crm_documents", "personal_crm_documents_enterprise")


def check_document_backend(env, selected):
    """Check both installed and queued modules, including one install transaction."""
    other = next(name for name in BACKENDS if name != selected)
    if env["ir.module.module"].search_count(
        [
            ("name", "=", other),
            ("state", "in", ["installed", "to install", "to upgrade"]),
        ]
    ):
        raise ValidationError(
            env._(
                "Select only one Personal CRM document backend. Uninstall the other backend first."
            )
        )


class IrModuleModule(models.Model):
    _inherit = "ir.module.module"

    def _check_personal_crm_document_backends(self):
        if any(module.name in BACKENDS for module in self):
            active = self.search_count(
                [
                    ("name", "in", list(BACKENDS)),
                    ("state", "in", ["installed", "to install", "to upgrade"]),
                ]
            )
            if active > 1:
                raise ValidationError(
                    self.env._("Select only one Personal CRM document backend.")
                )

    def write(self, vals):
        result = super().write(vals)
        if "state" in vals:
            self._check_personal_crm_document_backends()
        return result
