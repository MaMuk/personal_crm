# SPDX-License-Identifier: LGPL-3.0-only
"""Permission-aware, bounded network reads. No stored graph or privileged reads."""

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from odoo import api, fields, models

WARN_NODES = 100
WARN_EDGES = 250
MAX_NODES = 500
MAX_EDGES = 2000
MAX_ROUNDS = 500


class RelationshipNetwork(models.Model):
    _inherit = "personal.crm.relationship"

    network_orientation = fields.Selection(
        [
            ("forward", "First role → Second role"),
            ("reverse", "Second role → First role"),
        ],
        compute="_compute_network_orientation",
        readonly=False,
        store=False,
        string="Role assignment",
    )
    network_guidance = fields.Char(compute="_compute_network_guidance")

    def _network_authorize(self):
        if self.env.user.share or not self.env.user.has_group(
            "personal_crm.group_user"
        ):
            raise AccessError(self.env._("Personal CRM authorization is required."))
        self.check_access("read")

    def _network_assignments(self):
        self.ensure_one()
        if not (self.type_id and self.left_partner_id and self.right_partner_id):
            return []
        if not (self.left_partner_id | self.right_partner_id).has_access(
            "read"
        ) or not self.type_id.has_access("read"):
            raise AccessError(
                self.env._(
                    "A selected contact or relationship type is unavailable or inaccessible."
                )
            )
        valid = []
        for reverse in (False, True):
            probe = self.new(
                {
                    "type_id": self.type_id.id,
                    "left_partner_id": (
                        self.right_partner_id if reverse else self.left_partner_id
                    ).id,
                    "right_partner_id": (
                        self.left_partner_id if reverse else self.right_partner_id
                    ).id,
                }
            )
            if probe._contacts_fit():
                valid.append("reverse" if reverse else "forward")
        return valid

    @api.depends("type_id", "left_partner_id", "right_partner_id")
    def _compute_network_orientation(self):
        for link in self:
            valid = link._network_assignments()
            link.network_orientation = (
                "forward"
                if (
                    link._origin.id
                    and link.type_id == link._origin.type_id
                    and link.left_partner_id == link._origin.left_partner_id
                    and link.right_partner_id == link._origin.right_partner_id
                )
                or link.type_id.is_symmetric
                else valid[0]
                if len(valid) == 1
                else False
            )

    @api.depends(
        "type_id", "left_partner_id", "right_partner_id", "network_orientation"
    )
    def _compute_network_guidance(self):
        for link in self:
            valid = link._network_assignments()
            link.network_guidance = (
                self.env._("Choose both contacts and a relationship type.")
                if not (link.type_id and link.left_partner_id and link.right_partner_id)
                else self.env._(
                    "These contacts do not satisfy the type's contact, tag, or self-link rules."
                )
                if not valid
                else self.env._(
                    "Both assignments are possible. Choose each contact's role explicitly."
                )
                if len(valid) == 2
                and not link.type_id.is_symmetric
                and not link.network_orientation
                else self.env._("Role assignment is valid.")
            )

    @api.onchange("type_id", "left_partner_id", "right_partner_id")
    def _onchange_network_participants(self):
        if self.env.context.get("personal_crm_network_editor"):
            for link in self:
                link._compute_network_orientation()
                link.reverse_roles = link.network_orientation == "reverse"

    @api.onchange("network_orientation")
    def _onchange_network_orientation(self):
        for link in self:
            link.reverse_roles = link.network_orientation == "reverse"

    @api.model
    def _network_editor_values(self, vals, record=None):
        vals = dict(vals)
        orientation = vals.pop("network_orientation", None)
        if self.env.context.get("personal_crm_network_editor"):
            probe = self.new(
                {
                    "type_id": vals.get(
                        "type_id", record.type_id.id if record else False
                    ),
                    "left_partner_id": vals.get(
                        "left_partner_id",
                        record.left_partner_id.id if record else False,
                    ),
                    "right_partner_id": vals.get(
                        "right_partner_id",
                        record.right_partner_id.id if record else False,
                    ),
                }
            )
            valid = probe._network_assignments()
            unchanged = (
                record
                and probe.type_id == record.type_id
                and probe.left_partner_id == record.left_partner_id
                and probe.right_partner_id == record.right_partner_id
            )
            choice = orientation or (
                "forward"
                if unchanged or probe.type_id.is_symmetric
                else valid[0]
                if len(valid) == 1
                else None
            )
            if choice not in valid:
                raise ValidationError(
                    self.env._("Choose a valid role assignment before saving.")
                )
            vals["reverse_roles"] = choice == "reverse"
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._network_editor_values(v) for v in vals_list])

    def write(self, vals):
        for link in self:
            super(RelationshipNetwork, link).write(
                self._network_editor_values(vals, link)
            )
        return True

    @api.model
    def network_search(self, query):
        self._network_authorize()
        return self.env["res.partner"].search_read(
            [("personal_crm_contact", "=", True), ("name", "ilike", str(query)[:100])],
            ["name"],
            limit=20,
        )

    @api.model
    def network_read(self, state, allow_large=False):
        """Rebuild from live data; commit no partial result on a warning/limit.

        Manual paths preserve their connecting expanded ancestors when depth falls.
        Collapsed nodes stop traversal; unreachable expansion state is discarded.
        Every visible pair's eligible records are read, including cross edges.
        """
        self._network_authorize()
        focal = int(state["focal"])
        partner = (
            self.env["res.partner"]
            .with_context(active_test=False)
            .search([("id", "=", focal)], limit=1)
        )
        if not partner:
            raise UserError(
                self.env._("The focal contact is unavailable or inaccessible.")
            )
        depth = max(1, min(4, int(state.get("depth", 1))))
        kinds = self.env["personal.crm.relationship.type"].search([])
        selected = set(state.get("types", kinds.ids)) & set(kinds.ids)
        collapsed = set(state.get("collapsed", []))
        manual = set(state.get("expanded", [])) - collapsed
        if (
            any(
                len(state.get(key, [])) > MAX_NODES for key in ("expanded", "collapsed")
            )
            or len(state.get("paths", {})) > MAX_NODES
        ):
            raise UserError(self.env._("Exploration state exceeds the safety limit."))
        revealed = list(state.get("revealed", []))[:MAX_EDGES]
        bridges = set()
        for path in state.get("paths", {}).values():
            if isinstance(path, list) and len(path) <= MAX_NODES:
                bridges.update(path)
        forced = manual | bridges
        full = state.get("scope") == "full"
        domain = self._current_domain() & Domain("type_id", "in", list(selected))
        visible, processed, paths = {focal}, set(), {focal: []}
        distances = {focal: 0}
        frontier = {focal}
        rounds = 0
        while frontier:
            rounds += 1
            if rounds > MAX_ROUNDS:
                raise UserError(
                    self.env._(
                        "Network traversal exceeded the safety limit. Narrow the relationship types."
                    )
                )
            expand = {
                pid
                for pid in frontier
                if pid not in collapsed
                and (full or distances[pid] < depth or pid in forced)
            } - processed
            incident = Domain("left_partner_id", "in", list(expand)) | Domain(
                "right_partner_id", "in", list(expand)
            )
            if revealed:
                incident |= Domain("id", "in", revealed) & (
                    Domain("left_partner_id", "in", list(frontier))
                    | Domain("right_partner_id", "in", list(frontier))
                )
            if not expand and not revealed:
                break
            edges = self.search(domain & incident, limit=MAX_EDGES + 1)
            if len(edges) > MAX_EDGES:
                raise UserError(
                    self.env._(
                        "Network exceeds the safety limit of %s relationships.",
                        MAX_EDGES,
                    )
                )
            processed.update(expand)
            next_frontier = set()
            for edge in edges:
                left, right = edge.left_partner_id.id, edge.right_partner_id.id
                for source, target in ((left, right), (right, left)):
                    if (
                        source in expand or (edge.id in revealed and source in frontier)
                    ) and target not in visible:
                        visible.add(target)
                        paths[target] = paths[source] + [source]
                        distances[target] = distances[source] + 1
                        next_frontier.add(target)
            if len(visible) > MAX_NODES:
                raise UserError(
                    self.env._(
                        "Network exceeds the safety limit of %s contacts. Narrow the relationship types.",
                        MAX_NODES,
                    )
                )
            if not allow_large and (
                len(visible) > WARN_NODES or len(edges) > WARN_EDGES
            ):
                return {
                    "warning": self.env._(
                        "This exploration includes at least %s contacts and %s relationships. Continue?",
                        len(visible),
                        len(edges),
                    )
                }
            frontier = next_frontier
        edges = self.search(
            domain
            & Domain("left_partner_id", "in", list(visible))
            & Domain("right_partner_id", "in", list(visible)),
            limit=MAX_EDGES + 1,
        )
        if len(edges) > MAX_EDGES:
            raise UserError(
                self.env._(
                    "Network exceeds the relationship safety limit (%s).", MAX_EDGES
                )
            )
        if not allow_large and len(edges) > WARN_EDGES:
            return {
                "warning": self.env._(
                    "This exploration contains %s relationships. Continue?", len(edges)
                )
            }
        # Access rules on relationships require readable endpoints; keep reads under the caller.
        contacts = (
            self.env["res.partner"]
            .with_context(active_test=False)
            .search([("id", "in", list(visible))])
        )
        nodes = [
            {
                "id": p.id,
                "name": p.name,
                "company": p.personal_crm_is_company,
                "tags": p.category_id.mapped("name"),
                "state": "collapsed"
                if p.id in collapsed
                else "expanded"
                if p.id in processed
                else "unexplored",
            }
            for p in contacts
        ]
        records = [
            {
                "id": e.id,
                "left": e.left_partner_id.id,
                "right": e.right_partner_id.id,
                "type": e.type_id.id,
                "name": e.type_id.name,
                "leftRole": e.left_label,
                "rightRole": e.right_label,
                "symmetric": e.type_id.is_symmetric,
                "start": fields.Date.to_string(e.date_start),
                "end": fields.Date.to_string(e.date_end),
                "notes": [
                    {"id": n.id, "name": n.name}
                    for n in e.note_ids
                    if n.has_access("read")
                ],
            }
            for e in edges
        ]
        return {
            "nodes": nodes,
            "edges": records,
            "types": [{"id": k.id, "name": k.name} for k in kinds],
            "selectedTypes": list(selected),
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "expanded": list(manual & visible),
            "collapsed": list(collapsed & visible),
            "paths": {str(pid): paths[pid] for pid in manual & visible if pid in paths},
            "complete": full and not (collapsed & visible),
            "processed": list(processed),
        }


class PartnerNetwork(models.Model):
    _inherit = "res.partner"

    def action_personal_crm_network(self):
        self.ensure_one()
        self.env["personal.crm.relationship"]._network_authorize()
        self.check_access("read")
        return {
            "type": "ir.actions.client",
            "tag": "personal_crm.network",
            "name": self.env._("Relationship network"),
            "params": {"partnerId": self.id},
        }
