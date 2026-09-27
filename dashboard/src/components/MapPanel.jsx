import { useEffect, useMemo, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const LIGHT_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const DARK_STYLE = "https://tiles.openfreemap.org/styles/dark";

const TRAILS_SOURCE_ID = "live-trails";
const TRAILS_CASING_LAYER_ID = "live-trails-casing";
const TRAILS_LAYER_ID = "live-trails-lines";

const VEHICLES_SOURCE_ID = "live-vehicles";
const VEHICLES_LAYER_ID = "live-vehicles-points";
const VEHICLES_HIT_LAYER_ID = "live-vehicles-hit";

const EMPTY_GEOJSON = {
  type: "FeatureCollection",
  features: [],
};

const TONE_COLORS = {
  red: "#e14c4c",
  yellow: "#e7a318",
  green: "#22a45a",
  stale: "#7b8794",
};

function markerTone(vehicle) {
  if (vehicle.status && vehicle.status !== "ok") return "stale";
  return vehicle.risk || "green";
}

function pointTone(point) {
  if (point.status && point.status !== "ok") return "stale";
  return point.risk || "green";
}

function validVehicles(vehicles) {
  return (vehicles || [])
    .map((item) => ({
      ...item,
      lat: Number(item.lat),
      lon: Number(item.lon),
    }))
    .filter((item) => Number.isFinite(item.lat) && Number.isFinite(item.lon));
}

function validTrailPoints(points) {
  return (points || [])
    .map((point) => ({
      ...point,
      lon: Number(point.lon),
      lat: Number(point.lat),
    }))
    .filter((point) => Number.isFinite(point.lon) && Number.isFinite(point.lat));
}

function splitTrailByTone(trail) {
  const points = validTrailPoints(trail.points);
  if (points.length < 2) return [];

  const result = [];
  let currentTone = pointTone(points[1]);
  let coordinates = [
    [points[0].lon, points[0].lat],
    [points[1].lon, points[1].lat],
  ];

  for (let index = 2; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const tone = pointTone(current);

    if (tone === currentTone) {
      coordinates.push([current.lon, current.lat]);
      continue;
    }

    result.push({ tone: currentTone, coordinates });
    currentTone = tone;
    coordinates = [
      [previous.lon, previous.lat],
      [current.lon, current.lat],
    ];
  }

  result.push({ tone: currentTone, coordinates });
  return result;
}

function trailsToGeoJSON(trails) {
  const features = [];

  for (const trail of trails || []) {
    const unitId = String(trail.unit_id);

    splitTrailByTone(trail).forEach((part, index) => {
      features.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: part.coordinates,
        },
        properties: {
          unit_id: unitId,
          tone: part.tone,
          part_index: index,
        },
      });
    });
  }

  return {
    type: "FeatureCollection",
    features,
  };
}

function vehiclesToGeoJSON(vehicles, selectedUnitId) {
  const selected = selectedUnitId == null ? "" : String(selectedUnitId);

  return {
    type: "FeatureCollection",
    features: validVehicles(vehicles).map((vehicle) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [vehicle.lon, vehicle.lat],
      },
      properties: {
        unit_id: String(vehicle.unit_id),
        tone: markerTone(vehicle),
        selected: String(vehicle.unit_id) === selected ? 1 : 0,
      },
    })),
  };
}

function fitVehicles(map, vehicles) {
  if (!vehicles.length) return;

  if (vehicles.length === 1) {
    map.jumpTo({
      center: [vehicles[0].lon, vehicles[0].lat],
      zoom: 13,
    });
    return;
  }

  const bounds = new maplibregl.LngLatBounds();
  vehicles.forEach((vehicle) => bounds.extend([vehicle.lon, vehicle.lat]));

  map.fitBounds(bounds, {
    padding: 72,
    maxZoom: 13,
    duration: 0,
  });
}

