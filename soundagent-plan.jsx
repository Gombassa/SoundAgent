import { useState } from "react";

const PHASES = [
  {
    id: 1,
    code: "P1",
    title: "Foundation & Scaffolding",
    status: "planned",
    estimate: "2–3 days",
    deliverables: [
      "Project repo initialised (Git)",
      "Python virtual environment + dependency manifest",
      "Folder hierarchy creator script (library root + inbox + staging + errors)",
      "Config file (YAML): sources block, library root, tick interval, Basehead import path",
      "Source adapter config: local | network | rclone | webdav — each as named entry",
      "Basic tick runner (CLI invocable, loggable)",
      "ffprobe wrapper: extract duration, SR, bit depth, channels, format",
    ],
    tasks: [
      { label: "Repo & venv setup", deps: [] },
      { label: "Config loader (YAML) with sources block", deps: [] },
      { label: "Folder hierarchy initialiser", deps: ["Config loader (YAML) with sources block"] },
      { label: "ffprobe metadata extractor", deps: [] },
      { label: "Tick runner scaffold", deps: ["Config loader (YAML) with sources block"] },
      { label: "Logging framework (rotating file + console)", deps: ["Tick runner scaffold"] },
    ],
    risks: [],
  },
  {
    id: 2,
    code: "P2",
    title: "Ingest Adapters + Pipeline",
    status: "planned",
    estimate: "4–5 days",
    deliverables: [
      "Source adapter base class — common interface for all ingest types",
      "Local adapter: watchdog filesystem event monitor on one or more inbox paths",
      "Network adapter: watchdog on mapped/mounted network path (SMB, NFS) with availability check",
      "Rclone adapter: config generator + sync/mount mode toggle; any of 70+ cloud providers",
      "WebDAV adapter: wsgidav server as background service; exposes inbox as WebDAV endpoint",
      "Mobile ingest: WebDAV accessible from iOS Files app and Android file managers natively",
      "All adapters deliver to unified local /inbox/ — agent is source-agnostic from here",
      "SHA-256 deduplication against catalogue",
      "Staging copy/move with atomic rename",
      "File-type allowlist validation",
      "Ingest event log (source adapter, filename, hash, timestamp, status)",
    ],
    tasks: [
      { label: "Source adapter base class", deps: ["Config loader (YAML) with sources block"] },
      { label: "Local adapter (watchdog)", deps: ["Source adapter base class"] },
      { label: "Network adapter (watchdog + availability check)", deps: ["Source adapter base class"] },
      { label: "Rclone adapter (sync + mount modes)", deps: ["Source adapter base class"] },
      { label: "Rclone config generator (provider selection)", deps: ["Rclone adapter (sync + mount modes)"] },
      { label: "WebDAV server (wsgidav, background service)", deps: ["Source adapter base class"] },
      { label: "WebDAV auth + port config", deps: ["WebDAV server (wsgidav, background service)"] },
      { label: "SHA-256 hasher + dedup check", deps: [] },
      { label: "Staging copy/move logic", deps: ["Local adapter (watchdog)", "SHA-256 hasher + dedup check"] },
      { label: "Format/extension validator", deps: [] },
      { label: "Ingest event log writer", deps: ["Staging copy/move logic"] },
    ],
    risks: [
      "Network/cloud paths intermittently unavailable — graceful skip + retry queue per adapter",
      "Rclone mount requires FUSE on Windows (WinFsp) — document dependency clearly",
      "WebDAV on LAN vs remote: advise user on port-forwarding / VPN if remote mobile access needed",
    ],
  },
  {
    id: 3,
    code: "P3",
    title: "Claude Enrichment Pipeline",
    status: "planned",
    estimate: "3–4 days",
    deliverables: [
      "Claude API client with retry + rate-limit handling",
      "Enrichment prompt: category, subcategory, description, tags, mood, BPM/key (music), energy",
      "Structured JSON response parser + schema validator",
      "Confidence threshold: low-confidence → /unclassified/",
      "Enrichment cache keyed on SHA-256 (avoid re-processing unchanged files)",
      "Source annotation: enrichment record stores which adapter delivered the file",
    ],
    tasks: [
      { label: "Claude API wrapper (claude-sonnet-4)", deps: [] },
      { label: "Enrichment prompt design + iteration", deps: ["ffprobe metadata extractor"] },
      { label: "JSON schema validator for API response", deps: ["Claude API wrapper (claude-sonnet-4)"] },
      { label: "Confidence scoring + fallback routing", deps: ["JSON schema validator for API response"] },
      { label: "Enrichment result cache (hash-keyed)", deps: ["SHA-256 hasher + dedup check"] },
    ],
    risks: [
      "API latency on large batches — async queue with concurrency cap",
      "Prompt tuning for mixed library types will require several iterations",
    ],
  },
  {
    id: 4,
    code: "P4",
    title: "iXML/BWF Metadata Writer",
    status: "planned",
    estimate: "2 days",
    deliverables: [
      "BWF iXML chunk writer: embed enriched metadata into WAV header before library delivery",
      "ID3 writer for MP3 files",
      "XMP sidecar writer for formats without embedded metadata support",
      "UCS-compatible field mapping (category, subcategory, FXName, CatID)",
      "Basehead-readable field layout validated against Basehead import behaviour",
      "Metadata write verified with bwfmetaedit CLI",
    ],
    tasks: [
      { label: "BWF iXML writer (bwfmetaedit or soundfile)", deps: ["Enrichment result cache (hash-keyed)"] },
      { label: "ID3 writer (mutagen)", deps: ["Enrichment result cache (hash-keyed)"] },
      { label: "XMP sidecar writer", deps: ["Enrichment result cache (hash-keyed)"] },
      { label: "UCS field mapper", deps: ["JSON schema validator for API response"] },
      { label: "Basehead import validation test", deps: ["BWF iXML writer (bwfmetaedit or soundfile)", "UCS field mapper"] },
    ],
    risks: [
      "iXML spec has edge cases with non-ASCII characters — test with multilingual content early",
      "Basehead field mapping needs empirical testing; no public iXML import spec documented",
    ],
  },
  {
    id: 5,
    code: "P5",
    title: "Auto-Organiser + Basehead Delivery",
    status: "planned",
    estimate: "2 days",
    deliverables: [
      "Routing rules engine: enriched category + subcategory → target library path",
      "Safe atomic move with collision handling (append hash fragment)",
      "Dry-run mode: log intended moves, no filesystem writes",
      "Manual override: per-file destination pinning via sidecar JSON",
      "Delivery to Basehead import folder: agent places enriched + tagged file where Basehead watches",
      "Post-delivery log entry flagging file as ready for Basehead rescan",
    ],
    tasks: [
      { label: "Routing rules engine", deps: ["Confidence scoring + fallback routing"] },
      { label: "Safe atomic move + collision handler", deps: ["Routing rules engine"] },
      { label: "Dry-run mode flag", deps: ["Routing rules engine"] },
      { label: "Sidecar override parser", deps: ["Routing rules engine"] },
      { label: "Basehead delivery path config", deps: ["Config loader (YAML) with sources block"] },
      { label: "Post-delivery log entry", deps: ["Basehead delivery path config", "Safe atomic move + collision handler"] },
    ],
    risks: [
      "Category ambiguity edge cases — /unclassified/ must always be a safe fallback",
    ],
  },
  {
    id: 6,
    code: "P6",
    title: "SQLite Catalogue",
    status: "planned",
    estimate: "2 days",
    deliverables: [
      "DB schema: files, tags, enrichment, ingest_log, source_log, errors",
      "Upsert on each tick (SHA-256 hash as primary key)",
      "Full-text search index (FTS5) on description + tags",
      "CLI query tool: search by tag, category, BPM range, duration range, source adapter",
      "DB integrity checks on startup",
    ],
    tasks: [
      { label: "Schema design + migrations", deps: [] },
      { label: "Upsert writer", deps: ["Schema design + migrations", "JSON schema validator for API response"] },
      { label: "FTS5 index configuration", deps: ["Upsert writer"] },
      { label: "CLI query interface", deps: ["FTS5 index configuration"] },
      { label: "Startup integrity check", deps: ["Schema design + migrations"] },
    ],
    risks: [],
  },
  {
    id: 7,
    code: "P7",
    title: "Cowork Integration",
    status: "planned",
    estimate: "1–2 days",
    deliverables: [
      "Cowork task definition: tick interval, working directory, env vars",
      "Environment variable config layer (overrides YAML): API key, paths, adapter flags",
      "Adapter health check on each tick: report unavailable sources, skip gracefully",
      "Tick summary report (plaintext + structured JSON): files processed per source adapter",
      "Error escalation: failed files quarantined to /errors/ with source annotation",
      "Cowork-compatible exit codes",
    ],
    tasks: [
      { label: "Cowork task config file", deps: ["Tick runner scaffold"] },
      { label: "Env var config layer", deps: ["Config loader (YAML) with sources block"] },
      { label: "Adapter health check + tick report", deps: ["Source adapter base class"] },
      { label: "Tick summary report generator", deps: ["Ingest event log writer"] },
      { label: "Error quarantine + source annotation", deps: ["Safe atomic move + collision handler"] },
      { label: "Exit code standardisation", deps: ["Tick runner scaffold"] },
    ],
    risks: [
      "Confirm Python, ffprobe, rclone, and WinFsp (if used) are available in Cowork execution context",
      "WebDAV background service lifecycle: ensure clean start/stop with agent process",
    ],
  },
  {
    id: 8,
    code: "P8",
    title: "Search Interface",
    status: "planned",
    estimate: "3–4 days",
    deliverables: [
      "Lightweight web UI (FastAPI + HTMX or React)",
      "Search: full-text, tag filter, category filter, source adapter filter, duration/BPM sliders",
      "File detail panel: all metadata, source adapter, delivery status",
      "Copy-path and export-CSV actions",
      "Optional: audio preview (if browser-accessible path)",
    ],
    tasks: [
      { label: "FastAPI server scaffold", deps: ["CLI query interface"] },
      { label: "Search endpoint + query builder", deps: ["FastAPI server scaffold"] },
      { label: "Frontend: search + filter UI", deps: ["Search endpoint + query builder"] },
      { label: "File detail panel", deps: ["Frontend: search + filter UI"] },
      { label: "Export to CSV", deps: ["Search endpoint + query builder"] },
    ],
    risks: [
      "Audio preview feasibility depends on library path accessibility from browser context",
    ],
  },
];

