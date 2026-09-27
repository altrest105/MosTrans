import { useCallback, useEffect, useMemo, useState } from "react";
import { BusFront, Moon, Sun } from "lucide-react";
import { loadDashboardData } from "./api";
import MapPanel from "./components/MapPanel";
import IncidentList from "./components/IncidentList";

const REFRESH_MS = 1000;


function deviationValue(item) {
  return Number(item?.deviation_s ?? item?.prediction_s);
}

function formatDeviation(value, long = false, signed = true) {
  const seconds = Math.round(Number(value));
  if (!Number.isFinite(seconds)) return "—";

  const sign = signed
    ? (seconds > 0 ? "+" : seconds < 0 ? "−" : "")
    : "";
  const absolute = Math.abs(seconds);
  const minutes = Math.floor(absolute / 60);
  const rest = absolute % 60;

  if (long) {
    if (minutes === 0) return `${sign}${rest} сек`;
    return `${sign}${minutes} мин ${rest} сек`;
  }

  if (minutes === 0) return `${sign}${rest} сек`;
  return `${sign}${minutes}:${String(rest).padStart(2, "0")}`;
}

function deviationDirection(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds === 0) return "По графику";
  return seconds > 0 ? "Опоздание" : "Опережение";
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatScheduleClock(value) {
  if (!value) return "—";

  // Плановые времена расписания являются московским wall-clock временем.
  // Берём HH:MM напрямую из ISO-строки и не даём браузеру сдвигать timezone.
  if (typeof value === "string") {
    const match = value.match(/T(\d{2}):(\d{2})/);
    if (match) return `${match[1]}:${match[2]}`;
  }

  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function formatPredictedArrival(stop, fallbackDeviationS = null) {
  if (!stop) return "—";

  if (stop.predicted_arrival_time) {
    return formatScheduleClock(stop.predicted_arrival_time);
  }

  const deviation = Number(stop.predicted_deviation_s ?? fallbackDeviationS);
  if (!Number.isFinite(deviation) || !stop.planned_time) return "—";

  const match = String(stop.planned_time).match(/T(\d{2}):(\d{2}):(\d{2})/);
  if (!match) return "—";

  const baseSeconds = Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]);
  const daySeconds = 24 * 3600;
  let resultSeconds = Math.round(baseSeconds + deviation) % daySeconds;
  if (resultSeconds < 0) resultSeconds += daySeconds;

  const hours = Math.floor(resultSeconds / 3600);
  const minutes = Math.floor((resultSeconds % 3600) / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function formatNumber(value, digits = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function displayTone(item) {
  if (item?.status && item.status !== "ok") return "stale";
  return item?.risk || "green";
}

function riskLabel(item) {
  if (item?.service_status === "finished") return "Рейс завершён";
  if (item?.service_status === "not_started") return "Рейс ещё не начался";
  const tone = displayTone(item);
  if (tone === "red") return "Высокий риск";
  if (tone === "yellow") return "Повышенный риск";
  if (tone === "stale") return "Данные устарели";
  return "Норма";
}

function systemClass(status, error) {
  if (error || status === "degraded") return "degraded";
  if (status === "waiting") return "waiting";
  return "ok";
}

export default function App() {
  const [data, setData] = useState({
    system: { status: "waiting", message: "Ожидание телеметрии" },
    metrics: {},
    vehicles: [],
    predictions: [],
    trails: [],
  });
  const [error, setError] = useState("");
  const [updatedAt, setUpdatedAt] = useState(null);
  const [selectedUnitId, setSelectedUnitId] = useState(null);
  const [tab, setTab] = useState("incidents");
  const [theme, setTheme] = useState(() => localStorage.getItem("mostrans-theme") || "dark");

  const refresh = useCallback(async () => {
    try {
      const next = await loadDashboardData();
      setData(next);
      setUpdatedAt(new Date());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("mostrans-theme", theme);
  }, [theme]);

  const incidents = useMemo(
    () => data.predictions.filter(
      (item) => item.risk === "red" || item.risk === "yellow" || item.status !== "ok",
    ),
    [data.predictions],
  );

  // Географическое положение берём напрямую из последней NDTP-телеметрии,
  // а цвет/статус — из последнего ML-прогноза. Маркер ТС поэтому не зависит
  // от того, успел ли сформироваться новый prediction.
  const mapVehicles = useMemo(() => {
    const predictionByUnit = new Map(
      data.predictions.map((item) => [String(item.unit_id), item]),
    );

    return (data.vehicles || []).map((vehicle) => {
      const prediction = predictionByUnit.get(String(vehicle.unit_id));

      return {
        ...vehicle,
        risk: prediction?.risk || "green",
        status: prediction?.status || (
          Number(vehicle.telemetry_age_s) > 30 ? "stale" : "ok"
        ),
      };
    });
  }, [data.vehicles, data.predictions]);

  const allTransportItems = useMemo(() => {
    const predictionByUnit = new Map(
      data.predictions.map((item) => [String(item.unit_id), item]),
    );

    return mapVehicles.map((vehicle) => {
      const prediction = predictionByUnit.get(String(vehicle.unit_id));

      return {
        ...vehicle,
        ...(prediction || {}),
        // Пустой next_stop в prediction не должен затирать fallback из /vehicles.
        next_stop: prediction?.next_stop ?? vehicle?.next_stop ?? null,
      };
    });
  }, [mapVehicles, data.predictions]);

  const listItems = tab === "incidents" ? incidents : allTransportItems;

  const selected = useMemo(() => {
    if (selectedUnitId == null) {
      return null;
    }

    const vehicle = mapVehicles.find(
      (item) => String(item.unit_id) === String(selectedUnitId),
    );
    const prediction = data.predictions.find(
      (item) => String(item.unit_id) === String(selectedUnitId),
    );

    if (!vehicle && !prediction) {
      return null;
    }

    // Текущие координаты/скорость всегда берём из NDTP (/vehicles),
    // ML-поля накладываем сверху, если прогноз уже сформирован.
    return {
      ...(vehicle || {}),
      ...(prediction || {}),
      unit_id: prediction?.unit_id ?? vehicle?.unit_id,
      lat: vehicle?.lat ?? prediction?.lat,
      lon: vehicle?.lon ?? prediction?.lon,
      speed: vehicle?.speed ?? prediction?.speed,
      event_time: vehicle?.event_time ?? prediction?.event_time,
      // /vehicles всегда пытается дать ближайшую остановку этого tr_id.
      // Если prediction ещё хранит null, сохраняем найденный fallback.
      next_stop: prediction?.next_stop ?? vehicle?.next_stop ?? null,
      has_prediction: Boolean(prediction),
    };
  }, [data.predictions, mapVehicles, selectedUnitId]);

  const averageAbsoluteDeviation = data.predictions.length
    ? data.predictions.reduce(
      (sum, item) => sum + Math.abs(deviationValue(item) || 0),
      0,
    ) / data.predictions.length
    : 0;

  const statusMessage = error
    ? "Деградация: Backend недоступен. Показывается последнее известное состояние"
    : data.system.message || "Система в норме";

  const selectedForecast = selected;
  const selectedDeviation = selectedForecast ? deviationValue(selectedForecast) : null;




  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <BusFront size={22} strokeWidth={2} />
          <div>
            <strong>MosTrans</strong>
            <span>Диспетчерская</span>
          </div>
        </div>

        <div className="header-metrics" aria-label="Краткая сводка">
          <div>
            <span>Онлайн</span>
            <strong>{data.system.telemetry?.fresh_vehicles ?? data.predictions.length} ТС</strong>
          </div>
          <div>
            <span>Инциденты</span>
            <strong>{incidents.length}</strong>
          </div>
          <div>
            <span>Среднее отклонение</span>
            <strong>{formatDeviation(averageAbsoluteDeviation, false, false)}</strong>
          </div>
        </div>

        <div className="header-actions">
          <div className={`system-status ${systemClass(data.system.status, error)}`}>
            {statusMessage}
          </div>
          <button
            type="button"
            className="theme-toggle"
            onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"}
            title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          >
            {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
          </button>
        </div>
      </header>

      {data.system.status === "degraded" || error ? (
        <div className="degradation-banner">{statusMessage}</div>
      ) : null}

      <main className="workspace">
        <section className="map-panel" aria-label="Карта транспорта">
          <MapPanel
            vehicles={mapVehicles}
            trails={data.trails || []}
            selectedUnitId={selectedUnitId}
            onSelectVehicle={setSelectedUnitId}
            theme={theme}
          />
        </section>

        <aside className="side-panel">
          <div className="side-head">
            <div>
              <h1>Транспорт</h1>
              <p>
                {updatedAt
                  ? `Обновлено ${updatedAt.toLocaleTimeString("ru-RU")}`
                  : "Подключение…"}
              </p>
            </div>
          </div>

          <div className="tabs" role="tablist" aria-label="Список транспорта">
            <button
              type="button"
              className={tab === "incidents" ? "active" : ""}
              onClick={() => setTab("incidents")}
            >
              Инциденты <span>{incidents.length}</span>
            </button>
            <button
              type="button"
              className={tab === "all" ? "active" : ""}
              onClick={() => setTab("all")}
            >
              Все ТС <span>{mapVehicles.length}</span>
            </button>
          </div>

          <IncidentList
            predictions={listItems}
            selectedUnitId={selectedUnitId}
            onSelect={setSelectedUnitId}
          />

          <div className="detail-separator" />

          {selectedForecast ? (
            <section className="vehicle-detail">
              <div className="detail-heading">
                <div>
                  <div className={`risk-label ${displayTone(selectedForecast)}`}>
                    {riskLabel(selectedForecast)}
                  </div>
                  <h2>ТС {selectedForecast.unit_id}</h2>
                </div>
                <button
                  type="button"
                  className="close-detail"
                  onClick={() => setSelectedUnitId(null)}
                  aria-label="Закрыть"
                >
                  ×
                </button>
              </div>


              <div className="forecast-block horizon-forecast">
                <div className="forecast-title-row">
                  <span>Прогноз на горизонте</span>
                  <b>12.5 мин</b>
                </div>

                {selectedForecast.service_status === "finished" ? (
                  <>
                    <strong className="forecast-empty service-finished">Рейс завершён</strong>
                    <small>
                      Движение по расписанию завершено
                      {selectedForecast.service_last_planned_time
                        ? ` в ${formatScheduleClock(selectedForecast.service_last_planned_time)}`
                        : ""}.
                    </small>
                  </>
                ) : selectedForecast.service_status === "not_started" ? (
                  <>
                    <strong className="forecast-empty">Рейс ещё не начался</strong>
                    <small>
                      Первый плановый выход
                      {selectedForecast.service_first_planned_time
                        ? ` в ${formatScheduleClock(selectedForecast.service_first_planned_time)}`
                        : ""}.
                    </small>
                  </>
                ) : selectedForecast.has_prediction && selectedForecast.target_stop ? (
                  <>
                    <p className="forecast-stop-name">
                      {selectedForecast.target_stop.address
                        || `Остановка ${selectedForecast.target_stop.stop_id}`}
                    </p>

                    <div className="arrival-grid">
                      <div>
                        <span>По расписанию</span>
                        <strong>{formatScheduleClock(selectedForecast.target_stop.planned_time)}</strong>
                      </div>
                      <div>
                        <span>По прогнозу</span>
                        <strong>
                          {formatPredictedArrival(selectedForecast.target_stop, selectedDeviation)}
                        </strong>
                      </div>
                    </div>

                    <div className={`forecast-deviation-line ${displayTone(selectedForecast)}`}>
                      {deviationDirection(selectedDeviation)} · {formatDeviation(selectedDeviation, true)}
                    </div>
                  </>
                ) : selectedForecast.has_prediction ? (
                  <>
                    <strong className="forecast-empty">Нет целевой остановки</strong>
                    <small>В окне T+10…15 мин нет подходящей записи расписания.</small>
                  </>
                ) : (
                  <>
                    <strong className="forecast-empty">Ожидание прогноза</strong>
                    <small>Текущее положение получено по NDTP.</small>
                  </>
                )}
              </div>

              <div className="next-stop-block">
                <div className="next-stop-heading">Следующая остановка</div>
                {selectedForecast.service_status === "finished" ? (
                  <>
                    <p className="next-stop-finished">Нет — движение по расписанию завершено</p>
                    <small>Следующий суточный рейс здесь намеренно не подставляется.</small>
                  </>
                ) : selectedForecast.next_stop ? (
                  <>
                    <p>
                      {selectedForecast.next_stop.address
                        || `Остановка ${selectedForecast.next_stop.stop_id}`}
                    </p>
                    <div className="next-stop-times">
                      <span>План {formatScheduleClock(selectedForecast.next_stop.planned_time)}</span>
                      <span>
                        Прогноз {formatPredictedArrival(
                          selectedForecast.next_stop,
                          selectedForecast.current_deviation_s,
                        )}
                      </span>
                    </div>
                    {selectedForecast.next_stop.prediction_source === "current_deviation" ? (
                      <small>Оперативная ETA по текущему отклонению</small>
                    ) : selectedForecast.next_stop.prediction_source === "ml_12_5" ? (
                      <small>Совпадает с остановкой ML-прогноза</small>
                    ) : selectedForecast.next_stop.selection_source === "nearest_route_stop" ? (
                      <small>Ближайшая остановка из расписания этого ТС</small>
                    ) : null}
                  </>
                ) : (
                  <p>Не определена</p>
                )}
              </div>

              <div className="text-block">
                <span>Причина</span>
                <p>{selectedForecast.service_status === "finished" ? "Суточный график движения завершён." : (selectedForecast.cause || "Причина не определена")}</p>
              </div>

              <div className="text-block recommendation">
                <span>Рекомендация</span>
                <p>{selectedForecast.service_status === "finished" ? "Прогноз на текущий рейс больше не требуется." : (selectedForecast.recommendation || "Продолжать мониторинг.")}</p>
              </div>

              <div className="detail-metrics">
                <div>
                  <span>Скорость</span>
                  <strong>{formatNumber(selectedForecast.speed)} км/ч</strong>
                </div>
                <div>
                  <span>Средняя за 10 мин</span>
                  <strong>{formatNumber(selectedForecast.average_speed_kmh ?? selectedForecast.features?.mean_speed_10m)} км/ч</strong>
                </div>
                <div>
                  <span>Простой за 10 мин</span>
                  <strong>{formatDeviation(selectedForecast.dwell_time_s ?? 0, true, false)}</strong>
                </div>
                <div>
                  <span>Текущее отклонение</span>
                  <strong>{formatDeviation(selectedForecast.current_deviation_s, false)}</strong>
                </div>
              </div>

              {selectedForecast.status !== "ok" ? (
                <div className="stale-note">
                  {selectedForecast.degradation_reason || "Используется последнее известное состояние."}
                </div>
              ) : null}

              <div className="audit-line">
                T {formatTime(selectedForecast.prediction_time)} · прогноз до {formatTime(selectedForecast.forecast_for)}
              </div>
            </section>
          ) : (
            <div className="select-hint">
              Выберите ТС на карте или в списке, чтобы увидеть детали.
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
