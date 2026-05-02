import { useState } from "react";

const STEPS = [
  {
    id: 1,
    section: "INSTALL",
    title: "Install & Launch Basehead",
    tasks: [
      { label: "Run the Basehead installer you downloaded", note: "Accept defaults — installs Basehead Ultra trial + Basehead Connect AAX plugin" },
      { label: "Launch Basehead from Start Menu", note: null },
      { label: "At the licence screen, select Start Free Trial", note: "15-day full Ultra feature set — no credit card needed" },
      { label: "Create a Basehead account if prompted, or log in", note: "Required for licence validation" },
      { label: "Confirm Ultra features are active", note: "Check top-right: should show 'Ultra' not 'Lite'" },
    ],
  },
  {
    id: 2,
    section: "LAYOUT",
    title: "Understand the UI",
    tasks: [
      { label: "NodeTree (left panel) — your library structure and imports live here", note: "Think of it like Windows Explorer for your sound library" },
      { label: "Search Bar (top) — keyword + boolean search across all indexed files", note: "Supports AND, OR, NOT operators" },
      { label: "Results List (centre) — matched files with metadata columns", note: "Right-click column headers to add/remove fields" },
      { label: "Transport / Waveform (bottom) — playback, waveform view, metadata editor", note: "Press Spacebar to play selected file" },
      { label: "Ctrl+T to open a new Search Tab", note: "Pin tabs for different search contexts — e.g. one for field recordings, one for SFX" },
    ],
  },
  {
    id: 3,
    section: "IMPORT",
    title: "Import Local Libraries",
    tasks: [
      {
        label: "Import D:\\Field Recordings",
        note: "NodeTree → right-click Imports → Add Import Folder → browse to D:\\Field Recordings",
        path: "D:\\Field Recordings",
        tag: "local",
      },
      {
        label: "Import C:\\Users\\robin\\Music\\Field Recordings",
        note: "Repeat: right-click Imports → Add Import Folder → browse to path",
        path: "C:\\Users\\robin\\Music\\Field Recordings",
        tag: "local",
      },
      { label: "Let Basehead index both folders", note: "May take a few minutes depending on file count — progress shown in status bar" },
      { label: "Verify files appear in Results List", note: "Type a broad keyword in search bar to confirm indexing is complete" },
      { label: "Assign a Group colour to each import to distinguish them", note: "Right-click the Import in NodeTree → Assign Group → pick a colour" },
    ],
  },
  {
    id: 4,
    section: "GDRIVE",
    title: "Connect Google Drive Libraries",
    intro: "Basehead cannot mount Google Drive natively. Two options — pick one.",
    options: [
      {
        label: "Option A — Google Drive for Desktop (recommended)",
        steps: [
          "Download and install Google Drive for Desktop from drive.google.com",
          "Sign in — your Drive appears as a mapped drive (usually G:\\ or similar)",
          "In Basehead: Add Import Folder → navigate to the mapped drive paths below",
          "Basehead treats them as local folders from here",
        ],
        paths: [
          "G:\\My Drive\\Field recordings",
          "G:\\My Drive\\To sort",
        ],
        note: "Both folders confirmed on your G: drive. Add each as a separate Import in Basehead so you can filter or colour-code them independently.",
      },
      {
        label: "Option B — rclone mount (for SoundAgent integration later)",
        steps: [
          "Install rclone and configure a Google Drive remote: rclone config",
          "Mount to a local path: rclone mount gdrive: G:\\ --vfs-cache-mode writes",
          "Add the mounted paths as Import Folders in Basehead as above",
          "This is the same adapter SoundAgent will use — good to test early",
        ],
        paths: [],
        note: "Option B is slightly more technical but sets up the rclone integration you'll need for SoundAgent anyway.",
      },
    ],
  },
  {
    id: 5,
    section: "INBOX",
    title: "Create SoundAgent Inbox & Delivery Folder",
    tasks: [
      {
        label: "Create the SoundAgent drop folder and library folder structure",
        note: "Drop folder is where you place files for the agent to pick up. Library is where processed files land.",
        code: [
          "mkdir \"D:\\SoundLibrary_Inbox\"",
          "mkdir \"D:\\Sound Library\"",
          "mkdir \"D:\\Sound Library\\_inbox\"",
          "mkdir \"D:\\Sound Library\\_staging\"",
          "mkdir \"D:\\Sound Library\\_errors\"",
          "mkdir \"D:\\Sound Library\\field\"",
          "mkdir \"D:\\Sound Library\\sfx\"",
          "mkdir \"D:\\Sound Library\\music\"",
          "mkdir \"D:\\Sound Library\\broadcast\"",
          "mkdir \"D:\\Sound Library\\unclassified\"",
        ],
      },
      { label: "Add D:\\Sound Library as an Import Folder in Basehead", note: "NodeTree → Imports → Add Import Folder → D:\\Sound Library — this is where processed files land" },
      { label: "This is the Basehead delivery target — agent delivers renamed files here, Basehead sees them on rescan", note: "Delivered filenames follow UCS+slug format: WTHR_rain-woodland-wind-light_96k24b.wav. The original filename is preserved in the iXML ORIGFILENAME field." },
      { label: "Test it: manually copy a WAV file into D:\\Sound Library\\field and rename it WTHR_test-file_48k24b.wav", note: "This mimics the exact format SoundAgent delivers — search 'WTHR' in Basehead to find it" },
      { label: "Right-click the Sound Library import in NodeTree → Scan for New Files", note: "File should appear in results — confirms the delivery pipeline works" },
    ],
  },
  {
    id: 6,
    section: "METADATA",
    title: "Configure Metadata Columns",
    tasks: [
      { label: "Right-click the Results List column header row → select columns to display", note: "Recommended: Filename, Category, Description, Duration, Sample Rate, Bit Depth, Channels, BPM, Tags, Original Filename" },
      { label: "Enable the iXML / Description column", note: "This is where SoundAgent's Claude-generated descriptions will appear once embedded" },
      { label: "Enable Category and Sub Category columns", note: "UCS fields — will be populated by SoundAgent's enrichment pipeline" },
      { label: "Enable the Tags column", note: "Multi-value field — SoundAgent writes an array of descriptive tags here" },
      { label: "Enable the Original Filename (ORIGFILENAME) iXML column", note: "SoundAgent embeds the pre-rename source filename here — useful for tracing a delivered file back to the original recording (e.g. recording_047.wav)" },
      { label: "Drag columns to preferred order, then right-click → Save Column Layout", note: "Saves this as your default view" },
    ],
  },
  {
    id: 7,
    section: "DAW",
    title: "Set Up Basehead Connect for Pro Tools",
    tasks: [
      { label: "Open Pro Tools", note: null },
      { label: "Create a new session or open an existing one", note: null },
      { label: "Insert the Basehead Connect plugin on any audio track", note: "Insert → Instrument → Basehead Connect (AAX)" },
      { label: "In Basehead: click the BC button in the Transport bar", note: "BC button is in the bottom-left of the transport section — turns green when connected" },
      { label: "Test spot to cursor: find a file in Basehead, press S", note: "File should appear at the cursor position in your Pro Tools session" },
      { label: "Test spot to bin: find a file in Basehead, press B", note: "File should appear in the Pro Tools clip bin without placing it on a track" },
      { label: "Test handles: in Basehead Options, set handle length (e.g. 500ms each side)", note: "Spotted files will include pre/post handles for editing headroom" },
    ],
  },
  {
    id: 8,
    section: "SEARCH",
    title: "Test Search & Tagging",
    tasks: [
      { label: "Run a keyword search across all imports", note: "Try broad terms first: 'rain', 'wind', 'birds' — confirm results span all import folders" },
      { label: "Test boolean search: rain AND forest", note: "Results should narrow to files matching both terms" },
      { label: "Test exclude: rain NOT indoor", note: "Filters out files containing 'indoor' in their metadata" },
      { label: "Open the metadata editor on a file (M key)", note: "Manually add a Category and Description to one file to test the field layout before SoundAgent writes them" },
      { label: "Create a Taglist for your field recording workflow", note: "Options → Taglists → New — add your most-used descriptors for quick tagging" },
      { label: "Test a Search Tab workflow: Ctrl+T for a new tab, search a different term", note: "Keep multiple searches open side by side during a session" },
    ],
  },
  {
    id: 9,
    section: "VERIFY",
    title: "End-to-End Delivery Test",
    intro: "Manual simulation of what SoundAgent will do automatically.",
    tasks: [
      { label: "Pick a WAV file from your existing library", note: null },
      { label: "Manually write test metadata using bwfmetaedit or Basehead's editor", note: "Category: field / Nature, Description: Test delivery from SoundAgent pipeline, ORIGFILENAME: recording_047.wav" },
      { label: "Rename the file to match SoundAgent's output format and copy it into D:\\Sound Library\\field", note: "Use a name like AMB-NATU_woodland-rain-heavy_96k24b.wav — UCS code, slug, sample rate, bit depth, extension. This is exactly what the agent delivers.", code: ["rename recording_047.wav AMB-NATU_woodland-rain-heavy_96k24b.wav", "copy AMB-NATU_woodland-rain-heavy_96k24b.wav \"D:\\Sound Library\\field\\\""] },
      { label: "In Basehead: right-click SoundAgent import → Scan for New Files", note: null },
      { label: "Confirm the file appears with metadata visible and ORIGFILENAME shows recording_047.wav", note: "If the UCS filename and ORIGFILENAME both display correctly, the rename + iXML embedding strategy is confirmed end-to-end" },
      { label: "Spot the file into Pro Tools via Basehead Connect", note: "Full loop confirmed: agent rename → iXML embed → Basehead → DAW" },
    ],
  },
];

