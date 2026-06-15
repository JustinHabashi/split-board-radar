import { useState } from "react";
import AddCompany from "./components/AddCompany";
import MatchesView from "./components/MatchesView";

type Tab = "matches" | "add-company";

export default function App() {
  const [tab, setTab] = useState<Tab>("matches");

  return (
    <div style={{ minHeight: "100vh", background: "#f8fafc", fontFamily: "system-ui, sans-serif" }}>
      <header style={{ background: "#1e293b", color: "#f8fafc", padding: "0 32px" }}>
        <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", alignItems: "center", gap: 32 }}>
          <h1 style={{ fontSize: 18, fontWeight: 700, margin: "0 16px 0 0", padding: "18px 0" }}>
            JobPipe
          </h1>
          {(["matches", "add-company"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: "none",
                border: "none",
                color: tab === t ? "#60a5fa" : "#94a3b8",
                borderBottom: tab === t ? "2px solid #60a5fa" : "2px solid transparent",
                padding: "18px 4px",
                cursor: "pointer",
                fontSize: 14,
                fontWeight: tab === t ? 600 : 400,
              }}
            >
              {t === "matches" ? "Matches" : "Add Company"}
            </button>
          ))}
        </div>
      </header>

      <main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 32px" }}>
        {tab === "matches" && <MatchesView />}
        {tab === "add-company" && (
          <>
            <h2 style={{ marginTop: 0, fontSize: 20, fontWeight: 600 }}>Add Company</h2>
            <p style={{ color: "#6b7280", marginTop: 0, marginBottom: 24, fontSize: 14 }}>
              The company will be appended to companies.csv and seeded into the database immediately.
              Set ATS to <strong>? (auto-detect)</strong> if you don't know the board token — the resolver will detect it on the next digest run.
            </p>
            <AddCompany />
          </>
        )}
      </main>
    </div>
  );
}
