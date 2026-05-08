import { useState, useEffect } from "react";

const API_BASE = "http://localhost:8765";

// ── Design tokens (60-30-10) ──────────────────────────────────────────────────
// 60% — background family
// 30% — surfaces, borders, structure
// 10% — orange accent
const C = {
  bgBase:    "#111111",   // 60%: page background
  bgSurface: "#1a1a1a",   // 30%: cards, header, tab bar
  bgRaised:  "#222222",   // 30%: hover, inputs
  border:    "#2e2e2e",   // 30%: borders
  borderSub: "#252525",   // 30%: hairline dividers
  accent:    "#f97316",   // 10%: orange — primary action / active state
  accentDim: "#ea6800",   // 10%: orange border variant

  // Text — all verified WCAG AA (≥4.5:1) against #111111
  hi:  "#e2e8f0",   // ~16:1  primary content
  mid: "#94a3b8",   // ~7.5:1 secondary text, paths, descriptions
  lo:  "#7d8fa1",   // ~5.5:1 labels, tertiary info

  // Status
  green:  "#4ade80",
  red:    "#f87171",
  yellow: "#fbbf24",
  cyan:   "#22d3ee",
  purple: "#a78bfa",
};

// ── Primitives ────────────────────────────────────────────────────────────────

const Toggle = ({ enabled, onChange, disabled = false }) => (
  <div
    onClick={disabled ? undefined : onChange}
    style={{
      width: 42, height: 24, borderRadius: 12,
      background: enabled ? C.accent : C.bgRaised,
      border: `1px solid ${enabled ? C.accentDim : C.border}`,
      cursor: disabled ? "not-allowed" : "pointer",
      position: "relative", transition: "all 0.15s",
      flexShrink: 0, opacity: disabled ? 0.4 : 1,
    }}
  >
    <div style={{
      width: 18, height: 18, borderRadius: "50%",
      background: enabled ? "#fff" : C.lo,
      position: "absolute", top: 2,
      left: enabled ? 20 : 2, transition: "left 0.15s",
    }} />
  </div>
);

const Badge = ({ type }) => {
  const map = { local: [C.cyan, "LOCAL"], rclone: [C.purple, "RCLONE"], webdav: [C.green, "WEBDAV"] };
  const [color, label] = map[type] || ["#6b7280", type.toUpperCase()];
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, letterSpacing: "0.1em",
      padding: "3px 9px", borderRadius: 3,
      background: color + "18", border: `1px solid ${color}44`,
      color, whiteSpace: "nowrap",
    }}>{label}</span>
  );
};

const StatusDot = ({ status }) => {
  const colors = { ready: C.green, processing: C.accent, error: C.red, disabled: C.border, offline: C.red, connecting: C.yellow };
  const c = colors[status] || C.border;
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: c, flexShrink: 0,
      boxShadow: (status === "processing" || status === "connecting") ? `0 0 6px ${c}` : "none",
      animation: (status === "processing" || status === "connecting") ? "blink 1.4s ease-in-out infinite" : "none",
    }} />
  );
};

const SectionHeader = ({ title, sub }) => (
  <div style={{ marginBottom: 22, paddingBottom: 12, borderBottom: `1px solid ${C.borderSub}`, display: "flex", alignItems: "baseline", gap: 16 }}>
    <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.16em", color: C.hi }}>{title}</span>
    {sub && <span style={{ fontSize: 12, color: C.lo, letterSpacing: "0.04em" }}>{sub}</span>}
  </div>
);

const inputSt = {
  background: C.bgRaised, border: `1px solid ${C.border}`, color: C.hi,
  padding: "9px 12px", fontFamily: "inherit", fontSize: 13,
  borderRadius: 4, outline: "none",
};

const Btn = ({ onClick, children, ghost, danger, disabled, small }) => {
  const bg     = danger ? "#7f1d1d" : ghost ? "transparent" : C.accent;
  const border = danger ? "#991b1b" : ghost ? C.border      : C.accentDim;
  const col    = danger ? C.red     : ghost ? C.mid         : "#000";
  return (
    <button onClick={disabled ? undefined : onClick} style={{
      background: bg, border: `1px solid ${border}`, color: col,
      padding: small ? "6px 14px" : "9px 18px",
      fontFamily: "inherit", fontSize: small ? 11 : 12,
      fontWeight: 600, letterSpacing: "0.08em",
      cursor: disabled ? "not-allowed" : "pointer",
      borderRadius: 4, whiteSpace: "nowrap",
      opacity: disabled ? 0.35 : 1, transition: "opacity 0.15s",
    }}>{children}</button>
  );
};

