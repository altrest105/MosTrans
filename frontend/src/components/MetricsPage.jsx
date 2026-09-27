import { useEffect, useMemo, useState } from "react";
import { Activity, Clock3, Gauge, ShieldCheck, TimerReset } from "lucide-react";
import { loadEvidenceMetrics } from "../api";

const REFRESH_MS = 2000;

const STATIC_EVIDENCE = {
  testMaeS: 55.653917768087595,
  baselineMaeS: 93.35977337110482,
};

function number(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—";
}

function percent(value, digits = 1) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}%` : "—";
}

function milliseconds(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  if (parsed < 10) return `${parsed.toFixed(2)} мс`;
  if (parsed < 100) return `${parsed.toFixed(1)} мс`;
  return `${Math.round(parsed)} мс`;
}

function metricTone(ok, hasData = true) {
  if (!hasData) return "neutral";
  return ok ? "good" : "warning";
}

function MetricCard({ icon: Icon, label, value, note, tone = "neutral", subvalue }) {
  return (
    <article className={`evidence-card ${tone}`}>
      <div className="evidence-card-head">
        <span className="evidence-icon"><Icon size={18} /></span>
      </div>
      <span className="evidence-label">{label}</span>
      <strong className="evidence-value">{value}</strong>
      {subvalue ? <span className="evidence-subvalue">{subvalue}</span> : null}
      {note ? <p>{note}</p> : null}
    </article>
  );
}

export default function MetricsPage() {
  const [runtime, setRuntime] = useState(null);

  useEffect(() => {
    let active = true;

    async function refresh() {
      try {
        const next = await loadEvidenceMetrics();
        if (!active) return;
        setRuntime(next);
      } catch {
        if (!active) return;
        setRuntime(null);
      }
    }

    refresh();
    const timer = window.setInterval(refresh, REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const improvement = useMemo(() => (
    (STATIC_EVIDENCE.baselineMaeS - STATIC_EVIDENCE.testMaeS)
      / STATIC_EVIDENCE.baselineMaeS * 100
  ), []);

  const metrics = runtime?.metrics || {};
  const performance = runtime?.performance || {};
  const horizon = runtime?.horizon || {};
  const e2e = performance?.details?.end_to_end || metrics?.latency?.end_to_end || {};
  const ml = performance?.details?.ml || metrics?.latency?.ml || {};
  const horizonMetrics = horizon?.metrics || metrics?.horizon || {};
  const noHindsight = horizon?.no_hindsight || metrics?.no_hindsight || {};

  const horizonSamples = Number(horizonMetrics?.compliant_predictions || 0)
    + Number(horizonMetrics?.violations || 0);
  const noHindsightSamples = Number(noHindsight?.compliant_predictions || 0)
    + Number(noHindsight?.violations || 0);
  const latencySamples = Number(e2e?.samples || 0);
  const mlSamples = Number(ml?.samples || 0);

  return (
    <main className="metrics-page">
      <section className="metrics-hero">
        <div>
          <h1>Метрики</h1>
          <p>
            Результаты локальной валидации модели и показатели текущего запуска системы.
          </p>
        </div>
      </section>

      <section className="metrics-section">
        <div className="metrics-section-head">
          <div>
            <span>Зафиксированные результаты</span>
            <h2>ML-качество</h2>
          </div>
        </div>

        <div className="evidence-grid static-evidence-grid">
          <MetricCard
            icon={Gauge}
            label="MAE на локальном test split"
            value={`${number(STATIC_EVIDENCE.testMaeS, 2)} сек`}
            tone="good"
          />
          <MetricCard
            icon={TimerReset}
            label="Baseline MAE"
            value={`${number(STATIC_EVIDENCE.baselineMaeS, 2)} сек`}
          />
          <MetricCard
            icon={Activity}
            label="Снижение MAE относительно baseline"
            value={percent(improvement, 1)}
            subvalue={`${number(STATIC_EVIDENCE.baselineMaeS - STATIC_EVIDENCE.testMaeS, 2)} сек выигрыша по MAE`}
            tone="good"
          />
        </div>
      </section>

      <section className="metrics-section">
        <div className="metrics-section-head">
          <div>
            <span>Текущий запуск</span>
            <h2>Runtime</h2>
          </div>
          <p>Значения обновляются каждые 2 секунды и накапливаются с момента старта Backend.</p>
        </div>

        <div className="evidence-grid runtime-grid">
          <MetricCard
            icon={Clock3}
            label="Горизонт соблюдён"
            value={horizonSamples ? percent(horizonMetrics?.compliance_pct, 1) : "—"}
            subvalue={horizonSamples ? `${horizonSamples} проверенных предиктов` : "Ожидание предиктов"}
            note="Проверяется runtime-окно (T+10; T+15] для каждого сформированного прогноза."
            tone={metricTone(Number(horizonMetrics?.violations || 0) === 0, horizonSamples > 0)}
          />
          <MetricCard
            icon={ShieldCheck}
            label="Используются только данные, доступные на момент прогноза"
            value={noHindsightSamples ? percent(noHindsight?.compliance_pct, 1) : "—"}
            subvalue={noHindsightSamples ? `${noHindsightSamples} проверенных предиктов` : "Ожидание предиктов"}
            tone={metricTone(Number(noHindsight?.violations || 0) === 0, noHindsightSamples > 0)}
          />
          <MetricCard
            icon={Gauge}
            label="End-to-end latency p95"
            value={latencySamples ? milliseconds(e2e?.p95_ms) : "—"}
            subvalue={latencySamples ? `${latencySamples} измерений` : "Ожидание измерений"}
            tone={metricTone(Number(e2e?.p95_ms) < 2000, latencySamples > 0)}
          />
          <MetricCard
            icon={Activity}
            label="ML latency p95"
            value={mlSamples ? milliseconds(ml?.p95_ms) : "—"}
            subvalue={mlSamples ? `${mlSamples} измерений` : "Ожидание измерений"}
            tone={metricTone(Number(ml?.p95_ms) < 2000, mlSamples > 0)}
          />
        </div>

        <div className="runtime-strip">
          <div><span>Всего прогнозов</span><strong>{number(metrics?.total_predictions, 0)}</strong></div>
          <div><span>Ошибок prediction</span><strong>{number(metrics?.failed_predictions, 0)}</strong></div>
          <div><span>Пропускная способность</span><strong>{number(performance?.throughput_predictions_per_s ?? metrics?.throughput_predictions_per_s, 2)} /с</strong></div>
          <div><span>ТС в ожидании</span><strong>{number(performance?.pending_vehicles ?? metrics?.pending_vehicles, 0)}</strong></div>
          <div><span>До первого прогноза</span><strong>{number(performance?.time_to_first_prediction_s ?? metrics?.time_to_first_prediction_s, 2)} с</strong></div>
        </div>
      </section>
    </main>
  );
}