const STACK = [
  { layer: "Scheduler", tech: "Cowork", note: "Tick interval, env, task runner" },
  { layer: "Agent Runtime", tech: "Python 3.11+", note: "Core pipeline logic" },
  { layer: "Local/Network Ingest", tech: "watchdog", note: "Filesystem event monitor for local + mapped paths" },
  { layer: "Cloud Ingest", tech: "rclone", note: "Universal adapter — 70+ providers, sync or mount mode" },
  { layer: "Mobile Ingest", tech: "wsgidav (WebDAV)", note: "Self-hosted; iOS Files app + Android native, no extra app" },
  { layer: "Audio Analysis", tech: "ffprobe (FFmpeg)", note: "Technical metadata extraction" },
  { layer: "AI Enrichment", tech: "Claude claude-sonnet-4", note: "Tags, description, category, mood, BPM/key" },
  { layer: "Metadata Embedding", tech: "bwfmetaedit + mutagen", note: "iXML/BWF (WAV), ID3 (MP3), XMP sidecar" },
  { layer: "UCS Mapping", tech: "Custom mapper", note: "Enrichment → UCS-compatible field layout for Basehead" },
  { layer: "Library Front-end", tech: "Basehead Ultra", note: "Search, audition, spot-to-PT; Basehead Connect AAX plugin" },
  { layer: "Database", tech: "SQLite + FTS5", note: "Catalogue, dedup, full-text search" },
  { layer: "Config", tech: "YAML + env vars", note: "Sources, paths, intervals, adapter config" },
  { layer: "Search UI", tech: "FastAPI + React or HTMX", note: "Phase 8 — TBD" },
  { layer: "Monitoring", tech: "Rotating log files", note: "Per-tick reports, per-source health, error quarantine" },
];

