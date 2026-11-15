# SPDX-License-Identifier: LGPL-3.0-only
from odoo.exceptions import ValidationError
from odoo.fields import Domain

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    personal_crm_contact = fields.Boolean(
        "Personal CRM contact", index=True, copy=False
    )
    personal_crm_entity_type = fields.Selection(
        [("person", "Person"), ("company", "Company / authority")],
        string="Contact kind",
        required=True,
        default="person",
        index=True,
        help="Personal CRM classification, independent of Odoo's VAT-based company heuristic.",
    )
    personal_crm_is_company = fields.Boolean(
        compute="_compute_personal_crm_is_company",
        search="_search_personal_crm_is_company",
        groups="personal_crm.group_user",
    )

    @api.depends("personal_crm_contact", "personal_crm_entity_type", "is_company")
    def _compute_personal_crm_is_company(self):
        for partner in self:
            partner.personal_crm_is_company = (
                partner.personal_crm_entity_type == "company"
                if partner.personal_crm_contact
                else partner.is_company
            )

    @api.model
    def _search_personal_crm_is_company(self, operator, value):
        domain = (
            Domain("personal_crm_contact", "=", True)
            & Domain("personal_crm_entity_type", "=", "company")
        ) | (
            Domain("personal_crm_contact", "=", False) & Domain("is_company", "=", True)
        )
        if operator in ("in", "not in"):
            if not value:
                return Domain.FALSE if operator == "in" else Domain.TRUE
            if len(set(value)) > 1:
                return Domain.TRUE if operator == "in" else Domain.FALSE
            positive = (True in value) == (operator == "in")
        elif operator in ("=", "!="):
            positive = bool(value) == (operator == "=")
        else:
            return NotImplemented
        return domain if positive else ~domain

    personal_crm_birthdate = fields.Date("Birthdate", groups="personal_crm.group_user")
    personal_crm_note_ids = fields.Many2many(
        "personal.crm.note",
        "personal_crm_note_partner_rel",
        "partner_id",
        "note_id",
        string="Personal notes",
        groups="personal_crm.group_user",
    )
    personal_crm_gender = fields.Selection(
        [
            ("female", "Female"),
            ("male", "Male"),
            ("unknown", "Unknown"),
        ],
        string="Gender",
        groups="personal_crm.group_user",
        help="Used for relationship role labels. Unknown or unset uses neutral labels.",
    )
    personal_crm_relationship_left_ids = fields.One2many(
        "personal.crm.relationship", "left_partner_id", groups="personal_crm.group_user"
    )
    personal_crm_relationship_right_ids = fields.One2many(
        "personal.crm.relationship",
        "right_partner_id",
        groups="personal_crm.group_user",
    )
    personal_crm_relation_ids = fields.Many2many(
        "personal.crm.relationship",
        compute="_compute_personal_crm_relations",
        string="Relationships",
        groups="personal_crm.group_user",
    )
    personal_crm_relationship_count = fields.Integer(
        compute="_compute_personal_crm_relationship_count",
        groups="personal_crm.group_user",
    )
    personal_crm_search_relationship_type_id = fields.Many2one(
        "personal.crm.relationship.type",
        compute="_compute_relationship_search_fields",
        search="_search_relationship_type",
        string="Relationship type",
        groups="personal_crm.group_user",
    )
    personal_crm_search_relationship_partner_id = fields.Many2one(
        "res.partner",
        compute="_compute_relationship_search_fields",
        search="_search_relationship_partner",
        string="Related contact",
        groups="personal_crm.group_user",
    )
    personal_crm_search_relationship_category_id = fields.Many2one(
        "res.partner.category",
        compute="_compute_relationship_search_fields",
        search="_search_relationship_category",
        string="Related contact tag",
        groups="personal_crm.group_user",
    )
    personal_crm_search_relationship_date = fields.Date(
        compute="_compute_relationship_search_fields",
        search="_search_relationship_date",
        string="Relationship valid on",
        groups="personal_crm.group_user",
    )

    @api.depends(
        "personal_crm_relationship_left_ids", "personal_crm_relationship_right_ids"
    )
    def _compute_personal_crm_relations(self):
        for partner in self:
            partner.personal_crm_relation_ids = (
                partner.personal_crm_relationship_left_ids
                | partner.personal_crm_relationship_right_ids
            )

    @api.depends(
        "personal_crm_relationship_left_ids.active",
        "personal_crm_relationship_right_ids.active",
        "personal_crm_relationship_left_ids.date_start",
        "personal_crm_relationship_left_ids.date_end",
        "personal_crm_relationship_right_ids.date_start",
        "personal_crm_relationship_right_ids.date_end",
    )
    @api.depends_context("uid", "tz")
    def _compute_personal_crm_relationship_count(self):
        links = self.env["personal.crm.relationship"]
        domain = links._current_domain() & (
            Domain("left_partner_id", "in", self.ids)
            | Domain("right_partner_id", "in", self.ids)
        )
        counts = dict.fromkeys(self.ids, 0)
        for left, right, count in links._read_group(
            domain, ["left_partner_id", "right_partner_id"], ["__count"]
        ):
            for partner_id in {left.id, right.id} & counts.keys():
                counts[partner_id] += count
        for partner in self:
            partner.personal_crm_relationship_count = counts.get(partner.id, 0)

    def _compute_relationship_search_fields(self):
        for name in ("type_id", "partner_id", "category_id", "date"):
            self[f"personal_crm_search_relationship_{name}"] = False

    @api.model
    def _partners_with_relationship(self, domain):
        links = self.env["personal.crm.relationship"].search(domain)
        return Domain("id", "in", (links.left_partner_id | links.right_partner_id).ids)

    @api.model
    def _search_relationship_type(self, operator, value):
        positive = {
            "!=": "=",
            "not in": "in",
            "not like": "like",
            "not ilike": "ilike",
        }.get(operator)
        if positive:
            return ~self._search_relationship_type(positive, value)
        return self._partners_with_relationship(Domain("type_id", operator, value))

    @api.model
    def _search_relationship_partner(self, operator, value):
        positive = {
            "!=": "=",
            "not in": "in",
            "not like": "like",
            "not ilike": "ilike",
        }.get(operator)
        if positive:
            return ~self._search_relationship_partner(positive, value)
        links = self.env["personal.crm.relationship"]
        left = links.search(Domain("right_partner_id", operator, value)).left_partner_id
        right = links.search(
            Domain("left_partner_id", operator, value)
        ).right_partner_id
        return Domain("id", "in", (left | right).ids)

    @api.model
    def _search_relationship_category(self, operator, value):
        positive = {
            "!=": "=",
            "not in": "in",
            "not like": "like",
            "not ilike": "ilike",
        }.get(operator)
        if positive:
            return ~self._search_relationship_category(positive, value)
        links = self.env["personal.crm.relationship"]
        left = links.search(
            Domain("right_partner_id.category_id", operator, value)
        ).left_partner_id
        right = links.search(
            Domain("left_partner_id.category_id", operator, value)
        ).right_partner_id
        return Domain("id", "in", (left | right).ids)

    @api.model
    def _search_relationship_date(self, operator, value):
        values = (
            list(value)
            if not isinstance(value, str) and hasattr(value, "__iter__")
            else [value]
        )
        if operator not in ("=", "in") or len(values) != 1:
            raise ValidationError(
                self.env._("Choose one date using the equals operator.")
            )
        return self._partners_with_relationship(
            self.env["personal.crm.relationship"]._current_domain(values[0])
        )

    def action_personal_crm_relations(self):
        self.ensure_one()
        self.check_access("read")
        action = self.env["ir.actions.actions"]._for_xml_id(
            "personal_crm.action_relations"
        )
        action["domain"] = [
            "|",
            ("left_partner_id", "=", self.id),
            ("right_partner_id", "=", self.id),
        ]
        action["context"] = {
            "default_left_partner_id": self.id,
            "current_partner_id": self.id,
            "personal_crm_navigation": True,
            "search_default_current": 1,
        }
        action["views"] = [
            (self.env.ref("personal_crm.relation_list").id, "list"),
            (self.env.ref("personal_crm.relation_form").id, "form"),
        ]
        return action

    def write(self, vals):
        result = super().write(vals)
        if {
            "is_company",
            "personal_crm_entity_type",
            "personal_crm_contact",
            "category_id",
        }.intersection(vals):
            # Integrity checks must also see links hidden by contact/company rules.
            # Only a generic validation result leaves this narrow privileged read.
            links = (
                self.env["personal.crm.relationship"]
                .sudo()
                .with_context(active_test=False)
                .search(
                    [
                        "|",
                        ("left_partner_id", "in", self.ids),
                        ("right_partner_id", "in", self.ids),
                    ]
                )
            )
            if any(not link._contacts_fit() for link in links):
                raise ValidationError(
                    self.env._("This change would invalidate an existing relationship.")
                )
        return result

    @api.readonly
    def get_formview_id(self, access_uid=None):
        """Choose the minimal form for links opened within Personal CRM."""
        if self.env.context.get("personal_crm_navigation") and len(self) == 1:
            partner = self.with_user(access_uid or self.env.uid)
            if partner.env.user.has_group("personal_crm.group_user"):
                partner.check_access("read")
                kind = "company" if partner.personal_crm_is_company else "person"
                return partner.env.ref(f"personal_crm.{kind}_form").id
        return super().get_formview_id(access_uid=access_uid)

    def init(self):
        super().init()
        if not self.env.su:
            return
        allowed = tuple(
            value for value, label in self._fields["personal_crm_gender"].selection
        )
        self.env.cr.execute(
            "UPDATE res_partner SET personal_crm_gender = %s "
            "WHERE personal_crm_gender IS NOT NULL AND personal_crm_gender NOT IN %s RETURNING id",
            ("unknown", allowed),
        )
        changed = self.browse([row[0] for row in self.env.cr.fetchall()])
        if changed:
            changed.invalidate_recordset(["personal_crm_gender"])
            changed.modified(["personal_crm_gender"])
