/** @odoo-module **/
// JSON-only exploration snapshots: never retain ORM records or stale graph data.
export const copy = (value) => JSON.parse(JSON.stringify(value));
export function fresh(focal, depth = 1, types) {
    return { focal, depth, ...(types === undefined ? {} : {types}), expanded: [], collapsed: [],
        paths: {}, revealed: [], scope: "bounded", selected: null, individual: [], positions: {},
        viewport: { x: 0, y: 0, zoom: 1 } };
}
export function groups(edges, individual = []) {
    const pairs = new Map();
    for (const edge of edges) {
        const key = [edge.left, edge.right].sort((a,b) => a-b).join(":");
        if (!pairs.has(key)) pairs.set(key, []);
        pairs.get(key).push(edge);
    }
    return [...pairs].flatMap(([key, records]) => individual.includes(key)
        ? records.map((record, index) => ({key: `${key}:${record.id}`, pair: key, records: [record], index, total: records.length}))
        : [{key, pair: key, records, index: 0, total: 1}]);
}
export function positionNodes(nodes, edges, focal, previous = {}) {
    const positions = copy(previous);
    const adjacency = new Map(nodes.map(n => [n.id, []]));
    for (const e of edges) {
        adjacency.get(e.left)?.push(e.right);
        adjacency.get(e.right)?.push(e.left);
    }
    const distances = new Map([[focal, 0]]), queue = [focal];
    for (let i=0; i<queue.length; i++) {
        const id = queue[i];
        for (const next of adjacency.get(id) || []) if (!distances.has(next)) {
            distances.set(next, distances.get(id)+1); queue.push(next);
        }
    }
    positions[focal] ||= {x: 0, y: 0};
    const parent = new Map();
    for (const id of queue) for (const child of adjacency.get(id) || []) {
        if (distances.get(child) === distances.get(id)+1 && !parent.has(child)) parent.set(child,id);
    }
    const children = new Map(nodes.map(n => [n.id, []]));
    for (const [child,id] of parent) children.get(id).push(child);
    const occupied = nodes.filter(n => positions[n.id]).map(n => positions[n.id]);
    const root = positions[focal];
    for (const id of queue) {
        const siblings = children.get(id) || [], origin = positions[id];
        const direction = id === focal ? -Math.PI/2 : Math.atan2(origin.y-root.y,origin.x-root.x);
        siblings.forEach((child,index) => {
            if (positions[child]) return;
            let angle = direction + (id === focal ? 2*Math.PI*index/siblings.length : (index-(siblings.length-1)/2)*Math.min(.65,2/siblings.length));
            let point;
            for (let attempt=0;attempt<100;attempt++) {
                const radius=210+Math.floor(attempt/20)*100;
                point={x:origin.x+Math.cos(angle)*radius,y:origin.y+Math.sin(angle)*radius};
                if(occupied.every(p=>Math.hypot(p.x-point.x,p.y-point.y)>125))break;
                angle+=.23;
            }
            positions[child]=point;occupied.push(point);
        });
    }
    return positions;
}
export function connectionPath(group, positions) {
    const e = group.records[0], a = positions[e.left], b = positions[e.right];
    if (!a || !b) return {path: "", x: 0, y: 0};
    if (e.left === e.right) {
        const r = 65 + group.index * 20;
        return {path: `M ${a.x-22} ${a.y-20} C ${a.x-r*2} ${a.y-r*2}, ${a.x+r*2} ${a.y-r*2}, ${a.x+22} ${a.y-20}`, x: a.x, y: a.y-r*1.5};
    }
    const offset = (group.index-(group.total-1)/2)*55;
    const dx = b.x-a.x, dy = b.y-a.y, len = Math.hypot(dx,dy) || 1;
    const x = (a.x+b.x)/2-dy/len*offset, y = (a.y+b.y)/2+dx/len*offset;
    return {path: `M ${a.x} ${a.y} Q ${x} ${y} ${b.x} ${b.y}`, x, y};
}
