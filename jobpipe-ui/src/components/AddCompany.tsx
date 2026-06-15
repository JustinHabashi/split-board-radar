import { useState } from "react";
import { addCompany } from "../api";

const ATS_OPTIONS = ["greenhouse", "lever", "ashby", "workday", "fallback", "?"];
const CANDIDATE_OPTIONS = ["engineer", "scientist", "both"];

const FIELD_STYLE = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 6,
  border: "1px solid #d1d5db",
  fontSize: 14,
  boxSizing: "border-box" as const,
};

const LABEL_STYLE = {
  display: "block",
  fontSize: 13,
  fontWeight: 600,
  color: "#374151",
  marginBottom: 4,
};

export default function AddCompany() {
  const [form, setForm] = useState({
    name: "",
    candidate: "engineer",
    sector: "",
    careers_url: "",
    ats: "?",
    active: true,
  });
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function set(field: string, value: string | boolean) {
    setForm((f) => ({ ...f, [field]: value }));
    setSuccess(null);
    setError(null);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim() || !form.careers_url.trim()) {
      setError("Company name and careers URL are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      await addCompany({ ...form, sector: form.sector || undefined });
      setSuccess(`"${form.name}" added and seeded successfully.`);
      setForm({ name: "", candidate: "engineer", sector: "", careers_url: "", ats: "?", active: true });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ maxWidth: 520 }}>
      {success && (
        <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: 6, padding: "10px 14px", marginBottom: 20, fontSize: 13, color: "#166534" }}>
          {success}
        </div>
      )}
      {error && (
        <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, padding: "10px 14px", marginBottom: 20, fontSize: 13, color: "#b91c1c" }}>
          {error}
        </div>
      )}

      <div style={{ display: "grid", gap: 16 }}>
        <div>
          <label style={LABEL_STYLE}>Company Name *</label>
          <input style={FIELD_STYLE} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Acme Corp" />
        </div>

        <div>
          <label style={LABEL_STYLE}>Candidate *</label>
          <select style={FIELD_STYLE} value={form.candidate} onChange={(e) => set("candidate", e.target.value)}>
            {CANDIDATE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>

        <div>
          <label style={LABEL_STYLE}>Sector</label>
          <input style={FIELD_STYLE} value={form.sector} onChange={(e) => set("sector", e.target.value)} placeholder="e.g. fintech, biotech" />
        </div>

        <div>
          <label style={LABEL_STYLE}>Careers URL *</label>
          <input style={FIELD_STYLE} value={form.careers_url} onChange={(e) => set("careers_url", e.target.value)} placeholder="https://company.com/careers" type="url" />
        </div>

        <div>
          <label style={LABEL_STYLE}>ATS</label>
          <select style={FIELD_STYLE} value={form.ats} onChange={(e) => set("ats", e.target.value)}>
            {ATS_OPTIONS.map((o) => <option key={o} value={o}>{o === "?" ? "? (auto-detect)" : o}</option>)}
          </select>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="checkbox"
            id="active"
            checked={form.active}
            onChange={(e) => set("active", e.target.checked)}
            style={{ width: 16, height: 16, cursor: "pointer" }}
          />
          <label htmlFor="active" style={{ fontSize: 14, cursor: "pointer" }}>Active (include in digest runs)</label>
        </div>

        <button
          type="submit"
          disabled={submitting}
          style={{
            padding: "10px 20px",
            background: submitting ? "#6b7280" : "#2563eb",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            cursor: submitting ? "not-allowed" : "pointer",
            fontWeight: 600,
            fontSize: 14,
          }}
        >
          {submitting ? "Saving…" : "Add Company"}
        </button>
      </div>
    </form>
  );
}
