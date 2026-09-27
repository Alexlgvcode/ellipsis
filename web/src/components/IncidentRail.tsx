import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { clock } from "../lib/format";
import {
  STATUS_LABEL, counts, decisionLabel, elapsed, filterIncidents, sortIncidents,
  type FirstSeen, type Incident, type IncidentStatus, type RailFilter, type RailSort,
} from "../lib/incidents";

interface Props {
  incidents: Incident[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filter: RailFilter;
  onFilter: (f: RailFilter) => void;
  sort: RailSort;
  onSort: (s: RailSort) => void;
  collapsed: boolean;
  onCollapse: (c: boolean) => void;
  seen: FirstSeen;
  now: number;
}

const GROUP_ORDER: IncidentStatus[] = ["critical", "confirmed", "needs_review", "resolved"];

export function IncidentRail(p: Props) {
  const c = counts(p.incidents);
  const top = sortIncidents(p.incidents, "severity")[0];

  if (p.collapsed) {
    return (
      <aside id="incidents" tabIndex={-1} className="rail collapsed" aria-label="Active incidents">
        <div className="rail-hd">
          <button className="icon-btn" onClick={() => p.onCollapse(false)} aria-label="Expand incident list">
            <ChevronsRight size={16} />
          </button>
          <div className="rail-mini">
            <span aria-label={`${c.open} active incidents`}>{c.open}</span>
            {top && top.status !== "resolved" && <span className={`sev sev-${top.status}`} title={STATUS_LABEL[top.status]} />}
          </div>
        </div>
      </aside>
    );
  }

  const list = sortIncidents(filterIncidents(p.incidents, p.filter), p.sort);
  const groups = p.sort === "severity"
    ? GROUP_ORDER.map((s) => [s, list.filter((i) => i.status === s)] as const).filter(([, l]) => l.length)
    : [[null, list] as const];

  return (
    <aside id="incidents" tabIndex={-1} className="rail" aria-label="Active incidents">
      <div className="rail-hd">
        <div className="rail-title">
          <span>Active incidents</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span className="count">{c.open}</span>
            <button className="icon-btn" onClick={() => p.onCollapse(true)} aria-label="Collapse incident list">
              <ChevronsLeft size={15} />
            </button>
          </span>
        </div>
        <div className="rail-tools">
          <div className="filters" role="group" aria-label="Filter incidents">
            {([["critical", "Critical", c.critical], ["review", "Review", c.review], ["all", "All", c.all]] as const).map(([k, label, n]) => (
              <button key={k} aria-pressed={p.filter === k} onClick={() => p.onFilter(k)}>
                {label}<span className="n">{n}</span>
              </button>
            ))}
          </div>
          <div className="sort">
            Sort:<button onClick={() => p.onSort(p.sort === "severity" ? "newest" : "severity")}
              aria-label={`Sort by ${p.sort === "severity" ? "newest" : "severity"}`}>
              {p.sort === "severity" ? "Severity" : "Newest"}
            </button>
          </div>
        </div>
      </div>

      {list.length === 0 ? (
        <div className="empty">
          {p.incidents.length === 0 || p.filter === "all"
            ? <><h2>No active incidents</h2><p>Traffic conditions are normal in this area.</p></>
            : <><h2>Nothing in this filter</h2><p>Switch to All to see every incident.</p></>}
        </div>
      ) : (
        <ul className="rail-list">
          {groups.map(([status, items]) => (
            <li key={status ?? "all"}>
              {status && <div className="group-hd">{STATUS_LABEL[status]} <span className="mono">{items.length}</span></div>}
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {items.map((i) => {
                  const tag = i.decision ? decisionLabel(i.decision, i.response.state !== "none") : STATUS_LABEL[i.status];
                  return (
                  <li key={i.id}>
                    <button className={`row sev-${i.status}${i.status === "resolved" ? " resolved" : ""}`}
                      aria-current={p.selectedId === i.id} onClick={() => p.onSelect(i.id)}
                      aria-label={`${i.location}, ${i.typeLabel}, ${tag}, ${clock(elapsed(i, p.seen, p.now))} elapsed`}>
                      <span className="sev" aria-hidden="true" />
                      <span>
                        <div className="loc">{i.location}</div>
                        <div className="type">{i.typeLabel}</div>
                        <div className="time">{clock(elapsed(i, p.seen, p.now))}</div>
                      </span>
                      <span className={`status${i.decision ? ` decided ${i.decision}` : ""}`}>{tag}</span>
                    </button>
                  </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
