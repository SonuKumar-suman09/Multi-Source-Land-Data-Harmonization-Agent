import { useEffect, useMemo, useState } from "react";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { ArrowDownToLine, LocateFixed, LoaderCircle, MapPinned, Search, TriangleAlert, X } from "lucide-react";
import { apiRequest } from "../services/api.js";

const DEFAULT_CENTER = [28.6139, 77.209];
const STATUS_COLORS = {
  valid: "#29735f",
  needs_review: "#c58d36",
  conflict: "#c15f4d",
  invalid: "#854955",
};

export default function MapPage() {
  const [collection, setCollection] = useState({ type: "FeatureCollection", features: [], count: 0 });
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadTick, setReloadTick] = useState(0);
  const [selected, setSelected] = useState(null);
  const [map, setMap] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      const params = new URLSearchParams({ limit: "2000" });
      if (status) params.set("status", status);
      if (search.trim()) params.set("search", search.trim());
      try {
        const next = await apiRequest(`/api/v1/map/parcels?${params.toString()}`, { signal: controller.signal });
        setCollection(next);
        setSelected(null);
        setError("");
      } catch (requestError) {
        if (requestError.name !== "AbortError") setError(requestError.message);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [status, search, reloadTick]);

  const counts = useMemo(() => collection.features.reduce((result, feature) => {
    const key = feature.properties.status;
    result[key] = (result[key] || 0) + 1;
    return result;
  }, {}), [collection]);

  const chooseFeature = (feature) => {
    setSelected(feature);
    if (!map) return;
    const bounds = L.geoJSON(feature).getBounds();
    if (bounds.isValid()) map.flyToBounds(bounds.pad(0.5), { maxZoom: 17, duration: 0.55 });
  };

  return (
    <>
      <div className="page-heading map-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> GEOSPATIAL RECORDS</div><h1>Parcel map</h1><p>Explore stored parcel geometry and inspect its harmonized attributes.</p></div><div className="map-total"><MapPinned size={16} /><b>{collection.count.toLocaleString()}</b><span>mapped records</span></div></div>
      {error && <div className="inline-notice notice-error" role="alert"><TriangleAlert size={15} />{error}<button className="notice-action" onClick={() => setReloadTick((value) => value + 1)}>Retry</button></div>}
      <section className="panel map-workspace">
        <div className="map-toolbar">
          <label className="map-search"><Search size={15} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a plot or landholder" aria-label="Find a plot or landholder" />{search && <button aria-label="Clear search" onClick={() => setSearch("")}><X size={14} /></button>}</label>
          <label className="map-filter">Record status<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="valid">Valid</option><option value="needs_review">Needs review</option><option value="conflict">Conflict</option><option value="invalid">Invalid</option></select></label>
          <span className="map-result-count">{loading ? <LoaderCircle size={13} className="spin" /> : null}{collection.count.toLocaleString()} features</span>
        </div>
        <div className="map-view-layout">
          <div className="leaflet-frame" aria-label="Map of harmonized land parcels">
            <MapContainer center={DEFAULT_CENTER} zoom={12} scrollWheelZoom className="leaflet-map">
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                maxZoom={19}
              />
              <MapController features={collection.features} onReady={setMap} />
              {collection.features.length > 0 && <GeoJSON
                key={`${status}-${search}-${collection.features.map((feature) => feature.id).join(",")}`}
                data={collection}
                style={(feature) => parcelStyle(feature.properties.status)}
                pointToLayer={(feature, latlng) => L.circleMarker(latlng, { ...parcelStyle(feature.properties.status), radius: 7, weight: 2 })}
                onEachFeature={(feature, layer) => layer.on("click", () => setSelected(feature))}
              />}
            </MapContainer>
            {loading && <div className="map-loading"><LoaderCircle size={17} className="spin" /> Updating parcels</div>}
            {!loading && !error && collection.count === 0 && <div className="map-empty"><span><MapPinned size={20} /></span><b>No mapped records found</b><small>Upload and process a source file with valid geometry to see parcels here.</small></div>}
            <div className="map-attribution-note"><LocateFixed size={13} /> Coordinates stored in EPSG:4326</div>
          </div>
          <aside className="map-record-panel">
            <div className="map-record-heading"><div><span className="panel-kicker">VISIBLE FEATURES</span><h2>Parcel records</h2></div><span>{collection.count}</span></div>
            {collection.count > 0 ? <div className="map-record-list">{collection.features.map((feature) => {
              const item = feature.properties;
              return <button key={feature.id} className={`parcel-row ${selected?.id === feature.id ? "parcel-row-selected" : ""}`} onClick={() => chooseFeature(feature)}>
                <span className="parcel-status-mark" style={{ backgroundColor: STATUS_COLORS[item.status] || "#74847c" }} />
                <span className="parcel-row-copy"><b>{item.plot_id || "Unidentified plot"}</b><small>{item.owner_name || "Owner not recorded"}</small><small>{item.area_acres == null ? "Area not recorded" : `${Number(item.area_acres).toFixed(2)} acres`}</small></span>
                <span className={`parcel-status-label parcel-${item.status.replaceAll("_", "-")}`}>{item.status.replaceAll("_", " ")}</span>
              </button>;
            })}</div> : <div className="map-list-empty">No features match these filters.</div>}
            <div className="map-legend"><span className="panel-kicker">RECORD STATUS</span><div>{Object.entries({ valid: "Valid", needs_review: "Needs review", conflict: "Conflict", invalid: "Invalid" }).map(([key, label]) => <span key={key}><i style={{ backgroundColor: STATUS_COLORS[key] }} />{label}<b>{counts[key] || 0}</b></span>)}</div></div>
            {selected && <div className="selected-parcel"><div className="panel-kicker">SELECTED PARCEL</div><b>{selected.properties.plot_id || "Unidentified plot"}</b><span>{selected.properties.owner_name || "Owner not recorded"}</span><div><span>Quality score</span><b>{selected.properties.quality_score == null ? "—" : `${Number(selected.properties.quality_score).toFixed(1)}%`}</b></div><div><span>Recorded</span><b>{selected.properties.recorded_at || "—"}</b></div></div>}
          </aside>
        </div>
      </section>
      <div className="dashboard-note"><ArrowDownToLine size={14} /> Only valid, stored geometries are drawn. Records without geometry remain available in the harmonized dataset.</div>
    </>
  );
}

function MapController({ features, onReady }) {
  const leafletMap = useMap();
  useEffect(() => onReady(leafletMap), [leafletMap, onReady]);
  useEffect(() => {
    const bounds = L.geoJSON({ type: "FeatureCollection", features }).getBounds();
    if (bounds.isValid()) leafletMap.fitBounds(bounds.pad(0.12), { maxZoom: 15, animate: false });
  }, [features, leafletMap]);
  return null;
}

function parcelStyle(status) {
  const color = STATUS_COLORS[status] || "#74847c";
  return { color, fillColor: color, weight: 2, opacity: 0.9, fillOpacity: 0.22 };
}
