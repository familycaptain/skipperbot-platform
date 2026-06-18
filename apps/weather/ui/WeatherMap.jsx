// =============================================================================
// Weather radar/alerts map (~100-mile view) — Leaflet
// =============================================================================
// OpenStreetMap base + Iowa Environmental Mesonet (IEM) NEXRAD radar WMS overlay
// + active NWS severe-weather alert polygons (fetched server-side via
// /api/apps/weather/alerts to avoid the browser User-Agent restriction).
// Plain Leaflet (no marker-image icons) to sidestep bundler icon-path issues.
// =============================================================================

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const API = "/api/apps/weather";

function sevColor(sev) {
  const s = (sev || "").toLowerCase();
  if (s === "extreme" || s === "severe") return "#ef4444";
  if (s === "moderate") return "#f59e0b";
  return "#eab308";
}

export default function WeatherMap({ place }) {
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const [alertNote, setAlertNote] = useState("");

  useEffect(() => {
    const el = elRef.current;
    if (!el || !place || place.lat == null || place.lon == null) return;
    setAlertNote("");

    // Re-create cleanly if the location changed.
    if (mapRef.current) { mapRef.current.remove(); mapRef.current = null; }

    const map = L.map(el, { scrollWheelZoom: false }).setView([place.lat, place.lon], 7);
    mapRef.current = map;

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(map);

    const radar = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q.cgi", {
      layers: "nexrad-n0q-900913",
      format: "image/png",
      transparent: true,
      opacity: 0.55,
      attribution: "Radar © IEM NEXRAD",
    }).addTo(map);

    const alerts = L.geoJSON(null, {
      style: (f) => ({ color: sevColor(f.properties && f.properties.severity), weight: 2, fillOpacity: 0.12 }),
      onEachFeature: (f, layer) => {
        const p = (f && f.properties) || {};
        layer.bindPopup(
          `<strong>${p.event || "Alert"}</strong><br>${p.headline || ""}` +
          (p.area ? `<br><em>${p.area}</em>` : "")
        );
      },
    }).addTo(map);

    // Home location marker (circleMarker = SVG, no icon image needed).
    L.circleMarker([place.lat, place.lon], {
      radius: 5, color: "#38bdf8", fillColor: "#38bdf8", fillOpacity: 1, weight: 2,
    }).addTo(map).bindPopup(place.display_label || "Home");

    L.control.layers(null, { "Radar (NEXRAD)": radar, "Severe alerts": alerts }, { collapsed: false }).addTo(map);

    let dead = false;
    // NWS severe-weather alerts are US-only; the server gates non-US locations
    // and returns an explicit message we surface instead of a silent empty.
    fetch(`${API}/alerts?location=${encodeURIComponent(place.display_label || "")}`)
      .then((r) => r.json())
      .then((gj) => {
        if (dead || !gj) return;
        if (gj.us_only && gj.message) { setAlertNote(gj.message); return; }
        if (Array.isArray(gj.features)) alerts.addData(gj);
      })
      .catch(() => {});

    // Leaflet needs a sizing nudge when it mounts inside a flex/async layout.
    const t = setTimeout(() => map.invalidateSize(), 120);

    return () => { dead = true; clearTimeout(t); map.remove(); mapRef.current = null; };
  }, [place && place.lat, place && place.lon, place && place.display_label, place && place.country_code]);

  return (
    <div>
      <div className="rounded-xl overflow-hidden border border-slate-700/50" style={{ height: 360 }}>
        <div ref={elRef} style={{ height: "100%", width: "100%" }} />
      </div>
      {alertNote && (
        <div className="mt-2 text-xs text-amber-300/90">{alertNote}</div>
      )}
    </div>
  );
}