// ── Default Data ──────────────────────────────────────────────────────────────

const DEFAULT_SOURCES = [
  { id: 1, path: "D:\\Field Recordings",                     type: "local",  enabled: true  },
  { id: 2, path: "C:\\Users\\robin\\Music\\Field Recordings", type: "local",  enabled: true  },
  { id: 3, path: "G:\\My Drive\\Field recordings",            type: "rclone", enabled: true  },
  { id: 4, path: "G:\\My Drive\\To sort",                    type: "rclone", enabled: false },
];

const DEFAULT_CATEGORIES = [
  { id: "atmos",        label: "Atmosphere",   group: "Ambience",   enabled: true  },
  { id: "room",         label: "Room Tone",    group: "Ambience",   enabled: true  },
  { id: "silence",      label: "Silence",      group: "Ambience",   enabled: false },
  { id: "rain",         label: "Rain",         group: "Nature",     enabled: true  },
  { id: "wind",         label: "Wind",         group: "Nature",     enabled: true  },
  { id: "water",        label: "Water",        group: "Nature",     enabled: true  },
  { id: "birds",        label: "Birds",        group: "Nature",     enabled: true  },
  { id: "insects",      label: "Insects",      group: "Nature",     enabled: false },
  { id: "thunder",      label: "Thunder",      group: "Nature",     enabled: false },
  { id: "fire",         label: "Fire",         group: "Nature",     enabled: false },
  { id: "traffic",      label: "Traffic",      group: "Urban",      enabled: true  },
  { id: "crowd",        label: "Crowd",        group: "Urban",      enabled: true  },
  { id: "construction", label: "Construction", group: "Urban",      enabled: false },
  { id: "transport",    label: "Transport",    group: "Urban",      enabled: false },
  { id: "machinery",    label: "Machinery",    group: "Industrial", enabled: true  },
  { id: "electrical",   label: "Electrical",   group: "Industrial", enabled: false },
  { id: "hvac",         label: "HVAC",         group: "Industrial", enabled: false },
  { id: "voice",        label: "Voice",        group: "Human",      enabled: true  },
  { id: "foley",        label: "Foley",        group: "Human",      enabled: true  },
  { id: "footsteps",    label: "Footsteps",    group: "Human",      enabled: true  },
  { id: "music",        label: "Music",        group: "Music",      enabled: true  },
  { id: "tonal",        label: "Tonal / Drone",group: "Music",      enabled: false },
  { id: "rhythmic",     label: "Rhythmic",     group: "Music",      enabled: false },
];

const DEFAULT_MODELS = [
  { id: "yamnet",    name: "YAMNet",    desc: "Audio event classification · AudioSet", enabled: true,  threshold: 0.40, status: "ready"    },
  { id: "whisper",   name: "Whisper",   desc: "Speech detection & transcription",      enabled: true,  threshold: 0.50, status: "ready"    },
  { id: "audioclip", name: "AudioCLIP", desc: "Semantic audio-text embedding",         enabled: true,  threshold: 0.35, status: "ready"    },
  { id: "essentia",  name: "Essentia",  desc: "Music analysis & feature extraction",   enabled: false, threshold: 0.45, status: "disabled" },
];

const MOCK_EVENTS = [
  { ts: "14:32:01", file: "rain_forest_003.wav",        status: "enriched", ms: "2100" },
  { ts: "14:31:58", file: "city_ambience_morning.aiff", status: "enriched", ms: "3440" },
  { ts: "14:31:44", file: "footsteps_gravel_01.wav",    status: "enriched", ms: "1820" },
  { ts: "14:31:39", file: "wind_coastal_long.wav",      status: "skipped",  ms: "—"    },
  { ts: "14:30:12", file: "thunder_distant_02.wav",     status: "enriched", ms: "2910" },
  { ts: "14:29:55", file: "crowd_market_01.wav",        status: "error",    ms: "—"    },
];

// ── Sources Tab ───────────────────────────────────────────────────────────────

