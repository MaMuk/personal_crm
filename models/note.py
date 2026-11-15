# SPDX-License-Identifier: LGPL-3.0-only
from odoo import fields, models


class PersonalCrmNote(models.Model):
    _name = "personal.crm.note"
    _description = "Personal CRM Note"
    _order = "date desc, id desc"

    name = fields.Char("Title", required=True)
    date = fields.Date(
        "Note date", default=fields.Date.context_today, required=True, index=True
    )
    body = fields.Html("Note", sanitize=True)
    partner_ids = fields.Many2many(
        "res.partner",
        "personal_crm_note_partner_rel",
        "note_id",
        "partner_id",
        string="Related contacts",
    )

    relationship_ids = fields.Many2many(
        "personal.crm.relationship",
        "personal_crm_relationship_note_rel",
        "note_id",
        "relationship_id",
        string="Related relationships",
    )
