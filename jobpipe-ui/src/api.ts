const BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8090";

export interface Match {
  company: string;
  location: string | null;
  job_title: string;
  score: number;
  candidate: string;
  reason: string;
  url: string;
}

export interface DigestStatus {
  status: "idle" | "running" | "error";
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface Company {
  name: string;
  candidate: string;
  sector: string;
  careers_url: string;
  ats: string;
  board_token: string;
  active: string;
}

export interface CompanyIn {
  name: string;
  candidate: string;
  sector?: string;
  careers_url: string;
  ats?: string;
  active: boolean;
}

export async function getMatches(candidate?: string, threshold = 70): Promise<Match[]> {
  const params = new URLSearchParams({ threshold: String(threshold) });
  if (candidate) params.set("candidate", candidate);
  const res = await fetch(`${BASE}/api/matches?${params}`);
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.matches;
}

export async function getDigestStatus(): Promise<DigestStatus> {
  const res = await fetch(`${BASE}/api/digest/status`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function triggerDigest(): Promise<void> {
  const res = await fetch(`${BASE}/api/digest`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export async function addCompany(company: CompanyIn): Promise<void> {
  const res = await fetch(`${BASE}/api/companies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(company),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? res.statusText);
  }
}

export async function getCompanies(): Promise<Company[]> {
  const res = await fetch(`${BASE}/api/companies`);
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.companies;
}