function ensureLayers(map, trailsGeoJSON, vehiclesGeoJSON, selectedUnitId, theme) {
  if (!map.isStyleLoaded()) return;

  const selectedId = selectedUnitId == null ? "" : String(selectedUnitId);

  if (!map.getSource(TRAILS_SOURCE_ID)) {
    map.addSource(TRAILS_SOURCE_ID, {
      type: "geojson",
      data: trailsGeoJSON,
    });
  } else {
    map.getSource(TRAILS_SOURCE_ID)?.setData(trailsGeoJSON);
  }

  if (!map.getLayer(TRAILS_CASING_LAYER_ID)) {
    map.addLayer({
      id: TRAILS_CASING_LAYER_ID,
      type: "line",
      source: TRAILS_SOURCE_ID,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": theme === "dark" ? "#071019" : "#ffffff",
        "line-width": [
          "case",
          ["==", ["get", "unit_id"], selectedId],
          9,
          6,
        ],
        "line-opacity": [
          "case",
          ["==", ["get", "unit_id"], selectedId],
          0.88,
          0.62,
        ],
      },
    });
  } else {
    map.setPaintProperty(
      TRAILS_CASING_LAYER_ID,
      "line-color",
      theme === "dark" ? "#071019" : "#ffffff",
    );
    map.setPaintProperty(TRAILS_CASING_LAYER_ID, "line-width", [
      "case",
      ["==", ["get", "unit_id"], selectedId],
      9,
      6,
    ]);
  }

  if (!map.getLayer(TRAILS_LAYER_ID)) {
    map.addLayer({
      id: TRAILS_LAYER_ID,
      type: "line",
      source: TRAILS_SOURCE_ID,
      layout: {
        "line-cap": "round",
        "line-join": "round",
      },
      paint: {
        "line-color": [
          "match",
          ["get", "tone"],
          "red", TONE_COLORS.red,
          "yellow", TONE_COLORS.yellow,
          "green", TONE_COLORS.green,
          "stale", TONE_COLORS.stale,
          TONE_COLORS.stale,
        ],
        "line-width": [
          "case",
          ["==", ["get", "unit_id"], selectedId],
          6.5,
          4,
        ],
        "line-opacity": 0.92,
      },
    });
  } else {
    map.setPaintProperty(TRAILS_LAYER_ID, "line-width", [
      "case",
      ["==", ["get", "unit_id"], selectedId],
      6.5,
      4,
    ]);
  }

  if (!map.getSource(VEHICLES_SOURCE_ID)) {
    map.addSource(VEHICLES_SOURCE_ID, {
      type: "geojson",
      data: vehiclesGeoJSON,
    });
  } else {
    map.getSource(VEHICLES_SOURCE_ID)?.setData(vehiclesGeoJSON);
  }

  if (!map.getLayer(VEHICLES_LAYER_ID)) {
    map.addLayer({
      id: VEHICLES_LAYER_ID,
      type: "circle",
      source: VEHICLES_SOURCE_ID,
      paint: {
        "circle-radius": [
          "case",
          ["==", ["get", "selected"], 1],
          10,
          7,
        ],
        "circle-color": [
          "match",
          ["get", "tone"],
          "red", TONE_COLORS.red,
          "yellow", TONE_COLORS.yellow,
          "green", TONE_COLORS.green,
          "stale", TONE_COLORS.stale,
          TONE_COLORS.stale,
        ],
        "circle-stroke-color": [
          "case",
          ["==", ["get", "selected"], 1],
          "#2f80ff",
          "#ffffff",
        ],
        "circle-stroke-width": [
          "case",
          ["==", ["get", "selected"], 1],
          4,
          3,
        ],
        "circle-opacity": 1,
        "circle-stroke-opacity": 1,
        "circle-translate": [0, 0],
        "circle-translate-anchor": "map",
        "circle-pitch-alignment": "map",
        "circle-pitch-scale": "map",
      },
    });
  }

  if (!map.getLayer(VEHICLES_HIT_LAYER_ID)) {
    map.addLayer({
      id: VEHICLES_HIT_LAYER_ID,
      type: "circle",
      source: VEHICLES_SOURCE_ID,
      paint: {
        "circle-radius": 18,
        "circle-color": "#000000",
        "circle-opacity": 0.001,
        "circle-translate": [0, 0],
        "circle-translate-anchor": "map",
        "circle-pitch-alignment": "map",
        "circle-pitch-scale": "map",
      },
    });
  }

  // Точки всегда поверх пройденной траектории.
  if (map.getLayer(VEHICLES_LAYER_ID)) map.moveLayer(VEHICLES_LAYER_ID);
  if (map.getLayer(VEHICLES_HIT_LAYER_ID)) map.moveLayer(VEHICLES_HIT_LAYER_ID);
}

