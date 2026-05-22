import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Building2, ChevronDown, ChevronRight, Search, Users2 } from "lucide-react";
import { Input } from "@/components/ui/input";

const ROLE_BADGE = {
  super_admin: "bg-slate-900 text-white",
  hr: "bg-blue-50 text-blue-700 border border-blue-200",
  manager: "bg-fuchsia-50 text-fuchsia-700 border border-fuchsia-200",
  employee: "bg-slate-100 text-slate-600 border border-slate-200",
};

function buildTree(employees) {
  const byId = new Map(employees.map((e) => [e.id, { ...e, children: [] }]));
  const roots = [];
  byId.forEach((node) => {
    const parent = node.manager_id ? byId.get(node.manager_id) : null;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  const rolePriority = { super_admin: 0, hr: 1, manager: 2, employee: 3 };
  const sortRec = (nodes) => {
    nodes.sort((a, b) => {
      const ra = rolePriority[a.role] ?? 4;
      const rb = rolePriority[b.role] ?? 4;
      if (ra !== rb) return ra - rb;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach((n) => sortRec(n.children));
  };
  sortRec(roots);
  return roots;
}

// Flatten the tree into a list with depth + ancestor-open state, respecting collapsed nodes.
function flatten(roots, expanded) {
  const out = [];
  const stack = roots.map((r) => ({ node: r, depth: 0 }));
  // We need to push depth-first while preserving order, so iterate manually.
  const walk = (nodes, depth) => {
    for (const n of nodes) {
      out.push({ node: n, depth, hasChildren: n.children.length > 0, isOpen: expanded.has(n.id) });
      if (n.children.length > 0 && expanded.has(n.id)) {
        walk(n.children, depth + 1);
      }
    }
  };
  walk(roots, 0);
  // suppress unused
  void stack;
  return out;
}

export default function OrgChart() {
  const [employees, setEmployees] = useState([]);
  const [expanded, setExpanded] = useState(new Set());
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.get("/employees").then((r) => {
      setEmployees(r.data);
      setExpanded(new Set(r.data.map((e) => e.id)));
    });
  }, []);

  const tree = useMemo(() => buildTree(employees), [employees]);
  const rows = useMemo(() => flatten(tree, expanded), [tree, expanded]);

  const total = employees.length;
  const managers = employees.filter((e) => ["manager", "hr", "super_admin"].includes(e.role)).length;

  const toggle = (id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const expandAll = () => setExpanded(new Set(employees.map((e) => e.id)));
  const collapseAll = () => setExpanded(new Set());

  const q = query.toLowerCase();
  const matches = (n) =>
    !q ||
    n.name.toLowerCase().includes(q) ||
    (n.designation || "").toLowerCase().includes(q) ||
    (n.department || "").toLowerCase().includes(q);

  return (
    <div className="p-6 space-y-5 animate-fade-up" data-testid="org-chart">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-slate-900">Org chart</h1>
          <p className="text-sm text-slate-500 mt-1">{total} people · {managers} leaders · hierarchy view</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" strokeWidth={1.5} />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a person…"
              className="pl-9 h-10 w-56 rounded-lg border-slate-200"
              data-testid="org-search"
            />
          </div>
          <button onClick={expandAll} className="text-xs font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50" data-testid="org-expand-all">Expand all</button>
          <button onClick={collapseAll} className="text-xs font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50" data-testid="org-collapse-all">Collapse all</button>
        </div>
      </div>

      <div className="surface p-4 sm:p-6">
        {rows.length === 0 ? (
          <div className="py-16 text-center text-slate-400">
            <Building2 className="h-8 w-8 mx-auto opacity-40" strokeWidth={1.5} />
            <p className="text-sm mt-3">No employees yet.</p>
          </div>
        ) : (
          <div className="space-y-2" data-testid="org-tree">
            {rows.map(({ node, depth, hasChildren, isOpen }) => {
              const m = matches(node);
              return (
                <div
                  key={node.id}
                  className={`relative flex items-center gap-3 rounded-xl border px-4 py-3 transition-colors ${
                    m ? "border-slate-200 bg-white hover:border-slate-300" : "border-slate-100 bg-slate-50 opacity-60"
                  }`}
                  style={{ marginLeft: depth * 24 }}
                  data-testid={`org-node-${node.id}`}
                >
                  {/* depth guide lines */}
                  {depth > 0 && (
                    <span
                      aria-hidden
                      className="absolute top-1/2 h-px bg-slate-200"
                      style={{ left: -12, width: 12 }}
                    />
                  )}
                  {hasChildren ? (
                    <button
                      onClick={() => toggle(node.id)}
                      className="h-6 w-6 grid place-items-center rounded-md hover:bg-slate-100 text-slate-500 shrink-0"
                      aria-label={isOpen ? "Collapse" : "Expand"}
                      data-testid={`org-toggle-${node.id}`}
                    >
                      {isOpen ? <ChevronDown className="h-4 w-4" strokeWidth={1.5} /> : <ChevronRight className="h-4 w-4" strokeWidth={1.5} />}
                    </button>
                  ) : (
                    <span className="h-6 w-6 shrink-0" />
                  )}
                  <Avatar className="h-10 w-10 ring-2 ring-white shrink-0">
                    <AvatarImage src={node.avatar_url} alt={node.name} />
                    <AvatarFallback className="text-xs bg-slate-100 text-slate-700">
                      {node.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}
                    </AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900 truncate">{node.name}</span>
                      <span className={`text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded-md font-semibold ${ROLE_BADGE[node.role] || ROLE_BADGE.employee}`}>
                        {node.role === "super_admin" ? "Admin" : node.role}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500 truncate">{node.designation} · {node.department}</div>
                  </div>
                  {hasChildren && (
                    <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500 shrink-0">
                      <Users2 className="h-3 w-3" strokeWidth={1.5} />
                      {node.children.length} {node.children.length === 1 ? "report" : "reports"}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
