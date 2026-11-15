/** @odoo-module **/
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

const MODEL = "personal.crm.relationship";

export class AddRelationships extends Component {
    static template = "personal_crm.AddRelationships";
    static components = { Dialog };
    props = useProps();
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.s = proxy({anchor: null, types: [], typeId: false, role: "left", people: [],
            query: "", results: [], preview: [], start: "", end: "", busy: false, checking: false, error: ""});
        this.searchToken = 0;
        this.previewToken = 0;
        onWillStart(async () => {
            this.s.types = await this.orm.searchRead("personal.crm.relationship.type", [],
                ["name", "left_label", "right_label", "is_symmetric"], {limit: 1000});
            if (this.props.anchorId) {
                const [anchor] = await this.orm.read("res.partner", [this.props.anchorId], ["name"]);
                this.s.anchor = anchor;
            }
            if (this.props.otherId) {
                const [other] = await this.orm.read("res.partner", [this.props.otherId], ["name"]);
                if (other) this.s.people = [other];
            }
        });
    }
    get type() { return this.s.types.find(type => type.id === Number(this.s.typeId)); }
    get dialogTitle() { return _t("Add relationships"); }
    get contactLabel() { return _t("Contact"); }
    get addContactsLabel() { return _t("Add contacts"); }
    get findContactLabel() { return _t("Find a contact"); }
    get addButtonLabel() {
        return this.s.people.length === 1
            ? _t("Add %s relationship", this.s.people.length)
            : _t("Add %s relationships", this.s.people.length);
    }
    get selectedIds() { return this.s.people.map(person => person.id); }
    get valid() { return this.s.anchor && this.type && this.s.people.length && !this.s.checking && this.s.preview.length === this.s.people.length && !this.s.preview.some(row => row.error) && !this.s.busy && (!this.s.start || !this.s.end || this.s.start <= this.s.end); }
    async search(event) {
        this.s.query = event.target.value;
        const token = ++this.searchToken;
        if (this.s.query.trim().length < 2) { this.s.results = []; return; }
        try {
            const rows = await this.orm.searchRead("res.partner", [["name", "ilike", this.s.query.trim()], ["personal_crm_contact", "=", true]], ["name"], {limit: 20});
            if (token === this.searchToken) this.s.results = rows.filter(row => row.id !== this.s.anchor?.id && !this.selectedIds.includes(row.id));
        } catch (error) { if (token === this.searchToken) this.s.error = error.data?.message || error.message; }
    }
    async chooseAnchor(person) {
        this.s.anchor = person; this.s.query = ""; this.s.results = [];
        this.s.people = this.s.people.filter(row => row.id !== person.id);
        await this.preview();
    }
    async add(person) {
        if (!this.s.anchor) { await this.chooseAnchor(person); return; }
        if (!this.selectedIds.includes(person.id)) this.s.people.push(person);
        this.s.query = ""; this.s.results = [];
        await this.preview();
    }
    async remove(id) { this.s.people = this.s.people.filter(person => person.id !== id); await this.preview(); }
    async changeType(event) { this.s.typeId = Number(event.target.value) || false; await this.preview(); }
    async changeRole(event) { this.s.role = event.target.value; await this.preview(); }
    async preview() {
        const token = ++this.previewToken;
        this.s.preview = [];
        this.s.checking = false;
        if (!this.s.anchor || !this.type || !this.s.people.length) return;
        this.s.checking = true;
        try {
            const rows = await this.orm.call(MODEL, "batch_preview", [this.s.anchor.id, this.type.id, this.selectedIds, this.s.role, this.s.start || false, this.s.end || false]);
            if (token === this.previewToken) this.s.preview = rows;
        } catch (error) { if (token === this.previewToken) this.s.error = error.data?.message || error.message; }
        finally { if (token === this.previewToken) this.s.checking = false; }
    }
    row(id) { return this.s.preview.find(row => row.id === id) || {}; }
    async save() {
        if (!this.valid) return;
        this.s.busy = true; this.s.error = "";
        try {
            const ids = await this.orm.call(MODEL, "add_batch", [this.s.anchor.id, this.type.id, this.selectedIds, this.s.role, this.s.start || false, this.s.end || false]);
            this.notification.add(ids.length === 1 ? _t("%s relationship added.", ids.length) : _t("%s relationships added.", ids.length), {type: "success"});
            if (this.props.onSaved) {
                try { await this.props.onSaved(ids); }
                catch (error) { this.notification.add(_t("Relationships were saved, but the view could not refresh."), {type: "warning"}); }
            }
            this.close();
        } catch (error) { this.s.error = error.data?.message || error.message || _t("Relationships could not be saved."); }
        finally { this.s.busy = false; }
    }
    close() { if (this.props.close) this.props.close(); else if (this.props.onClose) this.props.onClose(); }
}

export class AddRelationshipsAction extends Component {
    static template = "personal_crm.AddRelationshipsAction";
    static components = { AddRelationships };
    props = useProps();
    setup() { this.action = useService("action"); }
    close() { this.action.doAction("personal_crm.action_relations", {stackPosition: "replacePreviousAction"}); }
}

registry.category("actions").add("personal_crm.relationship_add", AddRelationshipsAction);