export default function BaseheadGuide() {
  const [activeStep, setActiveStep] = useState(1);
  const [checked, setChecked] = useState({});

  const step = STEPS.find((s) => s.id === activeStep);

  const toggleCheck = (stepId, taskIdx) => {
    const key = `${stepId}-${taskIdx}`;
    setChecked((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const stepComplete = (s) => {
    const allTasks = s.tasks || [];
    if (allTasks.length === 0) return false;
    return allTasks.every((_, i) => checked[`${s.id}-${i}`]);
  };

  const totalTasks = STEPS.reduce((acc, s) => acc + (s.tasks?.length || 0), 0);
  const completedTasks = Object.values(checked).filter(Boolean).length;
  const pct = Math.round((completedTasks / totalTasks) * 100);

  return (
    <div style={{
      fontFamily: "'JetBrains Mono','Fira Mono','Courier New',monospace",
      background: "#0d0f12",
      color: "#c8d0db",
      minHeight: "100vh",
    }}>
      {/* Header */}
      <div style={{ borderBottom: "1px solid #1e2530", padding: "24px 32px 20px", background: "#0a0c0f" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "16px", marginBottom: "6px" }}>
          <span style={{ fontSize: "11px", color: "#f5a623", letterSpacing: "3px", textTransform: "uppercase" }}>SETUP GUIDE</span>
          <span style={{ fontSize: "11px", color: "#2a3040" }}>Basehead Ultra — 15-day Trial</span>
        </div>
        <h1 style={{ margin: "0 0 4px", fontSize: "26px", color: "#e8edf4", fontWeight: "700", letterSpacing: "-0.5px" }}>
          Basehead × SoundAgent
        </h1>
        <p style={{ margin: "0 0 16px", fontSize: "13px", color: "#5a6880" }}>
          Configure Basehead for testing with your existing libraries and the SoundAgent delivery pipeline
        </p>
        {/* Progress */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          <div style={{ flex: 1, background: "#131820", borderRadius: "3px", height: "6px", overflow: "hidden" }}>
            <div style={{ width: `${pct}%`, height: "100%", background: "#f5a623", borderRadius: "3px", transition: "width 0.3s" }} />
          </div>
          <span style={{ fontSize: "11px", color: "#f5a623", minWidth: "60px" }}>{completedTasks}/{totalTasks} done</span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", minHeight: "calc(100vh - 130px)" }}>
        {/* Step nav */}
        <div style={{ borderRight: "1px solid #1e2530", padding: "20px 0" }}>
          {STEPS.map((s) => {
            const done = stepComplete(s);
            const active = activeStep === s.id;
            return (
              <button key={s.id} onClick={() => setActiveStep(s.id)} style={{
                display: "block", width: "100%", background: active ? "#131820" : "none",
                border: "none",
                borderLeft: active ? "3px solid #f5a623" : "3px solid transparent",
                color: active ? "#e8edf4" : done ? "#3a5a3a" : "#4a5870",
                cursor: "pointer", padding: "10px 16px", textAlign: "left",
                fontSize: "11px", fontFamily: "inherit", marginBottom: "2px",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{
                    fontSize: "9px", letterSpacing: "1.5px",
                    color: active ? "#f5a623" : done ? "#4caf50" : "#2a3850",
                  }}>{done ? "✓ " : ""}{s.section}</span>
                </div>
                <div style={{ lineHeight: "1.3", marginTop: "2px" }}>{s.title}</div>
              </button>
            );
          })}
        </div>

        {/* Step content */}
        <div style={{ padding: "28px 32px", maxWidth: "760px" }}>
          {step && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "8px" }}>
                <span style={{ fontSize: "10px", color: "#f5a623", background: "#1a1000", border: "1px solid #3a2000", padding: "3px 10px", borderRadius: "3px", letterSpacing: "1.5px" }}>
                  {step.section}
                </span>
                <h2 style={{ margin: 0, fontSize: "18px", color: "#e8edf4", fontWeight: "600" }}>{step.title}</h2>
                <span style={{ marginLeft: "auto", fontSize: "10px", color: "#2a3850" }}>
                  {step.id} / {STEPS.length}
                </span>
              </div>

              {step.intro && (
                <p style={{ fontSize: "13px", color: "#5a7890", margin: "0 0 20px", lineHeight: "1.6", borderLeft: "2px solid #1e2d40", paddingLeft: "14px" }}>
                  {step.intro}
                </p>
              )}

              {/* Option blocks (step 4) */}
              {step.options && step.options.map((opt, oi) => (
                <div key={oi} style={{ background: "#0d1118", border: "1px solid #1a2030", borderRadius: "6px", padding: "18px 20px", marginBottom: "16px" }}>
                  <div style={{ fontSize: "12px", color: "#4a9eff", marginBottom: "12px", fontWeight: "600" }}>{opt.label}</div>
                  {opt.steps.map((os, si) => (
                    <div key={si} style={{ display: "flex", gap: "10px", marginBottom: "8px", alignItems: "flex-start" }}>
                      <span style={{ color: "#f5a623", minWidth: "18px", fontSize: "11px", marginTop: "2px" }}>{si + 1}.</span>
                      <span style={{ fontSize: "13px", color: "#9aacbe", lineHeight: "1.5" }}>{os}</span>
                    </div>
                  ))}
                  {opt.paths.length > 0 && (
                    <div style={{ marginTop: "12px", background: "#0a0c0f", borderRadius: "4px", padding: "12px 14px" }}>
                      {opt.paths.map((p, pi) => (
                        <div key={pi} style={{ fontSize: "11px", color: "#4a9eff", fontFamily: "monospace", marginBottom: pi < opt.paths.length - 1 ? "4px" : "0" }}>{p}</div>
                      ))}
                    </div>
                  )}
                  {opt.note && (
                    <div style={{ marginTop: "10px", fontSize: "12px", color: "#5a6880", fontStyle: "italic" }}>ℹ {opt.note}</div>
                  )}
                </div>
              ))}

              {/* Task list */}
              {step.tasks && step.tasks.map((task, ti) => {
                const key = `${step.id}-${ti}`;
                const done = checked[key];
                return (
                  <div key={ti} onClick={() => toggleCheck(step.id, ti)} style={{
                    background: done ? "#0a1a0a" : "#0d1118",
                    border: `1px solid ${done ? "#1a3a1a" : "#1a2030"}`,
                    borderRadius: "6px", padding: "14px 16px", marginBottom: "8px",
                    cursor: "pointer", transition: "all 0.15s",
                  }}>
                    <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                      <div style={{
                        width: "18px", height: "18px", borderRadius: "3px", flexShrink: 0, marginTop: "1px",
                        background: done ? "#4caf50" : "#0a0c10",
                        border: `1px solid ${done ? "#4caf50" : "#2a3a50"}`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: "11px", color: "#0a0c0f",
                      }}>
                        {done ? "✓" : ""}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: "13px", color: done ? "#4a7a4a" : "#c8d0db", lineHeight: "1.4", textDecoration: done ? "line-through" : "none" }}>
                          {task.label}
                        </div>
                        {task.path && (
                          <div style={{ marginTop: "6px", fontSize: "11px", color: "#4a9eff", fontFamily: "monospace", background: "#0a1020", display: "inline-block", padding: "2px 8px", borderRadius: "3px" }}>
                            {task.path}
                          </div>
                        )}
                        {task.code && (
                          <div style={{ marginTop: "8px", background: "#0a0c0f", borderRadius: "4px", padding: "10px 12px" }}>
                            {task.code.map((line, li) => (
                              <div key={li} style={{ fontSize: "11px", color: "#4a9eff", fontFamily: "monospace", marginBottom: li < task.code.length - 1 ? "3px" : "0" }}>{line}</div>
                            ))}
                          </div>
                        )}
                        {task.note && (
                          <div style={{ marginTop: "6px", fontSize: "12px", color: "#3a5060", lineHeight: "1.4" }}>
                            ↳ {task.note}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}

              {/* Nav buttons */}
              <div style={{ display: "flex", gap: "12px", marginTop: "24px" }}>
                {activeStep > 1 && (
                  <button onClick={() => setActiveStep(activeStep - 1)} style={{
                    background: "none", border: "1px solid #1e2530", color: "#4a5870",
                    padding: "9px 18px", borderRadius: "4px", cursor: "pointer",
                    fontSize: "12px", fontFamily: "inherit",
                  }}>← Previous</button>
                )}
                {activeStep < STEPS.length && (
                  <button onClick={() => setActiveStep(activeStep + 1)} style={{
                    background: "#0a1828", border: "1px solid #1e3050", color: "#4a9eff",
                    padding: "9px 18px", borderRadius: "4px", cursor: "pointer",
                    fontSize: "12px", fontFamily: "inherit", marginLeft: "auto",
                  }}>Next →</button>
                )}
                {activeStep === STEPS.length && (
                  <div style={{ marginLeft: "auto", fontSize: "13px", color: "#4caf50", padding: "9px 0" }}>
                    {pct === 100 ? "✓ All steps complete — Basehead is ready for SoundAgent" : `${pct}% complete`}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
