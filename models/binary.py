# SPDX-License-Identifier: LGPL-3.0-only
from odoo import models


class IrBinary(models.AbstractModel):
    _inherit = "ir.binary"

    def _find_record(
        self,
        xmlid=None,
        res_model="ir.attachment",
        res_id=None,
        access_token=None,
        field=None,
    ):
        record = super()._find_record(
            xmlid=xmlid,
            res_model=res_model,
            res_id=res_id,
            access_token=access_token,
            field=field,
        )
        # Standard tokens/public attachments must not bypass personal record ACLs.
        # Sudo reads only attachment linkage, never file content.
        if record._name == "ir.attachment":
            attachment = record.sudo()
            if (
                attachment.res_model in ("personal.crm.document", "personal.crm.note")
                and attachment.res_id
            ):
                self.env[attachment.res_model].browse(attachment.res_id).check_access(
                    "read"
                )
        elif record._name in ("personal.crm.document", "personal.crm.note"):
            record.with_env(self.env).check_access("read")
        return record
