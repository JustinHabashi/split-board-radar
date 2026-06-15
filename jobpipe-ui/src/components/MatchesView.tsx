import { useEffect, useRef, useState } from "react";
import { getDigestStatus, getMatches, triggerDigest } from "../api";
import type { DigestStatus, Match } from "../api";

const POLL_MS = 5000;

function scoreColor(score: number): string {
  if (score >= 80) return "#16a34a";
  if (score >= 70) return "#ca8a04";
  return "#6b7280";
}

function scoreBadge(score: number) {
  return (
    <span style={{
      display: "inline-block",
      minWidth: 36,
      padding: "2px 7px",
      borderRadius: 12,
      background: score >= 80 ? "#dcfce7" : score >= 70 ? "#fef9c3" : "#f3f4f6",
      color: scoreColor(score),
      fontWeight: 700,
      fontSize: 13,
      textAlign: "center",
    }}>
      {score}
    </span>
  );
}

function MatchRow({ match }: { match: Match }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        onClick={() => setExpanded((e) => !e)}
        style={{ borderBottom: expanded ? "none" : "1px solid #f3f4f6", cursor: "pointer", background: expanded ? "#fafafa" : "white" }}
        onMouseEnter={(e) => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = "#f9fafb"; }}
        onMouseLeave={(e) => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = "white"; }}
      >
        <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>{scoreBadge(match.score)}</td>
        <td style={{ padding: "8px 12px", whiteSpace: "nowrap", fontWeight: 500 }}>{match.company}</td>
        <td style={{ padding: "8px 12px" }}>{match.job_title}</td>
        <td style={{ padding: "8px 12px", whiteSpace: "nowrap", color: "#6b7280", fontSize: 13 }}>{match.location ?? "—"}</td>
        <td style={{ padding: "8px 12px", whiteSpace: "nowrap", fontSize: 13 }}>
          <span style={{
            display: "inline-block",
            padding: "1px 8px",
            borderRadius: 10,
            background: match.candidate === "engineer" ? "#eff6ff" : "#fdf4ff",
            color: match.candidate === "engineer" ? "#1d4ed8" : "#7e22ce",
            fontSize: 12,
            fontWeight: 500,
          }}>
            {match.candidate}
          </span>
        </td>
        <td style={{ padding: "8px 12px", whiteSpace: "nowrap" }}>
          {match.url
            ? <a href={match.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} style={{ color: "#2563eb", fontSize: 13 }}>Apply →</a>
            : "—"}
        </td>
        <td style={{ padding: "8px 12px", color: "#9ca3af", fontSize: 13, userSelect: "none" }}>
          {expanded ? "▲" : "▼"}
        </td>
      </tr>
      {expanded && (
        <tr style={{ borderBottom: "1px solid #f3f4f6", background: "#fafafa" }}>
          <td colSpan={7} style={{ padding: "0 12px 12px 12px" }}>
            <div style={{ fontSize: 13, color: "#374151", lineHeight: 1.6, paddingLeft: 2 }}>
              <span style={{ fontWeight: 600, color: "#6b7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Reason — </span>
              {match.reason}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function MatchesView() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [status, setStatus] = useState<DigestStatus | null>(null);
  const [candidateFilter, setCandidateFilter] = useState("all");
  const [threshold, setThreshold] = useState(70);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchMatches() {
    try {
      const cand = candidateFilter === "all" ? undefined : candidateFilter;
      setMatches(await getMatches(cand, threshold));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function fetchStatus() {
    try {
      const s = await getDigestStatus();
      setStatus(s);
      if (s.status !== "running") {
        stopPolling();
        setLoading(false);
        fetchMatches();
      }
    } catch {
      stopPolling();
      setLoading(false);
    }
  }

  function startPolling() {
    if (pollRef.current) return;
    pollRef.current = setInterval(fetchStatus, POLL_MS);
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  async function handleRunDigest() {
    setError(null);
    try {
      await triggerDigest();
      setLoading(true);
      startPolling();
      fetchStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    fetchMatches();
    fetchStatus();
    return () => stopPolling();
  }, []);

  useEffect(() => { fetchMatches(); }, [candidateFilter, threshold]);

  const isRunning = status?.status === "running";

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <button
          onClick={handleRunDigest}
          disabled={isRunning || loading}
          style={{
            padding: "7px 16px",
            background: isRunning ? "#6b7280" : "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: isRunning ? "not-allowed" : "pointer",
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          {isRunning ? "⏳ Running…" : "▶ Run Digest"}
        </button>

        <select
          value={candidateFilter}
          onChange={(e) => setCandidateFilter(e.target.value)}
          style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: 13 }}
        >
          <option value="all">All candidates</option>
          <option value="engineer">Engineer</option>
          <option value="scientist">Scientist</option>
        </select>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
          Min score:
          <input
            type="number"
            min={0}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            style={{ width: 54, padding: "4px 8px", borderRadius: 6, border: "1px solid #d1d5db", fontSize: 13 }}
          />
        </label>

        <span style={{ marginLeft: "auto", fontSize: 12, color: "#9ca3af" }}>
          {matches.length} match{matches.length !== 1 ? "es" : ""}
          {status?.completed_at && ` · last run ${new Date(status.completed_at).toLocaleString()}`}
        </span>
      </div>

      {status?.status === "error" && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#b91c1c" }}>
          Digest error: {status.error}
        </div>
      )}
      {error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#b91c1c" }}>
          {error}
        </div>
      )}

      {matches.length === 0 ? (
        <p style={{ color: "#6b7280", fontSize: 14 }}>No matches above threshold. Run the digest to populate results.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead>
              <tr style={{ background: "#f9fafb", textAlign: "left" }}>
                {["Score", "Company", "Job Title", "Location", "Candidate", "Link", ""].map((h, i) => (
                  <th key={i} style={{ padding: "8px 12px", borderBottom: "2px solid #e5e7eb", fontSize: 12, fontWeight: 600, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matches.map((m, i) => <MatchRow key={i} match={m} />)}
            </tbody>
          </table>
          <p style={{ fontSize: 12, color: "#9ca3af", marginTop: 10 }}>Click any row to expand the match reason.</p>
        </div>
      )}
    </div>
  );
}
