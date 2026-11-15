# SPDX-License-Identifier: LGPL-3.0-only
from datetime import date
from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools.safe_eval import safe_eval
from odoo.addons.personal_crm.models.backend import check_document_backend


class TestPersonalCrm(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login="pcrm_user", groups="personal_crm.group_user"
        )
        cls.outsider = new_test_user(
            cls.env, login="pcrm_outsider", groups="base.group_user"
        )
        cls.portal = new_test_user(
            cls.env, login="pcrm_portal", groups="base.group_portal"
        )
        cls.contacts = (
            cls.env["res.partner"]
            .with_user(cls.user)
            .create(
                [
                    {
                        "name": "Fictional Alex",
                        "personal_crm_contact": True,
                        "personal_crm_birthdate": "1990-02-03",
                    },
                    {"name": "Fictional Robin", "personal_crm_contact": True},
                ]
            )
        )

    def test_birthdate_and_notes(self):
        self.assertEqual(self.contacts[0].personal_crm_birthdate, date(1990, 2, 3))
        note = (
            self.env["personal.crm.note"]
            .with_user(self.user)
            .create(
                {
                    "name": "Shared note",
                    "body": "<p>Fictional memory</p>",
                    "partner_ids": [Command.set(self.contacts.ids)],
                }
            )
        )
        self.assertEqual(note.partner_ids, self.contacts)
        for partner in self.contacts:
            self.assertIn(note, partner.personal_crm_note_ids)
        self.assertTrue(note.create_date)
        note.body = "<p>Updated memory</p>"
        self.assertTrue(note.write_date)

    def test_inverse_relationship(self):
        relation = (
            self.env["personal.crm.relationship"]
            .with_user(self.user)
            .create(
                {
                    "left_partner_id": self.contacts[0].id,
                    "right_partner_id": self.contacts[1].id,
                    "type_id": self.env.ref("personal_crm.relationship_type_parent").id,
                }
            )
        )
        self.assertEqual(
            relation.with_context(current_partner_id=self.contacts[1].id).this_role,
            "Child",
        )
        self.assertIn(relation, self.contacts[1].personal_crm_relation_ids)

    def test_contact_and_note_privacy(self):
        note = (
            self.env["personal.crm.note"]
            .with_user(self.user)
            .create(
                {
                    "name": "Private note",
                    "partner_ids": [Command.set(self.contacts.ids)],
                }
            )
        )
        for user in (self.outsider, self.portal, self.env.ref("base.public_user")):
            with self.subTest(user=user.login):
                self.assertFalse(self.contacts.with_user(user).has_access("read"))
                self.assertFalse(note.with_user(user).has_access("read"))
                with self.assertRaises(AccessError):
                    self.env["personal.crm.note"].with_user(user).search(
                        [("id", "=", note.id)]
                    )
                with self.assertRaises(AccessError):
                    note.with_user(user).read(["body"])
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self.env["personal.crm.note"].with_user(user).create(
                        {"name": "Forbidden"}
                    )

    def test_notes_from_contact(self):
        self.contacts[0].write(
            {
                "personal_crm_note_ids": [
                    Command.create({"name": "From contact", "body": "<p>New</p>"})
                ]
            }
        )
        note = self.contacts[0].personal_crm_note_ids
        self.assertEqual(note.partner_ids, self.contacts[0])

    def test_custom_action_view_bindings(self):
        for kind, action_id in (
            ("person", "action_persons"),
            ("company", "action_companies"),
        ):
            action = self.env.ref("personal_crm." + action_id)
            form = action.view_ids.filtered(lambda v: v.view_mode == "form")
            self.assertEqual(
                form.view_id, self.env.ref("personal_crm." + kind + "_form")
            )

    def test_queued_backend_guard(self):
        modules = self.env["ir.module.module"].search(
            [
                (
                    "name",
                    "in",
                    ["personal_crm_documents", "personal_crm_documents_enterprise"],
                )
            ]
        )
        self.assertEqual(len(modules), 2)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            modules.write({"state": "to install"})
        with self.cr.savepoint():
            # A direct SQL setup simulates an installation queue before the core loads.
            self.cr.execute(
                "UPDATE ir_module_module SET state = 'to install' WHERE id = %s",
                (modules[0].id,),
            )
            modules.invalidate_recordset(["state"])
            other = (modules - modules[0]).name
            with self.assertRaises(ValidationError):
                check_document_backend(self.env, other)

    def _contact_note_context(self, kind, partner_id):
        view = self.env.ref(f"personal_crm.{kind}_form")
        arch = etree.fromstring(view.arch_db)
        field = arch.xpath("//field[@name='personal_crm_note_ids']")[0]
        return safe_eval(field.get("context"), {"id": partner_id})

    def test_note_from_unsaved_contact_form(self):
        for kind in ("person", "company"):
            with self.subTest(kind=kind):
                contact_form = Form(
                    self.env["res.partner"]
                    .with_user(self.user)
                    .with_context(
                        default_personal_crm_entity_type=kind,
                        default_personal_crm_contact=True,
                    ),
                    view=f"personal_crm.{kind}_form",
                )
                contact_form.name = f"Unsaved fictional {kind}"
                note_model = (
                    self.env["personal.crm.note"]
                    .with_user(self.user)
                    .with_context(self._contact_note_context(kind, False))
                )
                # Opening the child dialog calls default_get/onchange before
                # the parent has a database ID. No falsy partner may be linked.
                defaults = note_model.default_get(["partner_ids"])
                self.assertFalse(note_model.new(defaults).partner_ids)
                note_form = Form(note_model, view="personal_crm.note_form")
                note_form.name = f"Note for new {kind}"
                note = note_form.save()
                contact_form.personal_crm_note_ids.add(note)
                contact = contact_form.save()
                self.assertIn(note, contact.personal_crm_note_ids)
                self.assertEqual(note.partner_ids, contact)

    def test_note_defaults_from_saved_contact_form(self):
        for kind in ("person", "company"):
            with self.subTest(kind=kind):
                contact = self.contacts[0]
                note_model = (
                    self.env["personal.crm.note"]
                    .with_user(self.user)
                    .with_context(self._contact_note_context(kind, contact.id))
                )
                note_form = Form(note_model, view="personal_crm.note_form")
                self.assertIn(contact, note_form.partner_ids)
                note_form.name = f"Note from saved {kind} form"
                note = note_form.save()
                self.assertEqual(note.partner_ids, contact)
                self.assertIn(note, contact.personal_crm_note_ids)

    def test_relationship_partner_links_choose_person_and_company_forms(self):
        company = (
            self.env["res.partner"]
            .with_user(self.user)
            .create(
                {
                    "name": "Fictional linked company",
                    "personal_crm_entity_type": "company",
                    "personal_crm_contact": True,
                }
            )
        )
        for partner, kind in ((self.contacts[0], "person"), (company, "company")):
            with self.subTest(kind=kind):
                linked = partner.with_context(personal_crm_navigation=True)
                view_id = self.env.ref(f"personal_crm.{kind}_form").id
                # Many2one dialogs and full-page links use different entry points.
                self.assertEqual(linked.get_formview_id(), view_id)
                action = linked.get_record_default_action()
                self.assertEqual(action["views"], [(view_id, "form")])
                self.assertEqual(action["res_id"], partner.id)
                self.assertTrue(action["context"]["personal_crm_navigation"])
                self.assertNotIn(
                    partner.get_formview_id(),
                    [
                        self.env.ref("personal_crm.person_form").id,
                        self.env.ref("personal_crm.company_form").id,
                    ],
                )

    def test_personal_relationship_actions_use_scoped_views(self):
        views = [
            (self.env.ref("personal_crm.relation_list").id, "list"),
            (self.env.ref("personal_crm.relation_form").id, "form"),
        ]
        action = self.contacts[0].action_personal_crm_relations()
        self.assertEqual(action["views"], views)
        self.assertTrue(action["context"]["personal_crm_navigation"])
        self.assertEqual(action["context"]["current_partner_id"], self.contacts[0].id)
        menu_action = self.env.ref("personal_crm.menu_relations").action
        self.assertEqual(menu_action, self.env.ref("personal_crm.action_relations"))
        self.assertEqual(
            [
                (binding.view_id.id, binding.view_mode)
                for binding in menu_action.view_ids
            ],
            views,
        )
        for xid, names in (
            ("relation_list", ("this_partner_id", "other_partner_id")),
            ("relation_form", ("left_partner_id", "right_partner_id")),
        ):
            arch = etree.fromstring(
                self.env.ref(f"personal_crm.{xid}").get_combined_arch()
            )
            for name in names:
                context = arch.xpath(f"//field[@name='{name}']")[0].get("context")
                self.assertTrue(safe_eval(context)["personal_crm_navigation"])

    def test_people_and_company_tag_kanban_groups(self):
        tags = (
            self.env["res.partner.category"]
            .with_user(self.user)
            .create(
                [
                    {"name": "Test family", "color": 1},
                    {"name": "Test local", "color": 2},
                ]
            )
        )
        person, untagged = self.contacts
        person.category_id = [Command.set(tags.ids)]
        untagged.category_id = [Command.clear()]
        company = (
            self.env["res.partner"]
            .with_user(self.user)
            .create(
                {
                    "name": "Tagged organization",
                    "personal_crm_contact": True,
                    "personal_crm_entity_type": "company",
                    "category_id": [Command.link(tags[1].id)],
                }
            )
        )
        partners = self.env["res.partner"].with_user(self.user)
        for kind, ids, expected in (
            (
                "person",
                self.contacts.ids,
                {
                    tags[0].id: {person.id},
                    tags[1].id: {person.id},
                    False: {untagged.id},
                },
            ),
            ("company", company.ids, {tags[1].id: {company.id}}),
        ):
            with self.subTest(kind=kind):
                groups = partners._read_group(
                    [("id", "in", ids), ("personal_crm_entity_type", "=", kind)],
                    ["category_id"],
                    ["id:recordset"],
                )
                self.assertEqual(
                    {tag.id: set(records.ids) for tag, records in groups}, expected
                )
        self.assertIn(company, partners.search([("category_id", "in", tags[1].ids)]))
        self.assertIn(person, partners.search([("category_id", "in", tags[1].ids)]))
