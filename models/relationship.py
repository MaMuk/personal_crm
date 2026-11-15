# SPDX-License-Identifier: LGPL-3.0-only
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from odoo import api, fields, models


class Relationship(models.Model):
    _name = "personal.crm.relationship"
    _description = "Personal CRM Relationship"
    _order = "date_start desc, id desc"
    _rec_names_search = (
        "left_partner_id.name",
        "right_partner_id.name",
        "type_id.name",
    )

    left_partner_id = fields.Many2one(
        "res.partner",
        string="First contact",
        required=True,
        index=True,
        ondelete="cascade",
    )
    right_partner_id = fields.Many2one(
        "res.partner",
        string="Second contact",
        required=True,
        index=True,
        ondelete="cascade",
    )
    type_id = fields.Many2one(
        "personal.crm.relationship.type",
        string="Relationship",
        required=True,
        index=True,
        ondelete="restrict",
    )
    date_start = fields.Date("From", index=True)
    date_end = fields.Date("Until", index=True)
    active = fields.Boolean(default=True)
    note_ids = fields.Many2many(
        "personal.crm.note",
        "personal_crm_relationship_note_rel",
        "relationship_id",
        "note_id",
        string="Personal notes",
    )
    type_is_symmetric = fields.Boolean(related="type_id.is_symmetric")
    reverse_roles = fields.Boolean(
        "First contact has the second role",
        compute="_compute_reverse_roles",
        readonly=False,
        help="Switch the role assignments before saving, for example when adding a parent from a child's contact.",
    )
    left_label = fields.Char(compute="_compute_labels", string="First contact's role")
    right_label = fields.Char(compute="_compute_labels", string="Second contact's role")
    this_partner_id = fields.Many2one(
        "res.partner",
        compute="_compute_perspective",
        search="_search_this_partner",
        string="Contact",
    )
    other_partner_id = fields.Many2one(
        "res.partner",
        compute="_compute_perspective",
        search="_search_other_partner",
        string="Related contact",
    )
    this_role = fields.Char(compute="_compute_perspective", string="Contact's role")
    other_role = fields.Char(
        compute="_compute_perspective", string="Related contact's role"
    )
    any_partner_id = fields.Many2one(
        "res.partner",
        compute="_compute_search_partner",
        search="_search_any_partner",
        string="Either contact",
    )
    is_current = fields.Boolean(
        compute="_compute_current", search="_search_current", string="Current"
    )
    left_partner_domain = fields.Json(compute="_compute_domains")
    right_partner_domain = fields.Json(compute="_compute_domains")
    type_domain = fields.Json(compute="_compute_domains")

    @api.model
    def add_batch(
        self,
        anchor_id,
        type_id,
        other_ids,
        anchor_role="left",
        date_start=False,
        date_end=False,
    ):
        """Create one relationship per selected contact, in one transaction."""
        self.check_access("create")
        if (
            anchor_role not in ("left", "right")
            or not isinstance(other_ids, list)
            or not other_ids
        ):
            raise ValidationError(
                self.env._("Choose a role and at least one related contact.")
            )
        if len(other_ids) != len(set(other_ids)):
            raise ValidationError(
                self.env._("Each related contact can be selected only once.")
            )
        partner_ids = {anchor_id, *other_ids}
        partners = self.env["res.partner"].browse(list(partner_ids)).exists()
        kind = self.env["personal.crm.relationship.type"].browse(type_id).exists()
        if len(partners) != len(partner_ids) or not kind:
            raise ValidationError(
                self.env._("A selected contact or relationship type is unavailable.")
            )
        if not partners.has_access("read") or not kind.has_access("read"):
            raise AccessError(
                self.env._("A selected contact or relationship type is inaccessible.")
            )
        values = []
        for other_id in other_ids:
            left, right = (
                (anchor_id, other_id)
                if anchor_role == "left" or kind.is_symmetric
                else (other_id, anchor_id)
            )
            values.append(
                {
                    "left_partner_id": left,
                    "right_partner_id": right,
                    "type_id": kind.id,
                    "date_start": date_start or False,
                    "date_end": date_end or False,
                }
            )
        return self.create(values).ids

    @api.model
    def batch_preview(
        self,
        anchor_id,
        type_id,
        other_ids,
        anchor_role="left",
        date_start=False,
        date_end=False,
    ):
        """Return role labels and eligibility without altering the selection."""
        self.check_access("read")
        if anchor_role not in ("left", "right"):
            raise ValidationError(self.env._("Choose a valid role assignment."))
        kind = self.env["personal.crm.relationship.type"].browse(type_id).exists()
        anchor = self.env["res.partner"].browse(anchor_id).exists()
        if (
            not kind
            or not anchor
            or not kind.has_access("read")
            or not anchor.has_access("read")
        ):
            return []
        result = []
        for other_id in other_ids:
            other = self.env["res.partner"].browse(other_id).exists()
            if not other or not other.has_access("read"):
                result.append(
                    {"id": other_id, "error": self.env._("Contact is unavailable.")}
                )
                continue
            left, right = (
                (anchor, other)
                if anchor_role == "left" or kind.is_symmetric
                else (other, anchor)
            )
            probe = self.new(
                {
                    "left_partner_id": left.id,
                    "right_partner_id": right.id,
                    "type_id": kind.id,
                }
            )
            pair = Domain("left_partner_id", "=", left.id) & Domain(
                "right_partner_id", "=", right.id
            )
            if kind.is_symmetric:
                pair |= Domain("left_partner_id", "=", right.id) & Domain(
                    "right_partner_id", "=", left.id
                )
            overlap = (
                Domain("type_id", "=", kind.id) & Domain("active", "=", True) & pair
            )
            if date_start:
                overlap &= Domain("date_end", "=", False) | Domain(
                    "date_end", ">=", date_start
                )
            if date_end:
                overlap &= Domain("date_start", "=", False) | Domain(
                    "date_start", "<=", date_end
                )
            error = (
                self.env._(
                    "Contact kind, tags, or self-link rules do not fit this relationship."
                )
                if not probe._contacts_fit()
                else self.env._("An overlapping relationship already exists.")
                if self.search_count(overlap, limit=1)
                else False
            )
            result.append(
                {
                    "id": other_id,
                    "anchor_label": kind.role_label(
                        "left" if left == anchor else "right", anchor
                    ),
                    "other_label": kind.role_label(
                        "right" if left == anchor else "left", other
                    ),
                    "error": error,
                }
            )
        return result

    def _compute_reverse_roles(self):
        self.reverse_roles = False

    @api.model
    def _normalize_roles(self, vals, record=None):
        vals = dict(vals)
        if vals.pop("reverse_roles", False):
            left = vals.get(
                "left_partner_id",
                record.left_partner_id.id
                if record
                else self.env.context.get("default_left_partner_id"),
            )
            right = vals.get(
                "right_partner_id",
                record.right_partner_id.id
                if record
                else self.env.context.get("default_right_partner_id"),
            )
            vals.update(left_partner_id=right, right_partner_id=left)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_roles(vals) for vals in vals_list])

    def write(self, vals):
        for link in self:
            super(Relationship, link).write(self._normalize_roles(vals, link))
        return True

    @api.depends(
        "reverse_roles",
        "type_id.left_label",
        "type_id.left_label_male",
        "type_id.left_label_female",
        "type_id.right_label",
        "type_id.right_label_male",
        "type_id.right_label_female",
        "type_id.is_symmetric",
        "left_partner_id.personal_crm_gender",
        "right_partner_id.personal_crm_gender",
        "left_partner_id.personal_crm_is_company",
        "right_partner_id.personal_crm_is_company",
    )
    @api.depends_context("lang")
    def _compute_labels(self):
        for link in self:
            link.left_label = (
                link.type_id.role_label(
                    "right" if link.reverse_roles else "left", link.left_partner_id
                )
                if link.type_id
                else False
            )
            link.right_label = (
                link.type_id.role_label(
                    "left" if link.reverse_roles else "right", link.right_partner_id
                )
                if link.type_id
                else False
            )

    @api.depends("left_partner_id", "right_partner_id", "left_label", "right_label")
    @api.depends_context("current_partner_id", "lang")
    def _compute_perspective(self):
        current = self.env.context.get("current_partner_id")
        for link in self:
            reverse = bool(current and link.right_partner_id.id == current)
            link.this_partner_id = (
                link.right_partner_id if reverse else link.left_partner_id
            )
            link.other_partner_id = (
                link.left_partner_id if reverse else link.right_partner_id
            )
            link.this_role = link.right_label if reverse else link.left_label
            link.other_role = link.left_label if reverse else link.right_label

    @api.depends(
        "this_partner_id.name", "other_partner_id.name", "this_role", "other_role"
    )
    @api.depends_context("current_partner_id", "lang")
    def _compute_display_name(self):
        for link in self:
            link.display_name = f"{link.this_partner_id.name or ''} ({link.this_role or ''}) → {link.other_partner_id.name or ''} ({link.other_role or ''})"

    def _compute_search_partner(self):
        self.any_partner_id = False

    @api.model
    def _search_any_partner(self, operator, value):
        first = Domain("left_partner_id", operator, value)
        second = Domain("right_partner_id", operator, value)
        return (
            first & second
            if operator in ("!=", "not in", "not ilike", "not like")
            else first | second
        )

    @api.model
    def _search_perspective_partner(self, operator, value, other):
        current = self.env.context.get("current_partner_id")
        if not current:
            return Domain(
                "right_partner_id" if other else "left_partner_id", operator, value
            )
        reverse = Domain("right_partner_id", "=", current)
        return (
            reverse
            & Domain(
                "left_partner_id" if other else "right_partner_id", operator, value
            )
        ) | (
            ~reverse
            & Domain(
                "right_partner_id" if other else "left_partner_id", operator, value
            )
        )

    def _search_this_partner(self, operator, value):
        return self._search_perspective_partner(operator, value, False)

    def _search_other_partner(self, operator, value):
        return self._search_perspective_partner(operator, value, True)

    @api.depends("active", "date_start", "date_end")
    @api.depends_context("tz")
    def _compute_current(self):
        today = fields.Date.context_today(self)
        for link in self:
            link.is_current = (
                link.active
                and (not link.date_start or link.date_start <= today)
                and (not link.date_end or link.date_end >= today)
            )

    @api.model
    def _current_domain(self, date=None):
        date = date or fields.Date.context_today(self)
        return (
            Domain("active", "=", True)
            & (Domain("date_start", "=", False) | Domain("date_start", "<=", date))
            & (Domain("date_end", "=", False) | Domain("date_end", ">=", date))
        )

    def _search_current(self, operator, value):
        # Odoo 20 normalizes Boolean searches to in/not in.
        if operator in ("in", "not in"):
            if not value:
                return Domain.FALSE if operator == "in" else Domain.TRUE
            wants_true = True in value
            if len(set(value)) > 1:
                return Domain.TRUE if operator == "in" else Domain.FALSE
            if operator == "not in":
                wants_true = not wants_true
        elif operator in ("=", "!="):
            wants_true = bool(value) == (operator == "=")
        else:
            return NotImplemented
        domain = self._current_domain()
        return domain if wants_true else ~domain

    @api.depends(
        "reverse_roles",
        "type_id",
        "type_id.left_partner_type",
        "type_id.right_partner_type",
        "type_id.left_partner_category_id",
        "type_id.right_partner_category_id",
        "left_partner_id.personal_crm_is_company",
        "right_partner_id.personal_crm_is_company",
        "left_partner_id.category_id",
        "right_partner_id.category_id",
    )
    def _compute_domains(self):
        for link in self:
            for side in ("left", "right"):
                domain = []
                role_side = (
                    ("right" if side == "left" else "left")
                    if link.reverse_roles
                    else side
                )
                kind = link.type_id[f"{role_side}_partner_type"]
                category = link.type_id[f"{role_side}_partner_category_id"]
                if kind:
                    domain.append(("personal_crm_is_company", "=", kind == "c"))
                if category:
                    domain.append(("category_id", "in", category.ids))
                link[f"{side}_partner_domain"] = domain
            domain = Domain.TRUE
            for side in ("left", "right"):
                partner = link[f"{side}_partner_id"]
                if partner:
                    side = (
                        ("right" if side == "left" else "left")
                        if link.reverse_roles
                        else side
                    )
                    domain &= Domain(f"{side}_partner_type", "=", False) | Domain(
                        f"{side}_partner_type",
                        "=",
                        "c" if partner.personal_crm_is_company else "p",
                    )
                    domain &= Domain(
                        f"{side}_partner_category_id", "=", False
                    ) | Domain(
                        f"{side}_partner_category_id", "in", partner.category_id.ids
                    )
            link.type_domain = list(domain)

    def _contacts_fit(self):
        self.ensure_one()
        if (
            self.left_partner_id == self.right_partner_id
            and not self.type_id.allow_self
        ):
            return False
        for side in ("left", "right"):
            partner = self[f"{side}_partner_id"]
            kind = self.type_id[f"{side}_partner_type"]
            category = self.type_id[f"{side}_partner_category_id"]
            if kind and partner.personal_crm_is_company != (kind == "c"):
                return False
            if category and category not in partner.category_id:
                return False
        return True

    @api.constrains("left_partner_id", "right_partner_id", "type_id")
    def _check_contacts(self):
        for link in self:
            (link.left_partner_id | link.right_partner_id).check_access("read")
            if not link._contacts_fit():
                raise ValidationError(
                    self.env._(
                        "Contact kind, tags, or self-relationship rules are incompatible with this relationship."
                    )
                )

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for link in self:
            if link.date_start and link.date_end and link.date_start > link.date_end:
                raise ValidationError(
                    self.env._("The start date must not be after the end date.")
                )

    @api.constrains(
        "left_partner_id",
        "right_partner_id",
        "type_id",
        "date_start",
        "date_end",
        "active",
    )
    def _check_overlap(self):
        for link in self.filtered("active"):
            pair = Domain("left_partner_id", "=", link.left_partner_id.id) & Domain(
                "right_partner_id", "=", link.right_partner_id.id
            )
            if link.type_id.is_symmetric:
                pair |= Domain(
                    "left_partner_id", "=", link.right_partner_id.id
                ) & Domain("right_partner_id", "=", link.left_partner_id.id)
            domain = (
                Domain("type_id", "=", link.type_id.id)
                & Domain("id", "!=", link.id)
                & Domain("active", "=", True)
                & pair
            )
            if link.date_start:
                domain &= Domain("date_end", "=", False) | Domain(
                    "date_end", ">=", link.date_start
                )
            if link.date_end:
                domain &= Domain("date_start", "=", False) | Domain(
                    "date_start", "<=", link.date_end
                )
            if self.search_count(domain, limit=1):
                raise ValidationError(
                    self.env._(
                        "This relationship already exists during an overlapping period."
                    )
                )
