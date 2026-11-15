# SPDX-License-Identifier: LGPL-3.0-only
from datetime import timedelta

from lxml import etree
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools.safe_eval import safe_eval

from odoo import Command, fields


class TestRelationships(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login="native_relationship_user", groups="personal_crm.group_user"
        )
        cls.outsider = new_test_user(
            cls.env, login="native_relationship_outsider", groups="base.group_user"
        )
        cls.portal = new_test_user(
            cls.env, login="native_relationship_portal", groups="base.group_portal"
        )
        cls.links = cls.env["personal.crm.relationship"].with_user(cls.user)
        cls.kinds = cls.env["personal.crm.relationship.type"].with_user(cls.user)
        cls.people = (
            cls.env["res.partner"]
            .with_user(cls.user)
            .create(
                [
                    {
                        "name": "Test parent",
                        "personal_crm_gender": "female",
                        "personal_crm_contact": True,
                    },
                    {
                        "name": "Test child",
                        "personal_crm_gender": "male",
                        "personal_crm_contact": True,
                    },
                    {
                        "name": "Test other",
                        "personal_crm_gender": "female",
                        "personal_crm_contact": True,
                    },
                ]
            )
        )
        cls.company = (
            cls.env["res.partner"]
            .with_user(cls.user)
            .create(
                {
                    "name": "Test company",
                    "personal_crm_entity_type": "company",
                    "personal_crm_contact": True,
                }
            )
        )
        cls.parent = cls.env.ref("personal_crm.relationship_type_parent").with_user(
            cls.user
        )
        cls.sibling = cls.env.ref("personal_crm.relationship_type_sibling").with_user(
            cls.user
        )

    def link(self, kind=None, first=None, second=None, **values):
        return self.links.create(
            dict(
                {
                    "type_id": (kind or self.parent).id,
                    "left_partner_id": (first or self.people[0]).id,
                    "right_partner_id": (second or self.people[1]).id,
                },
                **values,
            )
        )

    def test_parent_child_gender_matrix(self):
        link = self.link()
        for first_gender, second_gender, first_label, second_label in (
            ("female", "male", "Mother", "Son"),
            ("female", "female", "Mother", "Daughter"),
            ("male", "male", "Father", "Son"),
            ("male", "female", "Father", "Daughter"),
            (False, "unknown", "Parent", "Child"),
            ("unknown", False, "Parent", "Child"),
        ):
            with self.subTest(first=first_gender, second=second_gender):
                self.people[0].personal_crm_gender = first_gender
                self.people[1].personal_crm_gender = second_gender
                self.assertEqual(
                    (link.left_label, link.right_label), (first_label, second_label)
                )
                reverse = link.with_context(current_partner_id=self.people[1].id)
                self.assertEqual(
                    (reverse.this_role, reverse.other_role), (second_label, first_label)
                )
                self.assertEqual(reverse.other_partner_id, self.people[0])

    def test_siblings_use_each_person_gender(self):
        link = self.link(self.sibling)
        self.assertEqual((link.left_label, link.right_label), ("Sister", "Brother"))
        reverse = link.with_context(current_partner_id=self.people[1].id)
        self.assertEqual((reverse.this_role, reverse.other_role), ("Brother", "Sister"))
        self.people[0].personal_crm_gender = "unknown"
        self.assertEqual(link.left_label, "Sibling")
        self.assertEqual(link.right_label, "Brother")

    def test_generic_seed_types(self):
        self.assertTrue(self.parent)
        self.assertTrue(self.sibling.is_symmetric)
        self.assertIn(
            self.parent.id,
            [identifier for identifier, label in self.kinds.name_search("Mother")],
        )
        self.assertIn(
            self.sibling.id,
            [identifier for identifier, label in self.kinds.name_search("Brother")],
        )
        # There is no separate Child, Brother, Sister, Mother, or Father category.
        self.assertFalse(
            self.kinds.search(
                [("name", "in", ["Child", "Brother", "Sister", "Mother", "Father"])]
            )
        )

    def test_reverse_create_normalizes_to_one_direction(self):
        link = self.link(
            first=self.people[1], second=self.people[0], reverse_roles=True
        )
        self.assertEqual(link.left_partner_id, self.people[0])
        self.assertEqual(link.right_partner_id, self.people[1])
        self.assertEqual((link.left_label, link.right_label), ("Mother", "Son"))
        self.assertFalse(link.reverse_roles)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.link()

    def test_add_batch_roles_preview_and_atomic_failure(self):
        anchor, first, second = self.people
        preview = self.links.batch_preview(
            anchor.id, self.parent.id, [first.id, second.id], "right"
        )
        self.assertEqual([row["error"] for row in preview], [False, False])
        self.assertEqual(preview[0]["anchor_label"], "Daughter")
        ids = self.links.add_batch(
            anchor.id, self.parent.id, [first.id, second.id], "right"
        )
        links = self.links.browse(ids)
        self.assertEqual(len(links), 2)
        self.assertEqual(
            set(links.mapped("left_partner_id").ids), {first.id, second.id}
        )
        self.assertEqual(set(links.mapped("right_partner_id").ids), {anchor.id})
        before = self.links.search_count([])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.links.add_batch(
                anchor.id, self.parent.id, [self.company.id, first.id], "right"
            )
        self.assertEqual(self.links.search_count([]), before)

    def test_add_batch_rejects_duplicate_selection_and_invalid_role(self):
        anchor, other = self.people[:2]
        for ids, role in (([other.id, other.id], "left"), ([other.id], "invalid")):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.links.add_batch(anchor.id, self.parent.id, ids, role)

    def test_reverse_roles_in_form_from_child(self):
        form = Form(
            self.links.with_context(default_left_partner_id=self.people[1].id),
            view="personal_crm.relation_form",
        )
        form.reverse_roles = True
        form.type_id = self.parent
        form.right_partner_id = self.people[0]
        self.assertEqual((form.left_label, form.right_label), ("Son", "Mother"))
        link = form.save()
        self.assertEqual(link.left_partner_id, self.people[0])
        self.assertEqual(link.right_partner_id, self.people[1])

    def test_symmetric_reverse_duplicate(self):
        self.link(self.sibling)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.link(self.sibling, first=self.people[1], second=self.people[0])

    def test_overlapping_and_separate_periods(self):
        self.link(date_start="2020-01-01", date_end="2020-12-31")
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.link(date_start="2020-12-31", date_end="2021-06-01")
        self.link(date_start="2021-01-01", date_end="2021-12-31")

    def test_invalid_dates(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.link(date_start="2022-01-02", date_end="2022-01-01")

    def test_self_links_and_type_change(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.link(second=self.people[0])
        kind = self.kinds.create(
            {
                "name": "Self",
                "left_label": "Self",
                "right_label": "Self",
                "allow_self": True,
            }
        )
        link = self.link(kind, second=self.people[0])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            link.type_id = self.parent

    def test_company_constraints_and_reverse(self):
        employment = self.env.ref("personal_crm.relationship_type_employment")
        self.assertTrue(self.company.personal_crm_is_company)
        self.assertFalse(self.company.vat)
        link = self.link(employment, second=self.company)
        self.assertEqual((link.left_label, link.right_label), ("Employee", "Employer"))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.link(employment)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.company.personal_crm_entity_type = "person"

    def test_tags_and_partner_changes(self):
        category = self.env["res.partner.category"].create({"name": "Membership"})
        self.people[0].category_id = [Command.link(category.id)]
        kind = self.kinds.create(
            {
                "name": "Tagged",
                "left_label": "Member",
                "right_label": "Contact",
                "left_partner_category_id": category.id,
            }
        )
        self.link(kind)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.people[0].category_id = [Command.clear()]

    def test_partner_type_changes_including_archived(self):
        link = self.link()
        link.active = False
        for person in self.people[:2]:
            with (
                self.subTest(person=person.id),
                self.assertRaises(ValidationError),
                self.cr.savepoint(),
            ):
                person.personal_crm_entity_type = "company"

    def test_current_dates_counts_and_archive(self):
        today = fields.Date.context_today(self.links)
        link = self.link(date_start=today, date_end=today)
        self.assertTrue(link.is_current)
        self.assertEqual(self.people[0].personal_crm_relationship_count, 1)
        self.assertIn(link, self.links.search([("is_current", "=", True)]))
        link.active = False
        self.assertFalse(link.is_current)
        self.assertEqual(self.people[0].personal_crm_relationship_count, 0)

    def test_ended_future_and_archived(self):
        today = fields.Date.context_today(self.links)
        ended = self.link(date_end=today - timedelta(days=1))
        future = self.link(
            first=self.people[0],
            second=self.people[2],
            date_start=today + timedelta(days=1),
        )
        self.assertFalse(ended.is_current)
        self.assertFalse(future.is_current)
        self.assertEqual(self.people[0].personal_crm_relationship_count, 0)
        self.assertIn(ended, self.links.search([("is_current", "=", False)]))
        ended.active = False
        self.assertIn(
            ended,
            self.links.with_context(active_test=False).search([("active", "=", False)]),
        )

    def test_archive_allows_replacement_but_not_overlapping_reactivation(self):
        link = self.link()
        link.active = False
        self.link()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            link.active = True

    def test_searches_from_both_endpoints_and_contacts(self):
        link = self.link()
        for person in self.people[:2]:
            self.assertIn(link, self.links.search([("any_partner_id", "=", person.id)]))
        reverse = self.links.with_context(current_partner_id=self.people[1].id)
        self.assertIn(
            link, reverse.search([("other_partner_id", "=", self.people[0].id)])
        )
        partners = self.env["res.partner"].with_user(self.user)
        self.assertIn(
            self.people[0],
            partners.search(
                [
                    (
                        "personal_crm_search_relationship_partner_id",
                        "=",
                        self.people[1].id,
                    )
                ]
            ),
        )
        self.assertTrue(
            self.people[:2]
            <= partners.search(
                [("personal_crm_search_relationship_type_id", "=", self.parent.id)]
            )
        )
        self.assertNotIn(
            self.people[0],
            partners.search(
                [("personal_crm_search_relationship_type_id", "!=", self.parent.id)]
            ),
        )

    def test_date_and_tag_searches(self):
        category = self.env["res.partner.category"].create({"name": "Search tag"})
        self.people[1].category_id = category
        self.link(date_start="2020-01-01", date_end="2020-12-31")
        partners = self.env["res.partner"].with_user(self.user)
        self.assertIn(
            self.people[0],
            partners.search(
                [("personal_crm_search_relationship_date", "=", "2020-06-01")]
            ),
        )
        self.assertNotIn(
            self.people[0],
            partners.search(
                [("personal_crm_search_relationship_date", "=", "2021-06-01")]
            ),
        )
        self.assertIn(
            self.people[0],
            partners.search(
                [("personal_crm_search_relationship_category_id", "=", category.id)]
            ),
        )

    def test_custom_type_gender_labels_and_symmetric_edit(self):
        kind = self.kinds.create(
            {
                "name": "Custom",
                "is_symmetric": True,
                "left_label": "Relative",
                "left_label_male": "Kinsman",
                "left_label_female": "Kinswoman",
            }
        )
        link = self.link(kind)
        self.assertEqual(link.right_label, "Kinsman")
        kind.left_label_male = "Male relative"
        self.assertEqual(link.right_label, "Male relative")
        self.assertEqual(kind.right_label_male, kind.left_label_male)

    def test_rule_change_policies(self):
        for policy in ("restrict", "ignore", "end", "delete"):
            with self.subTest(policy=policy), self.cr.savepoint():
                kind = self.kinds.create(
                    {
                        "name": policy,
                        "left_label": "First",
                        "right_label": "Second",
                        "handle_invalid_onchange": policy,
                    }
                )
                link = self.link(kind, date_start="2020-01-01")
                if policy == "restrict":
                    with self.assertRaises(ValidationError), self.cr.savepoint():
                        kind.right_partner_type = "c"
                else:
                    kind.right_partner_type = "c"
                    if policy == "delete":
                        self.assertFalse(link.exists())
                    elif policy == "end":
                        self.assertEqual(link.date_end, fields.Date.context_today(link))
                    else:
                        self.assertTrue(link.exists())

    def test_delete_and_cascade(self):
        link = self.link()
        link.unlink()
        self.assertFalse(link.exists())
        link = self.link()
        self.people[1].unlink()
        self.assertFalse(link.exists())

    def test_relationship_and_gender_privacy(self):
        link = self.link()
        for user in (self.outsider, self.portal, self.env.ref("base.public_user")):
            with self.subTest(user=user.login):
                self.assertFalse(link.with_user(user).has_access("read"))
                with self.assertRaises(AccessError):
                    link.with_user(user).read(["left_label", "right_label"])
                with self.assertRaises(AccessError):
                    self.links.with_user(user).search([])
                with self.assertRaises(AccessError), self.cr.savepoint():
                    self.links.with_user(user).create(
                        {
                            "type_id": self.parent.id,
                            "left_partner_id": self.people[0].id,
                            "right_partner_id": self.people[1].id,
                        }
                    )
                with self.assertRaises(AccessError):
                    self.people[0].with_user(user).read(["personal_crm_gender"])

    def test_upgrade_clears_unsupported_sex_values(self):
        link = self.link()
        self.assertEqual(link.left_label, "Mother")
        self.env.flush_all()
        self.cr.execute(
            "UPDATE res_partner SET personal_crm_gender = %s WHERE id = %s",
            ("removed_value", self.people[0].id),
        )
        self.env["res.partner"].init()
        self.assertEqual(self.people[0].personal_crm_gender, "unknown")
        self.assertEqual(link.left_label, "Parent")
        self.assertEqual(link.right_label, "Son")

    def _relationship_note_context(self, relationship_id=False):
        arch = etree.fromstring(self.env.ref("personal_crm.relation_form").arch_db)
        context = arch.xpath("//field[@name='note_ids']")[0].get("context")
        return safe_eval(
            context,
            {
                "id": relationship_id,
                "left_partner_id": self.people[0].id,
                "right_partner_id": self.people[1].id,
            },
        )

    def test_shared_html_note_from_saved_relationship(self):
        link = self.link()
        notes = (
            self.env["personal.crm.note"]
            .with_user(self.user)
            .with_context(self._relationship_note_context(link.id))
        )
        form = Form(notes, view="personal_crm.note_form")
        form.name = "Shared relationship memory"
        form.body = "<p>A shared <strong>HTML</strong> memory.</p>"
        note = form.save()
        self.assertIn(note, link.note_ids)
        self.assertEqual(note.relationship_ids, link)
        self.assertEqual(set(note.partner_ids.ids), set(self.people[:2].ids))
        for person in self.people[:2]:
            self.assertIn(note, person.personal_crm_note_ids)
        self.assertIn("<strong>HTML</strong>", note.body)
        self.assertIn(note, notes.search([("relationship_ids", "in", link.ids)]))

    def test_shared_note_from_unsaved_relationship(self):
        form = Form(self.links, view="personal_crm.relation_form")
        form.type_id = self.parent
        form.left_partner_id = self.people[0]
        form.right_partner_id = self.people[1]
        notes = (
            self.env["personal.crm.note"]
            .with_user(self.user)
            .with_context(self._relationship_note_context(False))
        )
        defaults = notes.default_get(["relationship_ids", "partner_ids"])
        self.assertFalse(notes.new(defaults).relationship_ids)
        note_form = Form(notes, view="personal_crm.note_form")
        note_form.name = "Before saving the relationship"
        note = note_form.save()
        form.note_ids.add(note)
        link = form.save()
        self.assertEqual(note.relationship_ids, link)
        self.assertEqual(set(note.partner_ids.ids), set(self.people[:2].ids))

    def test_existing_note_reuse_and_relationship_deletion(self):
        first = self.link()
        second = self.link(second=self.people[2])
        note = (
            self.env["personal.crm.note"]
            .with_user(self.user)
            .create(
                {
                    "name": "Existing shared note",
                    "body": "<p>Keep this note.</p>",
                    "partner_ids": [Command.set(self.people.ids)],
                }
            )
        )
        (first | second).write({"note_ids": [Command.link(note.id)]})
        self.assertEqual(set(note.relationship_ids.ids), {first.id, second.id})
        first.unlink()
        self.assertTrue(note.exists())
        self.assertEqual(note.relationship_ids, second)
        self.assertEqual(set(note.partner_ids.ids), set(self.people.ids))
        note.unlink()
        self.assertFalse(second.note_ids)
