# Relationship design

`personal_crm` stores relationships between contacts with configurable roles,
restrictions, and validity dates.

## Role and gender separation

Managed contacts have an explicit `res.partner.personal_crm_entity_type`
(person/company). `personal_crm_is_company` resolves that value for CRM contacts
and Odoo's native `is_company` for unflagged contacts. This avoids treating an
authority or company without a VAT number as a person under Odoo 20's tax-based
company heuristic. Restrictions, label selection, and navigation use this helper.

`res.partner.personal_crm_gender` (Sex in the form) is optional: female, male, or unknown.
Unknown, unset, and companies use neutral relationship labels.

`personal.crm.relationship.type` defines:

- `name`, `is_symmetric`, and `allow_self`;
- `left_label`, `left_label_male`, `left_label_female`;
- `right_label`, `right_label_male`, `right_label_female`;
- optional person/company and partner-tag restrictions per role;
- `handle_invalid_onchange`: restrict, ignore, end, or delete.

The first role of Parent/Child is Parent; the second is Child. Gender selects
Father/Mother and Son/Daughter independently. Symmetric types mirror the first
role's label vocabulary and restrictions onto the second, but label each person
using their own gender. A male/female Sibling edge therefore displays Brother
and Sister without a directed “Brother” type or a second database record.

Seed XML IDs:

```text
personal_crm.relationship_type_friend
personal_crm.relationship_type_spouse
personal_crm.relationship_type_partner
personal_crm.relationship_type_sibling
personal_crm.relationship_type_parent
personal_crm.relationship_type_grandparent
personal_crm.relationship_type_employment
```

`name_search` searches neutral/gendered role labels as well as the type name.
Gender changes affect current and historical display labels. The relationship
stores no gender snapshot and does not infer a person's gender from a label.

## Canonical edges and editor direction

`personal.crm.relationship` stores one `type_id`, `left_partner_id` (first role),
`right_partner_id` (second role), optional `date_start`/`date_end`, an independent
`active` archive flag, shared HTML `note_ids`, and normal timestamps. All three foreign keys have
indexes. Partner deletion cascades; type deletion restricts unless its configured
policy is delete.

`reverse_roles` is a transient editor option. It previews the selected contacts
in the opposite role assignments and swaps endpoints at create/write, then
resets. It is not a stored second representation. Symmetric reverse duplicates
are detected in either endpoint order; asymmetric reverse input normalizes to
the same canonical edge. Oppositely directed asymmetric edges are distinct when
they actually assign different roles.

`left_label` and `right_label` show canonical/editor roles. Context key
`current_partner_id` controls `this_partner_id`, `other_partner_id`, `this_role`,
and `other_role`, without changing stored data. For a son looking at his mother,
the smart-button list shows Son → Mother. Full display names include both people
and both roles, reducing ambiguity.

## Rules and history

- Start must be on or before end; missing bounds mean open-ended periods.
- Active edges of the same type and role assignment cannot overlap. Date bounds
  are inclusive. Separate periods are allowed. Reverse symmetric duplicates and
  duplicate inverse input are rejected.
- Archived edges do not reserve a period; unarchiving runs overlap validation.
- `is_current` means active and today's date lies within the optional bounds.
  The smart-button count counts each current relationship once, including an
  explicitly allowed self-link. Ended/future edges remain browsable.
- Endpoint changes validate tags, person/company restrictions, self-link rules,
  and contact access. Changing a partner's classification or tags revalidates
  its links, including archived links, and rejects invalid edits.
- Type restriction changes follow their configured policy. Restrict rejects;
  ignore preserves existing links; end sets today's end date for still-running
  links, removes links starting today/in the future, and keeps already-ended
  history; delete removes incompatible links. New links must always satisfy the
  current rules. Changing a type to symmetric also checks for reverse duplicates.
- Counts and UI use permission-aware ORM queries. SQL overlap checks are not a
  database exclusion constraint; no claim of cross-transaction uniqueness under
  concurrent inserts is made.

## Search and network access

Relationship search exposes either endpoint, canonical endpoints, type, current,
ended, and archived filters. Perspective endpoint searches follow the same
context as the displayed roles, including negative endpoint searches.

Partner search fields are namespaced:

```text
personal_crm_search_relationship_type_id
personal_crm_search_relationship_partner_id
personal_crm_search_relationship_category_id
personal_crm_search_relationship_date
```

The date filter takes one equality date and searches active edges valid on that
date. Other partner relationship filters include active historical/future edges;
use the date filter to narrow a result. Filters combine at the partner level.
Negative type/partner/tag filters exclude partners matching the positive filter.

The network reads relationships through the indexed endpoints and displays role
labels for each contact. Its records retain the canonical edge orientation.

## Shared HTML notes

`note_ids` points to the same `personal.crm.note` model used by contact/company
forms, using `personal_crm_relationship_note_rel`. Its inverse is
`personal.crm.note.relationship_ids`. Notes retain their existing model ACLs,
HTML sanitization, attachment protection, dates, and contact associations.
New-note defaults include valid endpoint IDs; a saved parent is also prelinked.
Unsaved parents are linked when saved. No note is deleted when an associated
relationship is deleted.
