# SPDX-License-Identifier: LGPL-3.0-only
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RelationshipType(models.Model):
    _name = "personal.crm.relationship.type"
    _description = "Personal CRM Relationship Type"
    _order = "name, id"
    _rec_names_search = (
        "name",
        "left_label",
        "right_label",
        "left_label_male",
        "left_label_female",
        "right_label_male",
        "right_label_female",
    )

    name = fields.Char(required=True, translate=True)
    is_symmetric = fields.Boolean("Same role on both sides")
    allow_self = fields.Boolean("Allow self relationships")
    left_label = fields.Char("First role (neutral)", required=True, translate=True)
    left_label_male = fields.Char("First role (male)", translate=True)
    left_label_female = fields.Char("First role (female)", translate=True)
    right_label = fields.Char("Second role (neutral)", required=True, translate=True)
    right_label_male = fields.Char("Second role (male)", translate=True)
    right_label_female = fields.Char("Second role (female)", translate=True)
    left_partner_type = fields.Selection(
        [("p", "Person"), ("c", "Company")], string="First contact kind"
    )
    right_partner_type = fields.Selection(
        [("p", "Person"), ("c", "Company")], string="Second contact kind"
    )
    left_partner_category_id = fields.Many2one(
        "res.partner.category", string="First contact tag"
    )
    right_partner_category_id = fields.Many2one(
        "res.partner.category", string="Second contact tag"
    )
    handle_invalid_onchange = fields.Selection(
        [
            ("restrict", "Reject changes that invalidate relationships"),
            ("ignore", "Keep existing relationships unchanged"),
            ("end", "End incompatible relationships today"),
            ("delete", "Delete incompatible relationships"),
        ],
        required=True,
        default="restrict",
        string="When rules change",
    )

    def role_label(self, side, partner):
        self.ensure_one()
        gender = (
            partner.personal_crm_gender
            if partner and not partner.personal_crm_is_company
            else False
        )
        if side == "right" and self.is_symmetric:
            side = "left"
        neutral = self[f"{side}_label"] or self.name or ""
        return (
            self[f"{side}_label_{gender}"] or neutral
            if gender in ("male", "female")
            else neutral
        )

    @api.onchange(
        "is_symmetric",
        "left_label",
        "left_label_male",
        "left_label_female",
        "left_partner_type",
        "left_partner_category_id",
    )
    def _onchange_symmetric(self):
        for kind in self.filtered("is_symmetric"):
            for suffix in (
                "label",
                "label_male",
                "label_female",
                "partner_type",
                "partner_category_id",
            ):
                kind[f"right_{suffix}"] = kind[f"left_{suffix}"]

    @api.model
    def _symmetric_values(self, values, record=None):
        values = dict(values)
        symmetric = values.get("is_symmetric", record.is_symmetric if record else False)
        if symmetric:
            for suffix in (
                "label",
                "label_male",
                "label_female",
                "partner_type",
                "partner_category_id",
            ):
                left, right = f"left_{suffix}", f"right_{suffix}"
                value = values.get(left, record[left] if record else False)
                values[right] = value.id if hasattr(value, "id") else value
        return values

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._symmetric_values(vals) for vals in vals_list])

    def write(self, vals):
        rules = {
            "left_partner_type",
            "right_partner_type",
            "left_partner_category_id",
            "right_partner_category_id",
            "allow_self",
            "is_symmetric",
        }
        for kind in self:
            values = self._symmetric_values(vals, kind)
            super(RelationshipType, kind).write(values)
            if rules.intersection(values):
                links = (
                    self.env["personal.crm.relationship"]
                    .with_context(active_test=False)
                    .search([("type_id", "=", kind.id)])
                )
                invalid = links.filtered(lambda link: not link._contacts_fit())
                policy = kind.handle_invalid_onchange
                if invalid and policy == "restrict":
                    raise ValidationError(
                        self.env._("Existing relationships do not satisfy these rules.")
                    )
                if policy == "delete":
                    invalid.unlink()
                elif policy == "end":
                    today = fields.Date.context_today(kind)
                    # Future relationships cannot be ended before they start.
                    future = invalid.filtered(
                        lambda link: link.date_start and link.date_start >= today
                    )
                    future.unlink()
                    invalid = invalid - future
                    invalid.filtered(
                        lambda link: not link.date_end or link.date_end > today
                    ).write({"date_end": today})
                if values.get("is_symmetric"):
                    # Existing directed links must not silently become duplicates.
                    (
                        links - invalid if policy == "delete" else links
                    ).exists()._check_overlap()
        return True

    def unlink(self):
        self.filtered(
            lambda kind: kind.handle_invalid_onchange == "delete"
        ).with_context(active_test=False).mapped("relationship_ids").unlink()
        return super().unlink()

    relationship_ids = fields.One2many(
        "personal.crm.relationship", "type_id", string="Relationships"
    )
