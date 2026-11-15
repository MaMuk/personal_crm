# SPDX-License-Identifier: LGPL-3.0-only
from datetime import timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user

from odoo import Command, fields

from ..models import network


class TestRelationshipNetwork(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login="network_user", groups="personal_crm.group_user"
        )
        cls.outsider = new_test_user(
            cls.env, login="network_outsider", groups="base.group_user"
        )
        cls.partners = (
            cls.env["res.partner"]
            .with_user(cls.user)
            .create(
                [
                    {"name": name, "personal_crm_contact": True}
                    for name in ["Anna", "Peter", "Maria", "David", "Eva", "Isolated"]
                ]
            )
        )
        cls.a, cls.b, cls.c, cls.d, cls.e, cls.isolated = cls.partners
        cls.links = cls.env["personal.crm.relationship"].with_user(cls.user)
        cls.friend = cls.env.ref("personal_crm.relationship_type_friend")
        cls.sibling = cls.env.ref("personal_crm.relationship_type_sibling")
        cls.ab = cls.link(cls.a, cls.b)
        cls.bc = cls.link(cls.b, cls.c)
        cls.cd = cls.link(cls.c, cls.d)
        cls.de = cls.link(cls.d, cls.e)

    @classmethod
    def link(cls, left, right, kind=None, **values):
        return cls.links.create(
            {
                "left_partner_id": left.id,
                "right_partner_id": right.id,
                "type_id": (kind or cls.friend).id,
                **values,
            }
        )

    def read(self, focal=None, **state):
        return self.links.network_read(
            {"focal": (focal or self.a).id, "depth": 1, **state}
        )

    def ids(self, graph):
        return {n["id"] for n in graph["nodes"]}

    def test_depth_and_isolated(self):
        self.assertEqual(self.ids(self.read(self.isolated)), {self.isolated.id})
        self.assertEqual(self.ids(self.read()), {self.a.id, self.b.id})
        self.assertEqual(
            self.ids(self.read(depth=2)), {self.a.id, self.b.id, self.c.id}
        )
        self.assertFalse(self.read()["complete"])

    def test_cycle_induced_edges_and_parallel_records(self):
        ca = self.link(self.c, self.a)
        parallel = self.link(self.a, self.b, self.sibling)
        graph = self.read()
        self.assertEqual(self.ids(graph), {self.a.id, self.b.id, self.c.id})
        self.assertEqual(
            {e["id"] for e in graph["edges"]},
            {self.ab.id, self.bc.id, ca.id, parallel.id},
        )
        self.assertEqual(len(graph["nodes"]), 3)

    def test_manual_expansion_and_paths_survive_depth_change(self):
        first = self.read(depth=2, expanded=[self.c.id])
        graph = self.read(depth=1, expanded=first["expanded"], paths=first["paths"])
        self.assertEqual(self.ids(graph), {self.a.id, self.b.id, self.c.id, self.d.id})
        self.assertIn(self.c.id, graph["expanded"])

    def test_collapse_withdraws_descendants_and_their_state(self):
        graph = self.read(
            expanded=[self.b.id, self.c.id],
            collapsed=[self.b.id],
            paths={str(self.c.id): [self.a.id, self.b.id]},
        )
        self.assertEqual(self.ids(graph), {self.a.id, self.b.id})
        self.assertNotIn(self.c.id, graph["expanded"])
        self.assertEqual(graph["paths"], {})

    def test_collapse_preserves_alternative_expanded_path(self):
        self.link(self.a, self.d)
        graph = self.read(
            expanded=[self.b.id, self.c.id, self.d.id], collapsed=[self.b.id]
        )
        self.assertIn(self.c.id, self.ids(graph))
        self.assertIn(self.c.id, graph["expanded"])
        self.assertIn(self.e.id, self.ids(graph))

    def test_type_filters_and_empty_selection(self):
        self.link(self.a, self.c, self.sibling)
        self.assertEqual(self.ids(self.read(types=[])), {self.a.id})
        graph = self.read(types=[self.sibling.id], scope="full")
        self.assertEqual(self.ids(graph), {self.a.id, self.c.id})
        self.assertEqual(len(graph["edges"]), 1)

    def test_archived_contacts_remain_identifiable_on_current_connections(self):
        self.b.active = False
        graph = self.read()
        self.assertEqual(self.ids(graph), {self.a.id, self.b.id})
        self.assertEqual(self.ids(self.read(self.b, types=[])), {self.b.id})

    def test_current_inclusive_archive_and_future(self):
        today = fields.Date.context_today(self.links)
        self.ab.write({"date_end": today})
        self.assertIn(self.b.id, self.ids(self.read()))
        self.ab.write({"date_end": today - timedelta(days=1)})
        self.assertEqual(self.ids(self.read()), {self.a.id})
        self.ab.write({"date_end": False, "date_start": today + timedelta(days=1)})
        self.assertEqual(self.ids(self.read()), {self.a.id})
        self.ab.write({"date_start": False, "active": False})
        self.assertEqual(self.ids(self.read()), {self.a.id})

    def test_full_component_and_live_history_reads(self):
        state = {"focal": self.a.id, "scope": "full"}
        self.assertEqual(
            self.ids(self.links.network_read(state)),
            set((self.partners - self.isolated).ids),
        )
        self.assertTrue(self.links.network_read(state)["complete"])
        self.bc.unlink()
        self.assertEqual(
            self.ids(self.links.network_read(state)), {self.a.id, self.b.id}
        )

    def test_full_scope_collapse_keeps_other_expansion_contributions(self):
        graph = self.read(scope="full", collapsed=[self.e.id])
        self.assertEqual(self.ids(graph), set((self.partners - self.isolated).ids))
        self.assertFalse(graph["complete"])
        self.assertNotIn(self.e.id, graph["processed"])

    def test_reveal_only_saved_connection(self):
        graph = self.read(revealed=[self.bc.id])
        self.assertEqual(self.ids(graph), {self.a.id, self.b.id, self.c.id})
        self.assertNotIn(self.b.id, graph["processed"])
        self.assertNotIn(self.d.id, self.ids(graph))

    def test_self_link_and_role_labels(self):
        kind = self.env["personal.crm.relationship.type"].create(
            {
                "name": "Self",
                "left_label": "Self",
                "right_label": "Self",
                "allow_self": True,
                "is_symmetric": True,
            }
        )
        edge = self.link(self.isolated, self.isolated, kind)
        graph = self.read(self.isolated, scope="full")
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["edges"][0]["id"], edge.id)
        self.a.personal_crm_gender = "female"
        parent = self.link(
            self.a, self.c, self.env.ref("personal_crm.relationship_type_parent")
        )
        record = next(e for e in self.read()["edges"] if e["id"] == parent.id)
        self.assertEqual(record["leftRole"], "Mother")
        self.assertEqual(record["rightRole"], "Child")

    def test_warning_and_hard_limit_are_atomic(self):
        before = self.links.search_count([])
        with patch.object(network, "WARN_NODES", 1):
            self.assertEqual(set(self.read()), {"warning"})
            self.assertIn("nodes", self.links.network_read({"focal": self.a.id}, True))
        with patch.object(network, "MAX_NODES", 1), self.assertRaises(UserError):
            self.read(scope="full")
        with patch.object(network, "MAX_EDGES", 0), self.assertRaises(UserError):
            self.read()
        self.assertEqual(self.links.search_count([]), before)

    def test_unauthorized_network_and_search_and_action(self):
        with self.assertRaises(AccessError):
            self.links.with_user(self.outsider).network_read({"focal": self.a.id})
        with self.assertRaises(AccessError):
            self.links.with_user(self.outsider).network_search("Anna")
        with self.assertRaises(AccessError):
            self.a.with_user(self.outsider).action_personal_crm_network()

    def test_hidden_contact_never_leaks_through_edges_or_search(self):
        self.env["ir.access"].create(
            {
                "name": "Network hide Maria",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "operation": "r",
                "domain": f"[('id', '!=', {self.c.id})]",
            }
        )
        graph = self.read(scope="full")
        self.assertEqual(self.ids(graph), {self.a.id, self.b.id})
        self.assertEqual({e["id"] for e in graph["edges"]}, {self.ab.id})
        self.assertFalse(self.links.network_search("Maria"))

    def test_editor_ambiguous_orientation_requires_choice(self):
        links = self.links.with_context(personal_crm_network_editor=True)
        vals = {
            "left_partner_id": self.a.id,
            "right_partner_id": self.c.id,
            "type_id": self.env.ref("personal_crm.relationship_type_parent").id,
        }
        with self.assertRaises(ValidationError):
            links.create(vals)
        edge = links.create({**vals, "network_orientation": "reverse"})
        self.assertEqual(edge.left_partner_id, self.c)
        self.assertEqual(edge.right_partner_id, self.a)

    def test_unique_orientation_and_company_without_tax(self):
        company = (
            self.env["res.partner"]
            .with_user(self.user)
            .create(
                {
                    "name": "Authority",
                    "personal_crm_contact": True,
                    "personal_crm_entity_type": "company",
                }
            )
        )
        edge = self.links.with_context(personal_crm_network_editor=True).create(
            {
                "left_partner_id": company.id,
                "right_partner_id": self.a.id,
                "type_id": self.env.ref("personal_crm.relationship_type_employment").id,
            }
        )
        self.assertEqual(edge.left_partner_id, self.a)
        self.assertEqual(edge.right_partner_id, company)

    def test_editor_form_onchange_roles_and_notes(self):
        with Form(
            self.links.with_context(personal_crm_network_editor=True),
            view="personal_crm.network_editor_form",
        ) as form:
            form.left_partner_id = self.a
            form.right_partner_id = self.c
            form.type_id = self.env.ref("personal_crm.relationship_type_parent")
            self.assertFalse(form.network_orientation)
            form.network_orientation = "reverse"
            self.assertTrue(form.reverse_roles)
            self.assertEqual(form.left_label, "Child")
        edge = form.record
        note = self.env["personal.crm.note"].create(
            {
                "name": "Shared",
                "relationship_ids": [Command.link(edge.id)],
                "partner_ids": [Command.link(self.a.id)],
            }
        )
        edge.unlink()
        self.assertTrue(note.exists())
        self.assertEqual(note.partner_ids, self.a)

    def test_action_and_no_persistent_network_fields(self):
        self.assertEqual(
            self.a.with_user(self.user).action_personal_crm_network()["params"][
                "partnerId"
            ],
            self.a.id,
        )
        for name in ("network_orientation", "network_guidance"):
            self.assertFalse(self.links._fields[name].store)
