const RISK_LABELS = {
  red: "Высокий риск",
  yellow: "Повышенный риск",
  green: "Норма",
};

function deviationValue(item) {
  return Number(item.deviation_s ?? item.prediction_s);
}

function formatDeviation(value) {
  const seconds = Math.round(Number(value));
  if (!Number.isFinite(seconds)) return "—";

  const sign = seconds > 0 ? "+" : seconds < 0 ? "−" : "";
  const absolute = Math.abs(seconds);
  const minutes = Math.floor(absolute / 60);
  const rest = absolute % 60;

  if (minutes === 0) return `${sign}${rest} сек`;
  return `${sign}${minutes}:${String(rest).padStart(2, "0")}`;
}

function directionLabel(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds === 0) return "По графику";
  return seconds > 0 ? "Опоздание" : "Опережение";
}

function riskClass(item) {
  if (item.status && item.status !== "ok") return "stale";
  return item.risk || "green";
}

export default function IncidentList({ predictions, selectedUnitId, onSelect }) {
  const ordered = [...predictions].sort((a, b) => {
    const priority = { red: 0, yellow: 1, stale: 2, green: 3 };
    const aRisk = riskClass(a);
    const bRisk = riskClass(b);
    const riskDiff = (priority[aRisk] ?? 9) - (priority[bRisk] ?? 9);
    if (riskDiff !== 0) return riskDiff;

    return Math.abs(deviationValue(b) || 0) - Math.abs(deviationValue(a) || 0);
  });

  if (!ordered.length) {
    return <div className="empty-list">Нет транспортных средств для отображения.</div>;
  }

  return (
    <div className="incident-list">
      {ordered.map((item) => {
        const active = String(item.unit_id) === String(selectedUnitId);
        const tone = riskClass(item);
        const degraded = item.status && item.status !== "ok";
        const deviation = deviationValue(item);

        return (
          <button
            type="button"
            className={`incident-row ${active ? "active" : ""}`}
            key={item.unit_id}
            onClick={() => onSelect(item.unit_id)}
          >
            <span className={`vehicle-dot ${tone}`} aria-hidden="true" />
            <span className="incident-copy">
              <strong>ТС {item.unit_id}</strong>
              <small>
                {degraded
                  ? "Последнее известное состояние"
                  : `${directionLabel(deviation)} · ${item.cause || RISK_LABELS[item.risk] || "Нет данных"}`}
              </small>
            </span>
            <span className={`deviation-value ${tone}`}>
              {formatDeviation(deviation)}
            </span>
          </button>
        );
      })}
    </div>
  );
}
