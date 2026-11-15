/** @odoo-module **/
import { Component, proxy, signal, useProps, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { View } from "@web/views/view";
import { useSetupAction } from "@web/search/action_hook";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { today } from "@web/core/l10n/dates";
import { copy, fresh, groups, positionNodes, connectionPath } from "./state";
import { AddRelationships } from "../relationship_add";

const inlineJourneys = new Map();
const MODEL = "personal.crm.relationship";

export class EndRelationshipDialog extends Component {
    static template = "personal_crm.EndRelationshipDialog";
    static components = { Dialog };
    props = useProps();
    get title() { return _t("End relationship"); }
    setup() { this.s = proxy({date: this.props.initialDate, error: "", busy: false}); }
    async save() {
        if (!this.s.date) { this.s.error = _t("Choose an end date."); return; }
        this.s.busy = true;
        try { await this.props.save(this.s.date); this.props.close(); }
        catch (error) { this.s.error = error.data?.message || error.message; }
        finally { this.s.busy = false; }
    }
}

export class RelationshipNetwork extends Component {
    static template = "personal_crm.Network";
    static components = { View };
    props = useProps();
    setup() {
        this.orm = useService("orm"); this.action = useService("action");
        this.dialog = useService("dialog"); this.notification = useService("notification");
        this.canvas = signal.ref();
        this.original = this.props.partnerId;
        const restored = this.props.initial || (this.props.embedded && inlineJourneys.get(this.original));
        this.s = proxy({ journey: restored ? copy(restored) : { current: fresh(this.original, this.props.embedded ? 1 : 2), back: [], forward: [] },
            graph: {nodes: [], edges: [], types: [], complete: false}, busy: false, error: "", query: "", results: [], editor: null });
        this.request = 0; this.searchRequest = 0; this.pointers = new Map();
        if (!this.props.embedded) useSetupAction({getLocalState: () => ({networkJourney: copy(this.s.journey)})});
        onWillStart(async () => {
            const loaded = await this.load(copy(this.current));
            if (loaded && !restored) this.fit();
            if (this.props.startFull) await this.full();
        });
        onWillUnmount(() => {
            this.request++; this.searchRequest++;
            if (this.props.embedded) inlineJourneys.set(this.original, copy(this.s.journey));
        });
    }
    get current() { return this.s.journey.current; }
    get nodes() { return this.s.graph.nodes; }
    kindLabel(node) { return node.company ? _t("Company / authority") : _t("Person"); }
    stateLabel(node) {
        return node.state === "expanded" ? _t("Expanded") : node.state === "collapsed" ? _t("Collapsed") : _t("Unexplored");
    }
    nodeAriaLabel(node) {
        const details = [node.name, this.kindLabel(node), this.stateLabel(node)];
        if (node.id === this.current.focal) details.push(_t("Focal contact"));
        return details.join(", ");
    }
    connectionAriaLabel(connection) {
        const edge = connection.records[0];
        return connection.records.length > 1
            ? _t("%s relationships between %s and %s", connection.records.length, this.nodeName(edge.left), this.nodeName(edge.right))
            : _t("%s as %s to %s as %s", this.nodeName(edge.left), edge.leftRole, this.nodeName(edge.right), edge.rightRole);
    }
    viewContactDetailsLabel(node) { return _t("View contact details for %s", node.name); }
    addRelationshipFromLabel(node) { return _t("Add relationship from %s", node.name); }
    relationshipCountLabel(count) { return count === 1 ? _t("1 relationship") : _t("%s relationships", count); }
    get regroupLabel() { return this.current.individual.includes(this.selectedGroup.pair) ? _t("Regroup connections") : _t("Reveal individual connections"); }
    get openStartLabel() { return _t("No start date"); }
    get openEndLabel() { return _t("No end date"); }
    get currentLabel() { return _t("Current"); }
    get selectedTypesLabel() { return _t("Relationship types (%s selected)", this.current.types?.length || 0); }
    get recordCountLabel() { return _t("%s contacts · %s relationship records", this.nodes.length, this.s.graph.edges.length); }
    get focalName() { return this.nodes.find(n => n.id === this.current.focal)?.name || _t("Contact"); }
    get visibleResults() { const q = this.s.query.toLocaleLowerCase(); return q ? this.nodes.filter(n => n.name.toLocaleLowerCase().includes(q)).slice(0,20) : []; }
    get otherResults() { return this.s.results.filter(n => !this.nodes.some(v => v.id === n.id)); }
    get connections() {
        return groups(this.s.graph.edges, this.current.individual).map(g => ({...g, ...connectionPath(g, this.current.positions)}));
    }
    get selectedNode() { return this.current.selected?.node && this.nodes.find(n => n.id === this.current.selected.node); }
    get selectedGroup() { return this.current.selected?.group ? this.connections.find(g => g.key === this.current.selected.group) : undefined; }
    get selectedRecords() {
        const id = this.current.selected?.record;
        return id ? this.s.graph.edges.filter(e => e.id === id) : this.selectedGroup?.records || [];
    }
    get transform() {
        const v = this.current.viewport;
        return `translate(${500+v.x} ${300+v.y}) scale(${v.zoom})`;
    }
    async confirm(body) {
        return new Promise(resolve => this.dialog.add(ConfirmationDialog, {title: _t("Relationship network"), body, confirmLabel: _t("Continue"), cancelLabel: _t("Cancel"), confirm: () => resolve(true), cancel: () => resolve(false), dismiss: () => resolve(false)}));
    }
    async load(candidate, history = null, allowLarge = false) {
        const token = ++this.request;
        this.s.busy = true; this.s.error = "";
        try {
            const graph = await this.orm.call(MODEL, "network_read", [candidate, allowLarge]);
            if (token !== this.request) return false;
            if (graph.warning) {
                const proceed = await this.confirm(graph.warning);
                if (token !== this.request) return false;
                if (proceed) return this.load(candidate, history, true);
                return false;
            }
            candidate.types = graph.selectedTypes;
            candidate.expanded = graph.expanded; candidate.collapsed = graph.collapsed; candidate.paths = graph.paths;
            candidate.positions = positionNodes(graph.nodes, graph.edges, candidate.focal, candidate.positions);
            if (candidate.selected?.node && !graph.nodes.some(n => n.id === candidate.selected.node) || candidate.selected?.record && !graph.edges.some(e => e.id === candidate.selected.record)) candidate.selected = null;
            if (candidate.selected?.group && !groups(graph.edges, candidate.individual).some(g => g.key === candidate.selected.group)) candidate.selected = null;
            if (history === "push") {
                this.s.journey.back.push(copy(this.current)); this.s.journey.forward = [];
            } else if (history === "back") {
                this.s.journey.forward.push(copy(this.current)); this.s.journey.back.pop();
            } else if (history === "forward") {
                this.s.journey.back.push(copy(this.current)); this.s.journey.forward.pop();
            }
            this.s.journey.current = candidate; this.s.graph = graph;
            return true;
        } catch (error) {
            if (token === this.request) this.s.error = error.data?.message || error.message || _t("The network could not be loaded.");
            return false;
        } finally { if (token === this.request) this.s.busy = false; }
    }
    cancel() { this.request++; this.s.busy = false; this.s.error = _t("Expansion cancelled. The preceding network is unchanged."); }
    async expand(id) {
        if (this.nodes.find(n => n.id === id)?.state === "expanded") { this.current.selected = {node: id}; return; }
        const next = copy(this.current); next.selected = {node: id}; next.expanded = [...new Set([...next.expanded,id])];
        next.collapsed = next.collapsed.filter(n => n !== id);
        await this.load(next);
    }
    collapse(id) {
        const next = copy(this.current);
        next.collapsed = [...new Set([...next.collapsed,id])]; next.expanded = next.expanded.filter(n => n !== id);
        delete next.paths[id]; this.load(next);
    }
    async focus(id) {
        if (await this.load(fresh(id, this.props.embedded ? 1 : this.current.depth, this.current.types), "push")) this.fit();
    }
    back() { const s = this.s.journey.back.at(-1); if (s) this.load(copy(s), "back"); }
    forward() { const s = this.s.journey.forward.at(-1); if (s) this.load(copy(s), "forward"); }
    reset() { return this.load(fresh(this.current.focal, this.current.depth, this.current.types)); }
    depth(event) { const next = copy(this.current); next.depth = Number(event.target.value); next.scope = "bounded"; this.load(next); }
    toggleType(id) {
        const next = copy(this.current);
        next.types = next.types.includes(id) ? next.types.filter(n => n!==id) : [...next.types,id];
        this.load(next);
    }
    allTypes(all) { const next = copy(this.current); next.types = all ? this.s.graph.types.map(k => k.id) : []; this.load(next); }
    async full() {
        if (this.props.embedded) return this.continue(true);
        const next = copy(this.current); next.scope = "full"; next.collapsed = [];
        if (await this.load(next, "push")) this.fit();
    }
    continue(full = false) {
        inlineJourneys.set(this.original, copy(this.s.journey));
        this.action.doAction({type: "ir.actions.client", tag: "personal_crm.network", name: _t("Relationship network"),
            params: {partnerId: this.original, initial: copy(this.s.journey), full}});
    }
    center(id = this.current.focal) {
        const p = this.current.positions[id]; if (!p) return;
        const v = this.current.viewport; v.x = -p.x*v.zoom; v.y = -p.y*v.zoom;
    }
    fit() {
        if (!this.nodes.length) return;
        const pts = this.nodes.map(n => this.current.positions[n.id]);
        const minX = Math.min(...pts.map(p=>p.x))-90, maxX = Math.max(...pts.map(p=>p.x))+90;
        const minY = Math.min(...pts.map(p=>p.y))-70, maxY = Math.max(...pts.map(p=>p.y))+70;
        const zoom = Math.min(1.4, 900/(maxX-minX), 510/(maxY-minY));
        this.current.viewport = {zoom, x: -(minX+maxX)/2*zoom, y: -(minY+maxY)/2*zoom};
    }
    zoom(factor) { this.current.viewport.zoom = Math.max(0.12,Math.min(3,this.current.viewport.zoom*factor)); }
    point(event) {
        return new DOMPoint(event.clientX,event.clientY).matrixTransform(this.canvas().getScreenCTM().inverse());
    }
    pointerDown(event) {
        if (event.button !== 0 || event.target.closest("[data-node], [data-connection]")) return;
        event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId);
        this.pointers.set(event.pointerId, this.point(event));
        this.pan = {points: [...this.pointers.values()], viewport: copy(this.current.viewport)};
    }
    pointerMove(event) {
        if (!this.pointers.has(event.pointerId)) return;
        this.pointers.set(event.pointerId, this.point(event));
        const points = [...this.pointers.values()], start = this.pan.points;
        const avg = ps => ({x: ps.reduce((v,p)=>v+p.x,0)/ps.length,y: ps.reduce((v,p)=>v+p.y,0)/ps.length});
        const a=avg(start), b=avg(points), old=this.pan.viewport;
        let zoom=old.zoom;
        if (points.length===2 && start.length===2) zoom=Math.max(.12,Math.min(3,old.zoom*Math.hypot(points[1].x-points[0].x,points[1].y-points[0].y)/Math.max(1,Math.hypot(start[1].x-start[0].x,start[1].y-start[0].y))));
        this.current.viewport={zoom,x:b.x-500-(a.x-500-old.x)*zoom/old.zoom,y:b.y-300-(a.y-300-old.y)*zoom/old.zoom};
    }
    pointerUp(event) {
        this.pointers.delete(event.pointerId);
        if (this.pointers.size) this.pan={points:[...this.pointers.values()],viewport:copy(this.current.viewport)};
    }
    wheel(event) {
        // Embedded graphs keep ordinary document scrolling; Ctrl+wheel is explicit zoom.
        if (this.props.embedded && !event.ctrlKey) return;
        event.preventDefault(); this.zoom(event.deltaY>0?.9:1.1);
    }
    async search(event) {
        this.s.query = event.target.value;
        const token=++this.searchRequest;
        if (this.s.query.trim().length<2) { this.s.results=[]; return; }
        try { const rows=await this.orm.call(MODEL,"network_search",[this.s.query]); if(token===this.searchRequest)this.s.results=rows; }
        catch(error) { if(token===this.searchRequest)this.s.error=error.data?.message||error.message; }
    }
    selectVisible(id) { this.current.selected={node:id}; this.center(id); }
    async openContact(id) {
        const context={personal_crm_navigation:true};
        const viewId=await this.orm.call("res.partner","get_formview_id",[[id]],{context});
        this.action.doAction({type:"ir.actions.act_window",res_model:"res.partner",res_id:id,views:[[viewId,"form"]],context});
    }
    openRecord(id) { this.dialog.add(FormViewDialog,{resModel:MODEL,resId:id,context:{form_view_ref:"personal_crm.relation_form",personal_crm_navigation:true},onRecordSaved:()=>this.load(copy(this.current))}); }
    openNote(id) { this.dialog.add(FormViewDialog,{resModel:"personal.crm.note",resId:id,context:{form_view_ref:"personal_crm.note_form"}}); }
    list(pair = null) {
        const domain = pair ? ["|","&",["left_partner_id","=",pair[0]],["right_partner_id","=",pair[1]],"&",["left_partner_id","=",pair[1]],["right_partner_id","=",pair[0]]] : ["|",["left_partner_id","=",this.current.focal],["right_partner_id","=",this.current.focal]];
        this.action.doAction({type:"ir.actions.act_window",name:_t("Stored relationships"),res_model:MODEL,views:[[false,"list"],[false,"form"]],domain,context:{personal_crm_navigation:true,active_test:false}});
    }
    ungroup(pair) {
        const next=this.current.individual;
        this.current.individual=next.includes(pair)?next.filter(k=>k!==pair):[...next,pair];
        this.current.selected=null;
    }
    dragStart(event,id) { event.dataTransfer.setData("application/x-personal-crm-contact",String(id)); event.dataTransfer.effectAllowed="link"; }
    drop(event,id) { event.preventDefault(); const from=Number(event.dataTransfer.getData("application/x-personal-crm-contact")); if(from)this.add(from,id); }
    add(anchorId = this.current.focal, otherId = null) {
        this.dialog.add(AddRelationships, {anchorId, otherId, onSaved: ids => this.savedBatch(ids)});
    }
    async savedBatch(ids) {
        const next = copy(this.current);
        next.selected = {record: ids.at(-1)};
        const records = await this.orm.read(MODEL, ids, ["left_partner_id", "right_partner_id", "type_id", "is_current"]);
        for (const record of records) {
            if (record.is_current && next.types.includes(record.type_id[0]) &&
                [record.left_partner_id[0], record.right_partner_id[0]].some(id => this.nodes.some(node => node.id === id))) {
                next.revealed = [...new Set([...(next.revealed || []), record.id])];
            }
        }
        this.s.graph.complete = false;
        await this.load(next, null, true);
    }
    editorProps(id) {
        return {type:"form",resModel:MODEL,resId:id||false,display:{controlPanel:{}},buttonTemplate:"personal_crm.NetworkEditorButtons",
            context:{form_view_ref:"personal_crm.relation_form",personal_crm_navigation:true},
            saveRecord:async(record)=>{const saved=await record.save({reload:false}); if(saved)await this.saved(record.resId,!id); return saved;},
            discardRecord:()=>{this.s.editor=null;}};
    }
    edit(edge) {
        const id=edge?.id;
        const props=this.editorProps(id);
        if(this.props.embedded) {
            this.dialog.add(FormViewDialog,{resModel:MODEL,resId:id||false,title:id?_t("Edit relationship"):_t("Add relationship"),context:props.context,canExpand:false,
                onRecordSaved:record=>this.saved(record.resId,!id)});
        } else this.s.editor={key:`${id||"new"}:${Date.now()}`,props};
    }
    async saved(id,isNew) {
        this.s.editor=null;
        const next=copy(this.current);
        // Read only this saved record, through ORM security. Reveal the new immediate link.
        const [record]=await this.orm.read(MODEL,[id],["left_partner_id","right_partner_id","type_id","is_current"]);
        if(isNew && record.is_current && next.types.includes(record.type_id[0])) {
            if ([record.left_partner_id[0],record.right_partner_id[0]].some(id=>this.nodes.some(n=>n.id===id))) {
                next.revealed = [...new Set([...(next.revealed || []),id])];
            }
        }
        next.selected={record:id};
        this.s.graph.complete=false;
        this.s.graph.edges=this.s.graph.edges.filter(e=>e.id!==id);
        await this.load(next,null,true);
        const visible=this.s.graph.edges.some(e=>e.id===id);
        this.notification.add(visible?_t("Relationship saved."):_t("Relationship saved outside the current network."),{type:"success",buttons:visible?[]:[{name:_t("Open relationship"),onClick:()=>this.openRecord(id)},{name:_t("Focus here"),onClick:()=>this.focus(record.left_partner_id[0])}]});
        if(visible) this.current.selected={record:id};
    }
    async lifecycle(edge,operation) {
        const identity=`${this.nodeName(edge.left)} (${edge.leftRole}) → ${this.nodeName(edge.right)} (${edge.rightRole}), ${edge.name}, ${edge.start||_t("No start date")} – ${edge.end||_t("No end date")}`;
        if(operation==="delete" && !await this.confirm(_t("Delete only this relationship? %s. Shared notes will be retained.", identity)))return;
        if(operation==="end") { this.edit(edge); return; }
        try {
            if(operation==="delete")await this.orm.unlink(MODEL,[edge.id]);
            else await this.orm.write(MODEL,[edge.id],{active:operation==="restore"});
            this.s.graph.complete=false;
            this.s.graph.edges=this.s.graph.edges.filter(e=>e.id!==edge.id);
            await this.load(copy(this.current),null,true);
            this.notification.add(operation==="delete"?_t("Relationship deleted."):_t("Relationship archived."),{type:"success",buttons:operation==="delete"?[]:[{name:_t("Open stored relationship"),onClick:()=>this.openRecord(edge.id)}]});
        }catch(error){this.s.error=error.data?.message||error.message;}
    }
    selectConnection(group) { this.current.selected = {group: group.key}; }
    connectionSelected(group) { return this.current.selected?.group === group.key || group.records.some(e => e.id === this.current.selected?.record); }
    nodeSelected(id) {
        const selected=this.current.selected;
        if(!selected)return false;
        if(selected.node)return selected.node===id;
        if(selected.group)return selected.group.split(":").slice(0,2).map(Number).includes(id);
        const edge=this.s.graph.edges.find(e=>e.id===selected.record);
        return Boolean(edge && (edge.left===id || edge.right===id));
    }
    nodeKey(event,id) { if (event.target.closest(".pcrm_node_action")) return; if (["Enter"," "].includes(event.key)) { event.preventDefault(); this.expand(id); } }
    connectionKey(event,group) { if (["Enter"," "].includes(event.key)) { event.preventDefault(); this.selectConnection(group); } }
    endRelationship(edge) {
        const endToday=this.s.graph.today || today().toISODate();
        this.dialog.add(EndRelationshipDialog,{initialDate:edge.start && edge.start>endToday?edge.start:endToday,
            save:async date=>{await this.orm.write(MODEL,[edge.id],{date_end:date}); this.s.graph.complete=false; this.s.graph.edges=this.s.graph.edges.filter(e=>e.id!==edge.id); await this.load(copy(this.current),null,true);
                this.notification.add(_t("Relationship end date saved. The end date is inclusive."),{type:"success",buttons:[{name:_t("Open stored relationship"),onClick:()=>this.openRecord(edge.id)}]});}});
    }
    nodeName(id) { return this.nodes.find(n=>n.id===id)?.name||_t("Contact"); }
}

export class EmbeddedNetwork extends Component {
    static template="personal_crm.EmbeddedNetwork";
    static components={RelationshipNetwork};
    props=useProps();
}
export class NetworkAction extends Component {
    static template="personal_crm.NetworkAction";
    static components={RelationshipNetwork};
    props=useProps();
}
registry.category("view_widgets").add("personal_crm_network",{component:EmbeddedNetwork});
registry.category("actions").add("personal_crm.network",NetworkAction);