export default function MapPanel({
  vehicles,
  trails,
  selectedUnitId,
  onSelectVehicle,
  theme,
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const onSelectVehicleRef = useRef(onSelectVehicle);
  const mountedThemeRef = useRef(theme);
  const interactingRef = useRef(false);
  const didInitialFitRef = useRef(false);
  const lastFocusedUnitIdRef = useRef(null);

  const trailsGeoJSONRef = useRef(EMPTY_GEOJSON);
  const vehiclesGeoJSONRef = useRef(EMPTY_GEOJSON);
  const selectedUnitIdRef = useRef(selectedUnitId);

  const activeVehicles = useMemo(
    () => validVehicles(vehicles),
    [vehicles],
  );

  const trailsGeoJSON = useMemo(
    () => trailsToGeoJSON(trails || []),
    [trails],
  );

  const vehiclesGeoJSON = useMemo(
    () => vehiclesToGeoJSON(activeVehicles, selectedUnitId),
    [activeVehicles, selectedUnitId],
  );

  useEffect(() => {
    onSelectVehicleRef.current = onSelectVehicle;
  }, [onSelectVehicle]);

  useEffect(() => {
    trailsGeoJSONRef.current = trailsGeoJSON;
    vehiclesGeoJSONRef.current = vehiclesGeoJSON;
    selectedUnitIdRef.current = selectedUnitId;
  }, [trailsGeoJSON, vehiclesGeoJSON, selectedUnitId]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: mountedThemeRef.current === "dark" ? DARK_STYLE : LIGHT_STYLE,
      center: [37.6176, 55.7558],
      zoom: 10.5,
      pitch: 0,
      bearing: 0,
      attributionControl: false,
    });

    map.addControl(
      new maplibregl.NavigationControl({
        showCompass: false,
        visualizePitch: false,
      }),
      "bottom-left",
    );

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-right",
    );

    const applyLatestData = () => {
      ensureLayers(
        map,
        trailsGeoJSONRef.current,
        vehiclesGeoJSONRef.current,
        selectedUnitIdRef.current,
        mountedThemeRef.current,
      );
    };

    const handleInteractionStart = () => {
      interactingRef.current = true;
    };

    const handleInteractionEnd = () => {
      interactingRef.current = false;
      applyLatestData();
    };

    const handleClick = (event) => {
      if (!map.getLayer(VEHICLES_HIT_LAYER_ID)) return;

      const features = map.queryRenderedFeatures(event.point, {
        layers: [VEHICLES_HIT_LAYER_ID],
      });

      const unitId = features[0]?.properties?.unit_id;
      if (unitId != null) {
        onSelectVehicleRef.current?.(unitId);
      }
    };

    const handleMouseMove = (event) => {
      if (!map.getLayer(VEHICLES_HIT_LAYER_ID)) {
        map.getCanvas().style.cursor = "";
        return;
      }

      const features = map.queryRenderedFeatures(event.point, {
        layers: [VEHICLES_HIT_LAYER_ID],
      });

      map.getCanvas().style.cursor = features.length ? "pointer" : "";
    };

    map.on("movestart", handleInteractionStart);
    map.on("zoomstart", handleInteractionStart);
    map.on("moveend", handleInteractionEnd);
    map.on("zoomend", handleInteractionEnd);
    map.on("click", handleClick);
    map.on("mousemove", handleMouseMove);

    map.once("load", () => {
      applyLatestData();
    });

    mapRef.current = map;

    return () => {
      map.off("movestart", handleInteractionStart);
      map.off("zoomstart", handleInteractionStart);
      map.off("moveend", handleInteractionEnd);
      map.off("zoomend", handleInteractionEnd);
      map.off("click", handleClick);
      map.off("mousemove", handleMouseMove);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || theme === mountedThemeRef.current) return undefined;

    mountedThemeRef.current = theme;

    const handleStyleLoad = () => {
      ensureLayers(
        map,
        trailsGeoJSONRef.current,
        vehiclesGeoJSONRef.current,
        selectedUnitIdRef.current,
        theme,
      );
    };

    map.once("style.load", handleStyleLoad);
    map.setStyle(theme === "dark" ? DARK_STYLE : LIGHT_STYLE);

    return () => map.off("style.load", handleStyleLoad);
  }, [theme]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    // Во время zoom/pan не меняем геометрию источника. Это исключает
    // визуальные рывки от одновременно приходящей раз в секунду NDTP-точки.
    // После окончания движения карты применяется самое свежее состояние.
    if (interactingRef.current) return;

    ensureLayers(
      map,
      trailsGeoJSON,
      vehiclesGeoJSON,
      selectedUnitId,
      theme,
    );

    // Автомасштабирование только один раз, когда впервые появились ТС.
    // После этого камера полностью принадлежит пользователю.
    if (!didInitialFitRef.current && activeVehicles.length) {
      fitVehicles(map, activeVehicles);
      didInitialFitRef.current = true;
    }
  }, [activeVehicles, trailsGeoJSON, vehiclesGeoJSON, selectedUnitId, theme]);

  useEffect(() => {
    const map = mapRef.current;

    if (selectedUnitId == null) {
      lastFocusedUnitIdRef.current = null;
      return;
    }

    if (!map) return;

    const selectedId = String(selectedUnitId);

    // Polling обновляет vehicles каждую секунду. Повторно двигать камеру
    // для уже выбранного ТС нельзя — иначе пользователь не сможет
    // самостоятельно масштабировать и перемещать карту.
    if (lastFocusedUnitIdRef.current === selectedId) return;

    const vehicle = activeVehicles.find(
      (item) => String(item.unit_id) === selectedId,
    );

    if (!vehicle) return;

    lastFocusedUnitIdRef.current = selectedId;

    map.easeTo({
      center: [vehicle.lon, vehicle.lat],
      zoom: Math.max(map.getZoom(), 14.5),
      duration: 550,
      essential: true,
    });
  }, [selectedUnitId, activeVehicles]);

  return (
    <div className="map-wrap">
      <div
        ref={containerRef}
        className="map"
        aria-label="Карта текущего положения транспортных средств"
      />

      <div className="map-legend" aria-label="Легенда карты">
        <span><i className="legend-dot green" />Норма</span>
        <span><i className="legend-dot yellow" />Риск</span>
        <span><i className="legend-dot red" />Высокий</span>
        <span><i className="legend-dot stale" />Нет данных</span>
      </div>
    </div>
  );
}