const SourcesTab = ({ sources, setSources, apiOnline }) => {
  const [newPath, setNewPath] = useState("");
  const [newType, setNewType] = useState("local");
  const [adding, setAdding] = useState(false);

  const apiPatch = async (path, body) => {
    if (!apiOnline) return;
    try { await fetch(`${API_BASE}${path}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); } catch {}
  };
  const apiDelete = async (path) => {
    if (!apiOnline) return;
    try { await fetch(`${API_BASE}${path}`, { method: "DELETE" }); } catch {}
  };

  const toggle = (id) => {
    const src = sources.find(s => s.id === id);
    apiPatch(`/api/sources/${id}`, { enabled: !src.enabled });
    setSources(s => s.map(x => x.id === id ? { ...x, enabled: !x.enabled } : x));
  };

  const remove = (id) => {
    apiDelete(`/api/sources/${id}`);
    setSources(s => s.filter(x => x.id !== id));
  };

  const add = async () => {
    if (!newPath.trim()) return;
    const src = { id: Date.now(), path: newPath.trim(), type: newType, enabled: true };
    if (apiOnline) {
      try {
        const res = await fetch(`${API_BASE}/api/sources`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(src) });
        const d = await res.json();
        if (d.id) src.id = d.id;
      } catch {}
    }
    setSources(s => [...s, src]);
    setNewPath(""); setAdding(false);
  };

  const active = sources.filter(s => s.enabled).length;

  return (
    <div>
      <SectionHeader title="INGEST SOURCES" sub={`${active} / ${sources.length} active`} />
      <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: 16 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.borderSub}` }}>
            {["TYPE", "PATH", "", ""].map((h, i) => (
              <th key={i} style={{ padding: "6px 12px", textAlign: "left", fontSize: 11, letterSpacing: "0.12em", color: C.lo, fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map(src => (
            <tr key={src.id} style={{ borderBottom: `1px solid ${C.borderSub}`, opacity: src.enabled ? 1 : 0.45, transition: "opacity 0.15s" }}>
              <td style={{ padding: "13px 12px", width: 100 }}><Badge type={src.type} /></td>
              <td style={{ padding: "13px 12px", fontSize: 13, color: C.mid }}>{src.path}</td>
              <td style={{ padding: "13px 12px", width: 60, textAlign: "right" }}>
                <Toggle enabled={src.enabled} onChange={() => toggle(src.id)} />
              </td>
              <td style={{ padding: "13px 12px", width: 36 }}>
                <button onClick={() => remove(src.id)}
                  style={{ background: "none", border: "none", color: C.lo, cursor: "pointer", fontSize: 20, lineHeight: 1, padding: 0, fontFamily: "inherit" }}
                  onMouseEnter={e => e.currentTarget.style.color = C.red}
                  onMouseLeave={e => e.currentTarget.style.color = C.lo}
                >×</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {adding ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={newType} onChange={e => setNewType(e.target.value)} style={{ ...inputSt, width: 110 }}>
            <option value="local">local</option>
            <option value="rclone">rclone</option>
            <option value="webdav">webdav</option>
          </select>
          <input
            value={newPath} onChange={e => setNewPath(e.target.value)}
            placeholder="D:\Path\To\Folder  or  gdrive:remote/path"
            style={{ ...inputSt, flex: 1 }}
            onKeyDown={e => e.key === "Enter" && add()}
            autoFocus
          />
          <Btn onClick={add}>ADD</Btn>
          <Btn ghost onClick={() => { setAdding(false); setNewPath(""); }}>CANCEL</Btn>
        </div>
      ) : (
        <button onClick={() => setAdding(true)}
          style={{
            width: "100%", background: "none", border: `1px dashed ${C.border}`,
            color: C.lo, padding: "12px", cursor: "pointer", fontFamily: "inherit",
            fontSize: 12, letterSpacing: "0.1em", borderRadius: 4, transition: "all 0.1s",
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = C.accent; e.currentTarget.style.color = C.accent; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.color = C.lo; }}
        >+ ADD SOURCE</button>
      )}
    </div>
  );
};

// ── Categories Tab ────────────────────────────────────────────────────────────

const CategoriesTab = ({ categories, setCategories, apiOnline }) => {
  const [addingSubcat, setAddingSubcat] = useState(null);  // group name being added to
  const [newSubcatLabel, setNewSubcatLabel] = useState("");
  const [addingGroup, setAddingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [pendingGroups, setPendingGroups] = useState([]);  // created groups with no subcats yet
  const [hoveredId, setHoveredId] = useState(null);

  const existingGroups = [...new Set(categories.map(c => c.group))];
  const allGroups = [...existingGroups, ...pendingGroups.filter(g => !existingGroups.includes(g))];
  const active = categories.filter(c => c.enabled);

  const toggle = (id) => {
    const cat = categories.find(c => c.id === id);
    if (apiOnline) {
      try { fetch(`${API_BASE}/api/categories/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: !cat.enabled }) }); } catch {}
    }
    setCategories(cs => cs.map(x => x.id === id ? { ...x, enabled: !x.enabled } : x));
  };

  const enableAll  = (group) => setCategories(cs => cs.map(x => x.group === group ? { ...x, enabled: true  } : x));
  const disableAll = (group) => setCategories(cs => cs.map(x => x.group === group ? { ...x, enabled: false } : x));

  const removeSubcat = (id) => setCategories(cs => cs.filter(c => c.id !== id));

  const removeGroup = (group) => {
    setCategories(cs => cs.filter(c => c.group !== group));
    setPendingGroups(gs => gs.filter(g => g !== group));
    if (addingSubcat === group) { setAddingSubcat(null); setNewSubcatLabel(""); }
  };

  const addSubcat = (group) => {
    if (!newSubcatLabel.trim()) return;
    const label = newSubcatLabel.trim();
    const newCat = {
      id: label.toLowerCase().replace(/\s+/g, "_") + "_" + Date.now(),
      label, group, enabled: true,
    };
    setCategories(cs => [...cs, newCat]);
    setPendingGroups(gs => gs.filter(g => g !== group));
    setNewSubcatLabel("");
    setAddingSubcat(null);
  };

  const addGroup = () => {
    if (!newGroupName.trim()) return;
    const name = newGroupName.trim();
    if (!allGroups.includes(name)) setPendingGroups(gs => [...gs, name]);
    setNewGroupName("");
    setAddingGroup(false);
    setAddingSubcat(name);
  };

  const cancelSubcat = () => { setNewSubcatLabel(""); setAddingSubcat(null); };

  const btnSt = { background: "none", border: "none", fontSize: 11, cursor: "pointer", fontFamily: "inherit" };

  return (
    <div>
      <SectionHeader title="CATEGORY HINTS" sub={`${active.length} / ${categories.length} active · injected into Claude synthesis prompt`} />

      {allGroups.map(group => {
        const cats       = categories.filter(c => c.group === group);
        const allOn      = cats.length > 0 && cats.every(c => c.enabled);
        const allOff     = cats.length === 0 || cats.every(c => !c.enabled);
        const isPending  = cats.length === 0;
        const isAdding   = addingSubcat === group;

        return (
          <div key={group} style={{ marginBottom: 26 }}>
            {/* ── Group header ── */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <span style={{ fontSize: 11, letterSpacing: "0.12em", color: C.lo }}>{group.toUpperCase()}</span>
              <div style={{ flex: 1, height: 1, background: C.borderSub }} />
              {!isPending && (
                <>
                  <button onClick={() => enableAll(group)}  style={{ ...btnSt, color: allOn  ? C.border : C.lo }}>ALL</button>
                  <button onClick={() => disableAll(group)} style={{ ...btnSt, color: allOff ? C.border : C.lo }}>NONE</button>
                </>
              )}
              <button
                onClick={() => { setAddingSubcat(isAdding ? null : group); setNewSubcatLabel(""); }}
                style={{ ...btnSt, color: isAdding ? C.accent : C.lo, letterSpacing: "0.08em" }}
                onMouseEnter={e => e.currentTarget.style.color = C.accent}
                onMouseLeave={e => e.currentTarget.style.color = isAdding ? C.accent : C.lo}
              >+ ADD</button>
              <button
                onClick={() => removeGroup(group)}
                style={{ ...btnSt, fontSize: 18, color: C.lo, lineHeight: 1 }}
                onMouseEnter={e => e.currentTarget.style.color = C.red}
                onMouseLeave={e => e.currentTarget.style.color = C.lo}
              >×</button>
            </div>

            {/* ── Chips ── */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              {cats.map(cat => (
                <div
                  key={cat.id}
                  style={{ position: "relative", display: "inline-flex" }}
                  onMouseEnter={() => setHoveredId(cat.id)}
                  onMouseLeave={() => setHoveredId(null)}
                >
                  <div onClick={() => toggle(cat.id)} style={{
                    padding: "7px 15px", borderRadius: 4, cursor: "pointer",
                    border: `1px solid ${cat.enabled ? "#c2410c" : C.border}`,
                    background: cat.enabled ? "#7c2d1222" : "transparent",
                    color: cat.enabled ? "#fed7aa" : C.mid,
                    fontSize: 13, letterSpacing: "0.03em", transition: "all 0.1s", userSelect: "none",
                  }}>{cat.label}</div>
                  <button
                    onClick={e => { e.stopPropagation(); removeSubcat(cat.id); }}
                    style={{
                      position: "absolute", top: -7, right: -7,
                      width: 16, height: 16, borderRadius: "50%",
                      background: C.bgRaised, border: `1px solid ${C.border}`,
                      color: C.lo, cursor: "pointer", fontSize: 11, lineHeight: "14px",
                      padding: 0, fontFamily: "inherit", textAlign: "center",
                      opacity: hoveredId === cat.id ? 1 : 0, transition: "opacity 0.1s",
                      display: "flex", alignItems: "center", justifyContent: "center",
                    }}
                    onMouseEnter={e => e.currentTarget.style.color = C.red}
                    onMouseLeave={e => e.currentTarget.style.color = C.lo}
                  >×</button>
                </div>
              ))}

              {/* ── Inline add-subcat form ── */}
              {isAdding && (
                <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input
                    value={newSubcatLabel}
                    onChange={e => setNewSubcatLabel(e.target.value)}
                    placeholder="Subcategory name"
                    style={{ ...inputSt, padding: "7px 12px", fontSize: 13, width: 180 }}
                    onKeyDown={e => { if (e.key === "Enter") addSubcat(group); if (e.key === "Escape") cancelSubcat(); }}
                    autoFocus
                  />
                  <Btn onClick={() => addSubcat(group)}>ADD</Btn>
                  <Btn ghost onClick={cancelSubcat}>CANCEL</Btn>
                </div>
              )}

              {isPending && !isAdding && (
                <span style={{ fontSize: 12, color: C.lo, fontStyle: "italic" }}>
                  No subcategories yet — click + ADD
                </span>
              )}
            </div>
          </div>
        );
      })}

      {/* ── Add new category group ── */}
      {addingGroup ? (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
          <input
            value={newGroupName}
            onChange={e => setNewGroupName(e.target.value)}
            placeholder="Category group name  (e.g. Urban, Nature)"
            style={{ ...inputSt, flex: 1 }}
            onKeyDown={e => { if (e.key === "Enter") addGroup(); if (e.key === "Escape") { setAddingGroup(false); setNewGroupName(""); } }}
            autoFocus
          />
          <Btn onClick={addGroup}>ADD</Btn>
          <Btn ghost onClick={() => { setAddingGroup(false); setNewGroupName(""); }}>CANCEL</Btn>
        </div>
      ) : (
        <button
          onClick={() => setAddingGroup(true)}
          style={{
            width: "100%", background: "none", border: `1px dashed ${C.border}`,
            color: C.lo, padding: "12px", cursor: "pointer", fontFamily: "inherit",
            fontSize: 12, letterSpacing: "0.1em", borderRadius: 4, transition: "all 0.1s",
            marginTop: 8,
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = C.accent; e.currentTarget.style.color = C.accent; }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.color = C.lo; }}
        >+ ADD CATEGORY</button>
      )}
    </div>
  );
};

// ── Pipeline Tab ──────────────────────────────────────────────────────────────

const PipelineTab = ({ apiOnline }) => {
  const [status, setStatus] = useState({ state: "idle", queue_depth: 0, processed_today: 47, current_file: null, events: [] });

  useEffect(() => {
    if (!apiOnline) return;
    const poll = async () => {
      try { const d = await (await fetch(`${API_BASE}/api/pipeline/status`)).json(); setStatus(d); } catch {}
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [apiOnline]);

  const events = apiOnline ? (status.events || []) : MOCK_EVENTS;
  const stateColors = { idle: C.green, processing: C.accent, error: C.red, paused: C.yellow };
  const stateColor  = stateColors[status.state] || C.green;

  return (
    <div>
      <SectionHeader title="PIPELINE STATUS" sub={apiOnline ? "live · polling 3s" : "api offline · mock data"} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 24 }}>
        {[
          { label: "STATE",           value: (status.state || "idle").toUpperCase(), color: stateColor },
          { label: "QUEUE",           value: status.queue_depth ?? 0,                color: C.hi },
          { label: "PROCESSED TODAY", value: status.processed_today ?? 0,            color: C.hi },
        ].map(s => (
          <div key={s.label} style={{ background: C.bgSurface, border: `1px solid ${C.border}`, borderRadius: 4, padding: "16px 18px" }}>
            <div style={{ fontSize: 11, letterSpacing: "0.12em", color: C.lo, marginBottom: 10 }}>{s.label}</div>
            <div style={{ fontSize: 28, fontWeight: 600, color: s.color, letterSpacing: "0.04em" }}>{s.value}</div>
          </div>
        ))}
      </div>

      {status.current_file && (
        <div style={{ padding: "10px 14px", background: "#110800", border: `1px solid ${C.accentDim}`, borderRadius: 4, marginBottom: 16, fontSize: 13, color: "#fed7aa" }}>
          ▶ {status.current_file}
        </div>
      )}

      <div style={{ fontSize: 11, letterSpacing: "0.12em", color: C.lo, marginBottom: 10 }}>RECENT ACTIVITY</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 4, overflow: "hidden" }}>
        {events.length === 0 ? (
          <div style={{ padding: 24, color: C.lo, fontSize: 13, textAlign: "center" }}>No activity</div>
        ) : events.map((ev, i) => {
          const sc = ev.status === "enriched" ? C.green : ev.status === "error" ? C.red : C.yellow;
          return (
            <div key={i} style={{
              display: "grid", gridTemplateColumns: "80px 1fr 80px 60px",
              gap: 12, padding: "11px 14px", fontSize: 13,
              borderBottom: i < events.length - 1 ? `1px solid ${C.borderSub}` : "none",
              background: ev.status === "error" ? "#0d0000" : "transparent",
            }}>
              <span style={{ color: C.lo }}>{ev.ts}</span>
              <span style={{ color: C.mid, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.file}</span>
              <span style={{ color: sc }}>{ev.status}</span>
              <span style={{ color: C.lo, textAlign: "right" }}>{ev.ms !== "—" ? `${ev.ms}ms` : "—"}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ── Models Tab ────────────────────────────────────────────────────────────────

const ModelsTab = ({ models, setModels, apiOnline }) => {
  const patchModel = async (id, body) => {
    if (!apiOnline) return;
    try { await fetch(`${API_BASE}/api/models/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); } catch {}
  };

  const toggle = (id) => {
    const m = models.find(x => x.id === id);
    patchModel(id, { enabled: !m.enabled });
    setModels(ms => ms.map(x => x.id === id ? { ...x, enabled: !x.enabled, status: !m.enabled ? "ready" : "disabled" } : x));
  };

  const setThreshold = (id, val) => {
    patchModel(id, { threshold: val });
    setModels(ms => ms.map(x => x.id === id ? { ...x, threshold: val } : x));
  };

  const modelColors = { yamnet: C.cyan, whisper: C.purple, audioclip: C.accent, essentia: C.green };

  return (
    <div>
      <SectionHeader title="ANALYSIS MODELS" sub="local ML pipeline · upstream of Claude synthesis" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {models.map(m => {
          const accent = modelColors[m.id] || C.accent;
          return (
            <div key={m.id} style={{
              border: `1px solid ${m.enabled ? C.border : C.borderSub}`,
              borderLeft: `3px solid ${m.enabled ? accent : C.border}`,
              borderRadius: "0 4px 4px 0", padding: "18px",
              background: m.enabled ? C.bgSurface : C.bgBase,
              opacity: m.enabled ? 1 : 0.55, transition: "opacity 0.2s",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <StatusDot status={m.status} />
                    <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "0.06em", color: m.enabled ? C.hi : C.lo }}>{m.name}</span>
                  </div>
                  <div style={{ fontSize: 12, color: C.mid, lineHeight: 1.5 }}>{m.desc}</div>
                </div>
                <Toggle enabled={m.enabled} onChange={() => toggle(m.id)} />
              </div>
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, letterSpacing: "0.1em", color: C.lo }}>CONFIDENCE THRESHOLD</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: m.enabled ? accent : C.lo }}>{m.threshold.toFixed(2)}</span>
                </div>
                <input
                  type="range" min={0.05} max={0.95} step={0.05}
                  value={m.threshold} disabled={!m.enabled}
                  onChange={e => setThreshold(m.id, parseFloat(e.target.value))}
                  style={{ width: "100%", cursor: m.enabled ? "pointer" : "not-allowed", accentColor: accent }}
                />
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5 }}>
                  <span style={{ fontSize: 11, color: C.lo }}>PERMISSIVE</span>
                  <span style={{ fontSize: 11, color: C.lo }}>STRICT</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: 16, padding: "14px 18px", background: C.bgSurface, border: `1px solid ${C.border}`, borderRadius: 4 }}>
        <div style={{ fontSize: 11, letterSpacing: "0.12em", color: C.lo, marginBottom: 10 }}>ACTIVE PIPELINE ORDER</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {models.filter(m => m.enabled).map((m, i, arr) => (
            <span key={m.id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13, color: modelColors[m.id] || C.accent }}>{m.name}</span>
              {i < arr.length - 1 && <span style={{ color: C.border, fontSize: 12 }}>→</span>}
            </span>
          ))}
          {models.filter(m => m.enabled).length > 0 && (
            <>
              <span style={{ color: C.border, fontSize: 12 }}>→</span>
              <span style={{ fontSize: 13, color: C.accent, fontWeight: 600 }}>Claude</span>
            </>
          )}
          {models.filter(m => m.enabled).length === 0 && (
            <span style={{ fontSize: 13, color: C.lo }}>No models active · Claude synthesis only</span>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Control Strip ────────────────────────────────────────────────────────────

const ControlStrip = ({ apiOnline }) => {
  const [tickState,  setTickState]  = useState("idle"); // "idle" | "running" | "paused"
  const [serviceMsg, setServiceMsg] = useState("");      // e.g. "starting ollama..."
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!apiOnline) return;
    const poll = async () => {
      try {
        const d = await (await fetch(`${API_BASE}/api/pipeline/status`)).json();
        setTickState(d.state === "processing" ? "running" : d.state === "paused" ? "paused" : "idle");
      } catch {}
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [apiOnline]);

  const call = async (endpoint) => {
    setBusy(true);
    if (endpoint === "/api/tick/run") setServiceMsg("starting services…");
    if (apiOnline) {
      try {
        const res = await fetch(`${API_BASE}${endpoint}`, { method: "POST" });
        const d   = await res.json();
        if (d.services) {
          const ollama = d.services.ollama;
          if      (ollama === "started")   setServiceMsg("ollama started");
          else if (ollama === "starting")  setServiceMsg("ollama starting…");
          else if (ollama === "not_found") setServiceMsg("ollama not found · using Claude");
          else                             setServiceMsg("");
          setTimeout(() => setServiceMsg(""), 5000);
        } else {
          setServiceMsg("");
        }
      } catch { setServiceMsg(""); }
    } else {
      setServiceMsg("");
    }
    if (endpoint === "/api/tick/run")    setTickState("running");
    if (endpoint === "/api/tick/pause")  setTickState("paused");
    if (endpoint === "/api/tick/resume") setTickState("idle");
    if (endpoint === "/api/tick/reset")  { setTickState("idle"); setServiceMsg(""); }
    setBusy(false);
  };

  const stateColor = { idle: C.green, running: C.accent, paused: C.yellow }[tickState] || C.green;
  const dotStatus  = { idle: "ready", running: "processing", paused: "connecting" }[tickState] || "ready";

  return (
    <div style={{
      borderBottom: `1px solid ${C.border}`,
      padding: "10px 28px",
      display: "flex", alignItems: "center", gap: 8,
      background: "#161616",
    }}>
      <Btn small onClick={() => call("/api/tick/run")} disabled={tickState === "running" || busy}>
        ▶ RUN TICK
      </Btn>

      {tickState === "paused" ? (
        <Btn small ghost onClick={() => call("/api/tick/resume")} disabled={busy}>
          ↺ RESUME
        </Btn>
      ) : (
        <Btn small ghost onClick={() => call("/api/tick/pause")} disabled={tickState !== "running" || busy}>
          ⏸ PAUSE
        </Btn>
      )}

      <Btn small ghost danger onClick={() => call("/api/tick/reset")} disabled={busy}>
        ↺ RESET
      </Btn>

      {serviceMsg && (
        <span style={{ fontSize: 11, color: C.lo, letterSpacing: "0.06em", marginLeft: 4 }}>
          {serviceMsg}
        </span>
      )}

      <div style={{ flex: 1 }} />

      <StatusDot status={dotStatus} />
      <span style={{ fontSize: 11, letterSpacing: "0.1em", color: stateColor }}>
        {tickState.toUpperCase()}
      </span>
    </div>
  );
};

// ── App Root ──────────────────────────────────────────────────────────────────

const TABS = ["SOURCES", "CATEGORIES", "PIPELINE", "MODELS"];

export default function App() {
  const [tab, setTab]             = useState("SOURCES");
  const [sources, setSources]     = useState(DEFAULT_SOURCES);
  const [categories, setCategories] = useState(DEFAULT_CATEGORIES);
  const [models, setModels]       = useState(DEFAULT_MODELS);
  const [apiOnline, setApiOnline] = useState(false);
  const [apiChecked, setApiChecked] = useState(false);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(2500) });
        if (res.ok) {
          setApiOnline(true);
          const [sRes, cRes, mRes] = await Promise.all([
            fetch(`${API_BASE}/api/sources`),
            fetch(`${API_BASE}/api/categories`),
            fetch(`${API_BASE}/api/models`),
          ]);
          if (sRes.ok) setSources(await sRes.json());
          if (cRes.ok) setCategories(await cRes.json());
          if (mRes.ok) setModels(await mRes.json());
        } else { setApiOnline(false); }
      } catch { setApiOnline(false); }
      setApiChecked(true);
    };
    check();
    const t = setInterval(check, 12000);
    return () => clearInterval(t);
  }, []);

  const apiStatus = !apiChecked ? "connecting" : apiOnline ? "ready" : "offline";
  const apiLabel  = !apiChecked ? "CONNECTING"  : apiOnline ? "API ONLINE" : "API OFFLINE · MOCK DATA";

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap');
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #111111; font-family: 'JetBrains Mono', 'Fira Code', monospace; }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
        ::-webkit-scrollbar { width: 4px; background: #1a1a1a; }
        ::-webkit-scrollbar-thumb { background: #2e2e2e; border-radius: 2px; }
        select, input, button { font-family: inherit; }
        select option { background: #1a1a1a; color: #e2e8f0; }
        input[type=range] { -webkit-appearance: none; appearance: none; height: 4px; border-radius: 2px; background: #2e2e2e; }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 50%; background: currentColor; cursor: pointer; }
      `}</style>

      <div style={{ minHeight: "100vh", background: C.bgBase, fontFamily: "'JetBrains Mono', monospace", color: C.hi }}>

        {/* ── Header ── */}
        <div style={{ borderBottom: `1px solid ${C.border}`, padding: "16px 28px", display: "flex", justifyContent: "space-between", alignItems: "center", background: C.bgSurface }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
            <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: "0.22em", color: C.accent }}>SOUND</span>
            <span style={{ fontSize: 15, fontWeight: 300, letterSpacing: "0.22em", color: C.mid }}>AGENT</span>
            <span style={{ fontSize: 12, color: C.lo, marginLeft: 12, letterSpacing: "0.06em" }}>v0.2</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StatusDot status={apiStatus} />
            <span style={{ fontSize: 12, letterSpacing: "0.08em", color: C.lo }}>{apiLabel}</span>
          </div>
        </div>

        {/* ── Control strip ── */}
        <ControlStrip apiOnline={apiOnline} />

        {/* ── Tab bar ── */}
        <div style={{ borderBottom: `1px solid ${C.border}`, display: "flex", padding: "0 28px", background: C.bgSurface }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              background: "none", border: "none", cursor: "pointer",
              padding: "14px 22px", fontFamily: "inherit", fontSize: 12,
              fontWeight: t === tab ? 700 : 400, letterSpacing: "0.12em",
              color: t === tab ? C.accent : C.lo,
              borderBottom: `2px solid ${t === tab ? C.accent : "transparent"}`,
              marginBottom: -1, transition: "color 0.1s",
            }}
              onMouseEnter={e => { if (t !== tab) e.currentTarget.style.color = C.mid; }}
              onMouseLeave={e => { if (t !== tab) e.currentTarget.style.color = C.lo; }}
            >{t}</button>
          ))}
        </div>

        {/* ── Content ── */}
        <div style={{ padding: "32px 28px", maxWidth: 960, margin: "0 auto" }}>
          {tab === "SOURCES"    && <SourcesTab    sources={sources}         setSources={setSources}         apiOnline={apiOnline} />}
          {tab === "CATEGORIES" && <CategoriesTab categories={categories}   setCategories={setCategories}   apiOnline={apiOnline} />}
          {tab === "PIPELINE"   && <PipelineTab   apiOnline={apiOnline} />}
          {tab === "MODELS"     && <ModelsTab     models={models}           setModels={setModels}           apiOnline={apiOnline} />}
        </div>
      </div>
    </>
  );
}