const SOURCES = [
  { type: "Local folder", adapter: "watchdog (direct)", notes: "Any path on local filesystem", mobile: false },
  { type: "Network share / NAS", adapter: "watchdog on mapped path", notes: "SMB, NFS — graceful skip if unavailable", mobile: false },
  { type: "Any cloud provider", adapter: "rclone sync or mount", notes: "S3, GDrive, OneDrive, Backblaze, SFTP, 70+ more", mobile: false },
  { type: "Mobile — iOS", adapter: "WebDAV via wsgidav", notes: "iOS Files app native — no extra app needed", mobile: true },
  { type: "Mobile — Android", adapter: "WebDAV via wsgidav", notes: "FolderSync, Cx File Explorer, Solid Explorer", mobile: true },
  { type: "Field recorder app", adapter: "WebDAV or rclone export", notes: "Apps with WebDAV/cloud export point directly to inbox", mobile: true },
  { type: "Recording session", adapter: "Local folder", notes: "Set DAW/app export path to agent inbox directly", mobile: false },
];

const TOTAL_DAYS = "19–27";

export default function SoundAgentPlan() {
  const [activePhase, setActivePhase] = useState(1);
  const [activeTab, setActiveTab] = useState("phases");
  const phase = PHASES.find((p) => p.id === activePhase);

  const tabStyle = (id) => ({
    background: "none", border: "none",
    borderBottom: activeTab === id ? "2px solid #4a9eff" : "2px solid transparent",
    color: activeTab === id ? "#e8edf4" : "#4a5870",
    cursor: "pointer", fontSize: "12px", letterSpacing: "1px",
    padding: "14px 18px 12px", textTransform: "uppercase",
    marginBottom: "-1px", transition: "color 0.15s", fontFamily: "inherit",
  });

  const sectionLabel = (text) => (
    <div style={{ fontSize: "10px", letterSpacing: "2px", color: "#3a4860", marginBottom: "12px", textTransform: "uppercase" }}>{text}</div>
  );

  const theadRow = (cols) => (
    <thead>
      <tr style={{ background: "#0a0c10" }}>
        {cols.map((c) => (
          <th key={c} style={{ textAlign: "left", padding: "10px 16px", color: "#3a4860", fontWeight: "400", fontSize: "10px", letterSpacing: "1.5px", textTransform: "uppercase" }}>{c}</th>
        ))}
      </tr>
    </thead>
  );

  const tableCard = (children) => (
    <div style={{ background: "#0d1118", border: "1px solid #1a2030", borderRadius: "6px", overflow: "hidden" }}>{children}</div>
  );

  return (
    <div style={{ fontFamily: "'JetBrains Mono','Fira Mono','Courier New',monospace", background: "#0d0f12", color: "#c8d0db", minHeight: "100vh" }}>

      {/* Header */}
      <div style={{ borderBottom: "1px solid #1e2530", padding: "24px 32px 20px", background: "#0a0c0f" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "16px", marginBottom: "6px" }}>
          <span style={{ fontSize: "11px", color: "#4a9eff", letterSpacing: "3px", textTransform: "uppercase" }}>PROJECT PLAN</span>
          <span style={{ fontSize: "11px", color: "#2a3040" }}>v0.2 — 2026-04-30</span>
        </div>
        <h1 style={{ margin: "0 0 4px", fontSize: "28px", color: "#e8edf4", fontWeight: "700", letterSpacing: "-0.5px" }}>SoundAgent</h1>
        <p style={{ margin: 0, fontSize: "13px", color: "#5a6880" }}>
          Agent-tick managed sound library · Cowork + Python + Claude API + Basehead + SQLite
        </p>
        <div style={{ marginTop: "14px", display: "flex", gap: "32px", flexWrap: "wrap" }}>
          {[
            { label: "PHASES", value: "8" },
            { label: "EST. DURATION", value: TOTAL_DAYS + " days" },
            { label: "FRONT-END", value: "Basehead Ultra" },
            { label: "INGEST", value: "Local · Network · rclone · WebDAV" },
          ].map((s) => (
            <div key={s.label}>
              <div style={{ fontSize: "9px", color: "#3a4860", letterSpacing: "2px" }}>{s.label}</div>
              <div style={{ fontSize: "13px", color: "#4a9eff", marginTop: "2px" }}>{s.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ borderBottom: "1px solid #1e2530", padding: "0 32px", display: "flex" }}>
        {[
          { id: "phases", label: "Phases" },
          { id: "sources", label: "Ingest Sources" },
          { id: "stack", label: "Tech Stack" },
          { id: "architecture", label: "Architecture" },
        ].map((t) => <button key={t.id} onClick={() => setActiveTab(t.id)} style={tabStyle(t.id)}>{t.label}</button>)}
      </div>

      <div style={{ padding: "28px 32px", maxWidth: "1100px" }}>

        {/* PHASES TAB */}
        {activeTab === "phases" && (
          <div style={{ display: "grid", gridTemplateColumns: "210px 1fr", gap: "24px" }}>
            <div>
              {PHASES.map((p) => (
                <button key={p.id} onClick={() => setActivePhase(p.id)} style={{
                  display: "block", width: "100%",
                  background: activePhase === p.id ? "#131820" : "none",
                  border: activePhase === p.id ? "1px solid #1e2d45" : "1px solid transparent",
                  borderLeft: activePhase === p.id ? "3px solid #4a9eff" : "3px solid transparent",
                  color: activePhase === p.id ? "#e8edf4" : "#4a5870",
                  cursor: "pointer", padding: "10px 14px", textAlign: "left",
                  borderRadius: "4px", marginBottom: "4px", fontSize: "12px", fontFamily: "inherit",
                }}>
                  <div style={{ color: activePhase === p.id ? "#4a9eff" : "#2a3850", fontSize: "10px", marginBottom: "2px" }}>{p.code}</div>
                  <div style={{ lineHeight: "1.3" }}>{p.title}</div>
                  <div style={{ marginTop: "3px", color: activePhase === p.id ? "#3a5870" : "#2a3040", fontSize: "10px" }}>{p.estimate}</div>
                </button>
              ))}
            </div>

            {phase && (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "20px", flexWrap: "wrap" }}>
                  <span style={{ fontSize: "11px", color: "#4a9eff", background: "#0a1828", border: "1px solid #1e3050", padding: "3px 10px", borderRadius: "3px" }}>{phase.code}</span>
                  <h2 style={{ margin: 0, fontSize: "17px", color: "#e8edf4", fontWeight: "600" }}>{phase.title}</h2>
                  <span style={{ marginLeft: "auto", fontSize: "11px", color: "#5a6880", background: "#131820", border: "1px solid #1e2530", padding: "3px 10px", borderRadius: "3px" }}>EST: {phase.estimate}</span>
                </div>

                <div style={{ marginBottom: "22px" }}>
                  {sectionLabel("Deliverables")}
                  <div style={{ background: "#0d1118", border: "1px solid #1a2030", borderRadius: "6px", padding: "16px" }}>
                    {phase.deliverables.map((d, i) => (
                      <div key={i} style={{ display: "flex", gap: "10px", marginBottom: i < phase.deliverables.length - 1 ? "8px" : "0", alignItems: "flex-start" }}>
                        <span style={{ color: "#4a9eff", flexShrink: 0, marginTop: "2px" }}>◆</span>
                        <span style={{ fontSize: "13px", color: "#9aacbe", lineHeight: "1.5" }}>{d}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ marginBottom: "22px" }}>
                  {sectionLabel("Tasks")}
                  {tableCard(
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                      {theadRow(["Task", "Depends On"])}
                      <tbody>
                        {phase.tasks.map((t, i) => (
                          <tr key={i} style={{ borderTop: "1px solid #141c28" }}>
                            <td style={{ padding: "10px 16px", color: "#c8d0db", width: "45%", lineHeight: "1.4" }}>{t.label}</td>
                            <td style={{ padding: "10px 16px" }}>
                              {t.deps.length === 0
                                ? <span style={{ color: "#2a3040" }}>—</span>
                                : t.deps.map((d, j) => (
                                    <span key={j} style={{ display: "inline-block", background: "#0a1420", border: "1px solid #1a2a3a", borderRadius: "3px", padding: "2px 7px", marginRight: "5px", marginBottom: "3px", fontSize: "11px", color: "#5a7890" }}>{d}</span>
                                  ))}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                {phase.risks.length > 0 && (
                  <div>
                    {sectionLabel("Risks & Mitigations")}
                    <div style={{ background: "#110c06", border: "1px solid #2a1e0a", borderRadius: "6px", padding: "16px" }}>
                      {phase.risks.map((r, i) => (
                        <div key={i} style={{ display: "flex", gap: "10px", marginBottom: i < phase.risks.length - 1 ? "10px" : "0", alignItems: "flex-start" }}>
                          <span style={{ color: "#f5a623", flexShrink: 0, marginTop: "2px" }}>⚠</span>
                          <span style={{ fontSize: "13px", color: "#9a8a6e", lineHeight: "1.5" }}>{r}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* INGEST SOURCES TAB */}
        {activeTab === "sources" && (
          <div>
            {sectionLabel("Source Adapter Overview")}
            <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "20px 28px", fontFamily: "monospace", fontSize: "12px", lineHeight: "2.3", marginBottom: "28px" }}>
              {[
                ["Local folder        ", "#4a9eff", "watchdog (direct)          "],
                ["Network / NAS       ", "#4a9eff", "watchdog on mapped path    "],
                ["Any cloud provider  ", "#9b59b6", "rclone sync or mount       "],
                ["Mobile — iOS        ", "#4caf50", "WebDAV (wsgidav)           "],
                ["Mobile — Android    ", "#4caf50", "WebDAV (wsgidav)           "],
                ["Field recorder app  ", "#4caf50", "WebDAV or rclone export    "],
                ["Recording session   ", "#4a9eff", "local export path          "],
              ].map(([src, col, adapter], i) => (
                <div key={i} style={{ display: "flex", gap: "4px", alignItems: "baseline" }}>
                  <span style={{ color: col, minWidth: "210px" }}>{src}</span>
                  <span style={{ color: "#1e2840" }}>→  </span>
                  <span style={{ color: "#5a6880", minWidth: "230px" }}>{adapter}</span>
                  <span style={{ color: "#1e2840" }}>→  </span>
                  <span style={{ color: "#2a5040" }}>/inbox/</span>
                </div>
              ))}
              <div style={{ marginTop: "14px", paddingTop: "14px", borderTop: "1px solid #1a2030", display: "flex", gap: "4px" }}>
                <span style={{ color: "#2a3850", minWidth: "450px" }}>Agent inbox — source-agnostic from this point onwards</span>
                <span style={{ color: "#1e2840" }}>→  </span>
                <span style={{ color: "#2a5040" }}>Enrich → Embed → Basehead</span>
              </div>
            </div>

            {sectionLabel("Adapter Detail")}
            {tableCard(
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                {theadRow(["Source Type", "Adapter", "Notes", "Mobile"])}
                <tbody>
                  {SOURCES.map((s, i) => (
                    <tr key={i} style={{ borderTop: "1px solid #141c28" }}>
                      <td style={{ padding: "11px 16px", color: "#c8d0db" }}>{s.type}</td>
                      <td style={{ padding: "11px 16px", color: "#4a9eff", fontSize: "11px" }}>{s.adapter}</td>
                      <td style={{ padding: "11px 16px", color: "#5a6880" }}>{s.notes}</td>
                      <td style={{ padding: "11px 16px", textAlign: "center", color: s.mobile ? "#4caf50" : "#2a3040" }}>{s.mobile ? "✓" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div style={{ marginTop: "28px" }}>
              {sectionLabel("YAML Config — sources block")}
              <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "20px 24px", fontSize: "12px", lineHeight: "1.9", color: "#5a7890" }}>
                {[
                  ["sources:", "#e8edf4", 0],
                  ["- name: local-inbox", "#9aacbe", 1],
                  ["  type: local", "#5a7890", 1],
                  ["  path: C:\\Users\\robin\\SoundAgent\\inbox", "#5a7890", 1],
                  ["", "", 0],
                  ["- name: nas-inbox", "#9aacbe", 1],
                  ["  type: network", "#5a7890", 1],
                  ["  path: \\\\NAS\\soundlibrary\\inbox", "#5a7890", 1],
                  ["", "", 0],
                  ["- name: cloud-any", "#9aacbe", 1],
                  ["  type: rclone", "#5a7890", 1],
                  ["  remote: myremote        # any rclone-configured provider", "#3a5870", 1],
                  ["  remote_path: /inbox", "#5a7890", 1],
                  ["  mode: sync              # or: mount", "#3a5870", 1],
                  ["  interval: 60            # seconds (sync mode only)", "#3a5870", 1],
                  ["", "", 0],
                  ["- name: mobile-webdav", "#9aacbe", 1],
                  ["  type: webdav", "#5a7890", 1],
                  ["  enabled: true", "#5a7890", 1],
                  ["  port: 8080", "#5a7890", 1],
                  ["  auth: true", "#5a7890", 1],
                  ["  username: soundagent", "#5a7890", 1],
                ].map(([line, col, indent], i) => (
                  <div key={i} style={{ paddingLeft: `${indent * 16}px`, color: col, minHeight: "20px" }}>{line}</div>
                ))}
              </div>
            </div>

            <div style={{ marginTop: "28px" }}>
              {sectionLabel("Mobile Setup — iOS (zero extra apps)")}
              <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "20px 24px", fontSize: "13px", lineHeight: "2.1", color: "#5a6880" }}>
                {[
                  ["1", "SoundAgent starts WebDAV server on configured port at tick startup"],
                  ["2", "On iPhone: Files app → Browse → ··· → Connect to Server"],
                  ["3", "Enter: http://[machine-ip]:8080"],
                  ["4", "Authenticate with configured username / password"],
                  ["5", "Inbox appears as a persistent network location in Files app"],
                  ["6", "User drops recordings directly into inbox from any app"],
                  ["7", "Next agent tick detects new files and begins processing"],
                ].map(([n, step]) => (
                  <div key={n} style={{ display: "flex", gap: "16px" }}>
                    <span style={{ color: "#4a9eff", minWidth: "20px" }}>{n}.</span>
                    <span>{step}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* TECH STACK TAB */}
        {activeTab === "stack" && (
          <div>
            {sectionLabel("Technology Stack")}
            {tableCard(
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                {theadRow(["Layer", "Technology", "Role"])}
                <tbody>
                  {STACK.map((s, i) => (
                    <tr key={i} style={{ borderTop: "1px solid #141c28" }}>
                      <td style={{ padding: "12px 20px", color: "#4a9eff", fontSize: "11px", width: "190px" }}>{s.layer}</td>
                      <td style={{ padding: "12px 20px", color: "#e8edf4", width: "230px" }}>{s.tech}</td>
                      <td style={{ padding: "12px 20px", color: "#5a6880" }}>{s.note}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div style={{ marginTop: "28px" }}>
              {sectionLabel("Python Dependencies")}
              <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "20px", fontSize: "12px", lineHeight: "1.9" }}>
                {[
                  ["anthropic", "Claude API client"],
                  ["pyyaml", "Config file parsing"],
                  ["watchdog", "Filesystem event monitoring"],
                  ["ffmpeg-python", "ffprobe wrapper"],
                  ["mutagen", "ID3/XMP metadata writing"],
                  ["wsgidav", "WebDAV server (mobile ingest)"],
                  ["aiofiles", "Async file I/O"],
                  ["tenacity", "Retry logic for API + network calls"],
                  ["fastapi", "Search API server (Phase 8)"],
                  ["uvicorn", "ASGI server (Phase 8)"],
                  ["alembic", "DB migrations"],
                ].map(([pkg, desc]) => (
                  <div key={pkg} style={{ display: "flex", gap: "16px" }}>
                    <span style={{ color: "#4a9eff", minWidth: "180px" }}>{pkg}</span>
                    <span style={{ color: "#2a3850" }}># {desc}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ marginTop: "28px" }}>
              {sectionLabel("External System Tools")}
              <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "20px", fontSize: "12px", lineHeight: "1.9" }}>
                {[
                  ["ffprobe", "FFmpeg", "Audio technical metadata extraction"],
                  ["rclone", "rclone.org", "Universal cloud sync/mount (70+ providers)"],
                  ["WinFsp", "winfsp.dev", "FUSE layer for rclone mount on Windows"],
                  ["bwfmetaedit", "MediaArea/FADGI", "BWF iXML chunk write + validation"],
                  ["Basehead Ultra", "baseheadinc.com", "Library front-end + Basehead Connect AAX"],
                ].map(([tool, src, desc]) => (
                  <div key={tool} style={{ display: "flex", gap: "12px" }}>
                    <span style={{ color: "#4a9eff", minWidth: "130px" }}>{tool}</span>
                    <span style={{ color: "#2a4060", minWidth: "150px" }}>[{src}]</span>
                    <span style={{ color: "#2a3850" }}># {desc}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ARCHITECTURE TAB */}
        {activeTab === "architecture" && (
          <div>
            {sectionLabel("Full Pipeline — Data Flow")}
            <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "24px 28px", fontSize: "12px", lineHeight: "2.3", marginBottom: "28px" }}>
              {[
                ["TICK START", "#4a9eff", "Cowork fires agent process"],
                ["1 · ADAPTER HEALTH", "#4a9eff", "Check each configured source — skip unavailable, log warning"],
                ["2 · SCAN", "#4a9eff", "Each active adapter delivers new/changed files to /inbox/"],
                ["3 · DEDUP", "#4a9eff", "SHA-256 hash → check DB → skip known files"],
                ["4 · VALIDATE", "#4a9eff", "Format/extension check → reject to /_errors/"],
                ["5 · STAGE", "#4a9eff", "Atomic copy to /_staging/ → ffprobe technical metadata"],
                ["6 · ENRICH", "#9b59b6", "Claude API: category, subcategory, tags, description, mood, BPM"],
                ["7 · EMBED", "#9b59b6", "Write iXML/BWF (WAV) · ID3 (MP3) · XMP sidecar into file"],
                ["8 · ROUTE", "#4caf50", "Rules engine: enriched metadata → target library path"],
                ["9 · DELIVER", "#4caf50", "Atomic move → Basehead import folder, fully tagged"],
                ["10 · CATALOGUE", "#4caf50", "Upsert DB record → FTS5 index → source + delivery annotation"],
                ["11 · REPORT", "#f5a623", "Tick summary per source adapter → Cowork log + summary.json"],
                ["TICK END", "#4a9eff", "Exit 0 (clean) or exit 1 (partial failure)"],
              ].map(([step, col, detail], i) => (
                <div key={i} style={{ display: "flex", gap: "20px" }}>
                  <span style={{ color: col, minWidth: "190px", fontWeight: "600" }}>{step}</span>
                  <span style={{ color: "#1e2a40" }}>→</span>
                  <span style={{ color: "#5a6880" }}>{detail}</span>
                </div>
              ))}
            </div>

            {sectionLabel("Library Folder Hierarchy")}
            <div style={{ background: "#0a0c0f", border: "1px solid #1a2030", borderRadius: "6px", padding: "20px 28px", fontSize: "12px", lineHeight: "2.1", marginBottom: "28px" }}>
              {[
                [0, "/SoundLibrary/", "#e8edf4"],
                [1, "_inbox/", "#4a9eff"],
                [1, "_staging/", "#4a9eff"],
                [1, "field/", "#9b59b6"],
                [2, "nature/   urban/   industrial/   interior/", "#5a4870"],
                [1, "sfx/", "#9b59b6"],
                [2, "impacts/   ambience/   foley/   designed/", "#5a4870"],
                [1, "music/", "#9b59b6"],
                [2, "loops/   stems/   beds/   stingers/", "#5a4870"],
                [1, "broadcast/", "#9b59b6"],
                [2, "idents/   vo/   transitions/", "#5a4870"],
                [1, "unclassified/", "#f5a623"],
                [1, "_errors/", "#e74c3c"],
                [1, "archive/", "#3a4860"],
                [1, "soundlibrary.db", "#4caf50"],
                [1, "soundagent.log", "#3a4860"],
                [1, "summary.json", "#3a4860"],
              ].map(([indent, text, color], i) => (
                <div key={i} style={{ paddingLeft: `${indent * 24}px`, color }}>{indent > 0 ? "├─ " : ""}{text}</div>
              ))}
            </div>

            {sectionLabel("Metadata Schema")}
            {tableCard(
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                {theadRow(["Field", "Type", "Source"])}
                <tbody>
                  {[
                    ["file_hash", "TEXT PK", "SHA-256"],
                    ["filename / path", "TEXT", "Filesystem"],
                    ["source_adapter", "TEXT", "Agent (which adapter delivered file)"],
                    ["format / codec", "TEXT", "ffprobe"],
                    ["duration_s", "REAL", "ffprobe"],
                    ["sample_rate / bit_depth / channels", "INTEGER", "ffprobe"],
                    ["category / subcategory", "TEXT", "Claude API"],
                    ["ucs_catid", "TEXT", "UCS mapper"],
                    ["description", "TEXT", "Claude API"],
                    ["tags", "JSON array", "Claude API"],
                    ["mood / energy", "TEXT", "Claude API"],
                    ["bpm / key", "TEXT", "Claude API (music only)"],
                    ["enrichment_confidence", "REAL 0–1", "Agent"],
                    ["date_added / last_seen", "TIMESTAMP", "Agent"],
                    ["basehead_delivered", "BOOLEAN", "Agent"],
                  ].map(([field, type, source], i) => (
                    <tr key={i} style={{ borderTop: "1px solid #141c28" }}>
                      <td style={{ padding: "9px 16px", color: "#c8d0db", fontFamily: "monospace" }}>{field}</td>
                      <td style={{ padding: "9px 16px", color: "#4a9eff", fontFamily: "monospace", fontSize: "11px" }}>{type}</td>
                      <td style={{ padding: "9px 16px", color: "#5a6880" }}>{source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
