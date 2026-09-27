const API_PREFIX = import.meta.env.VITE_API_PREFIX || "/api";

async function getJson(path) {
  const response = await fetch(`${API_PREFIX}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`${path}: HTTP ${response.status}`);
  }

  return response.json();
}

export async function loadDashboardData() {
  const [system, metrics, vehicles, predictions, trails] = await Promise.all([
    getJson("/system/status"),
    getJson("/metrics"),
    getJson("/vehicles"),
    getJson("/predictions"),
    getJson("/trails"),
  ]);

  return { system, metrics, vehicles, predictions, trails };
}


export async function loadEvidenceMetrics() {
  const [metrics, performance, horizon] = await Promise.all([
    getJson("/metrics"),
    getJson("/audit/performance"),
    getJson("/audit/horizon"),
  ]);

  return { metrics, performance, horizon };
}
