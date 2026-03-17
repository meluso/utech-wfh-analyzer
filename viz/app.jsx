/**
 * WFH Perturbation Visualization Tool
 *
 * Interactive map showing how WFH scenarios change commute flows across
 * Queens County, NY. Loads precomputed data (from precompute_viz_data.py)
 * and renders hex choropleth + flow arcs with an alpha slider.
 *
 * See docs/visualization_tool_spec.md for full specification.
 */

import React, { useState, useEffect, useMemo, useCallback, createRoot } from "react";
import ReactDOM from "react-dom/client";
import Map from "react-map-gl";
import DeckGL from "@deck.gl/react";
import { GeoJsonLayer, ArcLayer } from "@deck.gl/layers";
import { scaleSequential, scaleDiverging } from "d3-scale";
import { interpolateRdBu } from "d3-scale-chromatic";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// Supply your Mapbox token via viz/.env as VITE_MAPBOX_TOKEN
const MAPBOX_TOKEN =
  import.meta.env.VITE_MAPBOX_TOKEN || "YOUR_MAPBOX_TOKEN_HERE";

const INITIAL_VIEW_STATE = {
  longitude: -73.85,
  latitude: 40.71,
  zoom: 10.5,
  pitch: 30,
  bearing: 0,
};

const MAP_STYLE = "mapbox://styles/mapbox/dark-v11";
const TOP_N_ARCS = 75;

const EDU_LABELS = [
  "Less than HS",
  "HS Diploma",
  "Some College",
  "Bachelor's",
  "Advanced",
];

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Failed to load ${url}: ${resp.status}`);
  return resp.json();
}

function usePrecomputedData() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([
      loadJson("/hex_geometries.geojson"),
      loadJson("/snapshots.json"),
      loadJson("/hex_metadata.json"),
    ])
      .then(([geojson, snapshots, metadata]) => {
        // Build centroid lookup from geojson
        const centroids = {};
        for (const feat of geojson.features) {
          const { hex_id, centroid_lat, centroid_lng } = feat.properties;
          centroids[hex_id] = [centroid_lng, centroid_lat];
        }

        // Compute global min/max of hex_net_change across all snapshots
        // for a stable color scale
        let globalMin = 0;
        let globalMax = 0;
        for (const snap of snapshots.snapshots) {
          for (const val of Object.values(snap.hex_net_change)) {
            if (val < globalMin) globalMin = val;
            if (val > globalMax) globalMax = val;
          }
        }
        // Make symmetric around 0
        const absMax = Math.max(Math.abs(globalMin), Math.abs(globalMax));
        globalMin = -absMax;
        globalMax = absMax;

        setData({ geojson, snapshots, metadata, centroids, globalMin, globalMax });
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  return { data, loading, error };
}

// ---------------------------------------------------------------------------
// Color scale: diverging blue-white-red
// ---------------------------------------------------------------------------

function makeColorScale(min, max) {
  // interpolateRdBu goes red -> white -> blue
  // We want blue = negative (traffic reduced), red = positive (traffic increased)
  // So we reverse: value -max -> blue, 0 -> white, +max -> red
  const scale = scaleDiverging()
    .domain([min, 0, max])
    .interpolator((t) => interpolateRdBu(1 - t)); // reverse RdBu

  return (value) => {
    const color = scale(value);
    // Parse "rgb(r, g, b)" string to [r, g, b]
    const match = color.match(/\d+/g);
    if (match)
      return [parseInt(match[0]), parseInt(match[1]), parseInt(match[2])];
    return [200, 200, 200];
  };
}

// ---------------------------------------------------------------------------
// Nearest alpha snapshot index
// ---------------------------------------------------------------------------

function findNearestAlphaIndex(alphaValues, target) {
  let best = 0;
  let bestDist = Math.abs(alphaValues[0] - target);
  for (let i = 1; i < alphaValues.length; i++) {
    const d = Math.abs(alphaValues[i] - target);
    if (d < bestDist) {
      best = i;
      bestDist = d;
    }
  }
  return best;
}

// ---------------------------------------------------------------------------
// P-value histogram bins
// ---------------------------------------------------------------------------

function computePHistogram(PValues, nBins = 20) {
  const min = 0.5;
  const max = 1.5;
  const binWidth = (max - min) / nBins;
  const bins = new Array(nBins).fill(0);
  const labels = [];
  for (let i = 0; i < nBins; i++) {
    labels.push(min + (i + 0.5) * binWidth);
  }
  for (const p of PValues) {
    const idx = Math.floor((p - min) / binWidth);
    if (idx >= 0 && idx < nBins) bins[idx]++;
  }
  const maxCount = Math.max(...bins, 1);
  return { bins, labels, maxCount, binWidth, min, max };
}

// ---------------------------------------------------------------------------
// Summary Stats Panel
// ---------------------------------------------------------------------------

function SummaryPanel({ snapshot, PValues }) {
  const hist = useMemo(
    () => computePHistogram(PValues),
    [PValues]
  );

  return (
    <div
      style={{
        position: "absolute",
        top: 80,
        right: 16,
        width: 280,
        backgroundColor: "rgba(15, 23, 42, 0.92)",
        borderRadius: 12,
        padding: 16,
        color: "#e2e8f0",
        fontSize: 13,
        backdropFilter: "blur(8px)",
        zIndex: 10,
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 12 }}>
        Summary
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ color: "#94a3b8" }}>Baseline flow</span>
        <span style={{ fontFamily: "monospace" }}>
          {snapshot.total_T.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={{ color: "#94a3b8" }}>Perturbed flow</span>
        <span style={{ fontFamily: "monospace" }}>
          {snapshot.total_G.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <span style={{ color: "#94a3b8" }}>Change</span>
        <span
          style={{
            fontFamily: "monospace",
            fontWeight: 700,
            color: snapshot.percent_change < 0 ? "#60a5fa" : "#f87171",
          }}
        >
          {(snapshot.percent_change * 100).toFixed(1)}%
        </span>
      </div>

      <div style={{ fontWeight: 600, fontSize: 12, color: "#94a3b8", marginBottom: 8 }}>
        P value distribution
      </div>
      <svg width={248} height={60}>
        {hist.bins.map((count, i) => (
          <rect
            key={i}
            x={i * (248 / hist.bins.length)}
            y={60 - (count / hist.maxCount) * 55}
            width={248 / hist.bins.length - 1}
            height={(count / hist.maxCount) * 55}
            fill={hist.labels[i] < 1 ? "#60a5fa" : "#f87171"}
            opacity={0.8}
            rx={1}
          />
        ))}
        {/* axis line at P=1 */}
        <line
          x1={(1.0 - hist.min) / (hist.max - hist.min) * 248}
          y1={0}
          x2={(1.0 - hist.min) / (hist.max - hist.min) * 248}
          y2={60}
          stroke="#fbbf24"
          strokeWidth={1}
          strokeDasharray="3,3"
        />
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "#64748b",
          marginTop: 2,
        }}
      >
        <span>0.5</span>
        <span>P = 1.0</span>
        <span>1.5</span>
      </div>
      <div style={{ fontSize: 10, color: "#475569", marginTop: 8 }}>
        Baseline flows from LODES OD data; absolute magnitudes are approximate.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Alpha Slider
// ---------------------------------------------------------------------------

function AlphaSlider({ alpha, alphaMax, onChange, percentChange }) {
  return (
    <div
      style={{
        position: "absolute",
        top: 16,
        left: 16,
        right: 310,
        backgroundColor: "rgba(15, 23, 42, 0.92)",
        borderRadius: 12,
        padding: "12px 20px",
        zIndex: 10,
        backdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <div style={{ flex: "0 0 auto", color: "#e2e8f0", fontSize: 13 }}>
        <span style={{ fontWeight: 700, fontFamily: "monospace", fontSize: 15 }}>
          &alpha; = {alpha.toFixed(2)}
        </span>
        <span style={{ color: "#94a3b8", marginLeft: 12 }}>
          |{" "}
          <span
            style={{
              color: percentChange < 0 ? "#60a5fa" : "#f87171",
              fontWeight: 600,
            }}
          >
            {(percentChange * 100).toFixed(1)}% total flow
          </span>
        </span>
      </div>
      <input
        type="range"
        min={-1}
        max={alphaMax}
        step={0.001}
        value={alpha}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: "#6366f1", height: 6 }}
      />
      <div
        style={{
          flex: "0 0 auto",
          display: "flex",
          gap: 16,
          fontSize: 10,
          color: "#64748b",
        }}
      >
        <span>-1.0</span>
        <span>{alphaMax.toFixed(1)}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inspect Panel (click-to-inspect a hex)
// ---------------------------------------------------------------------------

function InspectPanel({ hexId, metadata, snapshot, pairKeys, T, Lij, Lji, centroids, onClose }) {
  const meta = metadata[hexId];
  if (!meta) return null;

  // Find all pairs involving this hex
  const pairInfo = [];
  for (let k = 0; k < pairKeys.length; k++) {
    const [origin, dest] = pairKeys[k];
    if (origin === hexId || dest === hexId) {
      const direction = origin === hexId ? "Outbound" : "Inbound";
      const partner = origin === hexId ? dest : origin;
      const delta = (snapshot.P[k] - 1) * T[k];
      pairInfo.push({
        partner,
        direction,
        T_ij: T[k],
        P_ij: snapshot.P[k],
        delta,
        absDelta: Math.abs(delta),
        k,
      });
    }
  }
  pairInfo.sort((a, b) => b.absDelta - a.absDelta);
  const top5 = pairInfo.slice(0, 5);

  const topPartner = top5[0] || null;

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        right: 0,
        width: "40%",
        minWidth: 380,
        height: "100%",
        backgroundColor: "rgba(15, 23, 42, 0.95)",
        color: "#e2e8f0",
        overflowY: "auto",
        zIndex: 20,
        padding: 24,
        backdropFilter: "blur(12px)",
        borderLeft: "1px solid rgba(100, 116, 139, 0.3)",
      }}
    >
      {/* Close button */}
      <button
        onClick={onClose}
        style={{
          position: "absolute",
          top: 16,
          right: 16,
          background: "rgba(100, 116, 139, 0.3)",
          border: "none",
          color: "#e2e8f0",
          width: 32,
          height: 32,
          borderRadius: 8,
          cursor: "pointer",
          fontSize: 18,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        &times;
      </button>

      {/* Header */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: 1 }}>
          Hex Inspector
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "monospace", marginTop: 4 }}>
          {hexId}
        </div>
        {centroids[hexId] && (
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>
            {centroids[hexId][1].toFixed(4)}°N, {Math.abs(centroids[hexId][0]).toFixed(4)}°W
          </div>
        )}
      </div>

      {/* Section 1: Demographics */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginBottom: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>
          Demographics
        </div>

        <div style={{ display: "flex", gap: 16 }}>
          {/* Education */}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>Education Profile</div>
            {EDU_LABELS.map((label, i) => {
              const val = meta.edu_shares[i];
              const isMax = val === Math.max(...meta.edu_shares);
              return (
                <div key={i} style={{ display: "flex", alignItems: "center", marginBottom: 3 }}>
                  <span style={{ fontSize: 10, color: "#94a3b8", width: 72, textAlign: "right", marginRight: 6, flexShrink: 0 }}>
                    {label}
                  </span>
                  <div style={{ flex: 1, height: 12, backgroundColor: "rgba(100, 116, 139, 0.2)", borderRadius: 3, overflow: "hidden" }}>
                    <div
                      style={{
                        width: `${Math.max(1, val * 100)}%`,
                        height: "100%",
                        backgroundColor: isMax ? "#3b82f6" : "#475569",
                        borderRadius: 3,
                        transition: "width 0.3s",
                      }}
                    />
                  </div>
                  <span style={{ fontSize: 10, fontFamily: "monospace", color: "#94a3b8", width: 40, textAlign: "right", marginLeft: 4 }}>
                    {(val * 100).toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>

          {/* Industry (4+1) */}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>Industry Profile</div>
            {meta.ind_top4.map((item, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", marginBottom: 3 }}>
                <span style={{ fontSize: 10, color: "#94a3b8", width: 72, textAlign: "right", marginRight: 6, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {item.label}
                </span>
                <div style={{ flex: 1, height: 12, backgroundColor: "rgba(100, 116, 139, 0.2)", borderRadius: 3, overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${Math.max(1, item.share * 100)}%`,
                      height: "100%",
                      backgroundColor: i === 0 ? "#f59e0b" : "#78716c",
                      borderRadius: 3,
                    }}
                  />
                </div>
                <span style={{ fontSize: 10, fontFamily: "monospace", color: "#94a3b8", width: 40, textAlign: "right", marginLeft: 4 }}>
                  {(item.share * 100).toFixed(1)}%
                </span>
              </div>
            ))}
            {meta.ind_other_share > 0 && (
              <div style={{ display: "flex", alignItems: "center", marginBottom: 3 }}>
                <span style={{ fontSize: 10, color: "#64748b", width: 72, textAlign: "right", marginRight: 6, flexShrink: 0 }}>
                  Other
                </span>
                <div style={{ flex: 1, height: 12, backgroundColor: "rgba(100, 116, 139, 0.2)", borderRadius: 3, overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${Math.max(1, meta.ind_other_share * 100)}%`,
                      height: "100%",
                      backgroundColor: "#334155",
                      borderRadius: 3,
                    }}
                  />
                </div>
                <span style={{ fontSize: 10, fontFamily: "monospace", color: "#64748b", width: 40, textAlign: "right", marginLeft: 4 }}>
                  {(meta.ind_other_share * 100).toFixed(1)}%
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Section 2: Top Commute Partners */}
      {top5.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginBottom: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Top Commute Partners
          </div>
          <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ color: "#64748b", borderBottom: "1px solid rgba(100, 116, 139, 0.3)" }}>
                <th style={{ textAlign: "left", padding: "4px 6px" }}>Partner Hex</th>
                <th style={{ textAlign: "left", padding: "4px 6px" }}>Dir</th>
                <th style={{ textAlign: "right", padding: "4px 6px" }}>T</th>
                <th style={{ textAlign: "right", padding: "4px 6px" }}>P</th>
                <th style={{ textAlign: "right", padding: "4px 6px" }}>&Delta; Flow</th>
              </tr>
            </thead>
            <tbody>
              {top5.map((row, i) => (
                <tr key={i} style={{ borderBottom: "1px solid rgba(100, 116, 139, 0.15)" }}>
                  <td style={{ padding: "4px 6px", fontFamily: "monospace", fontSize: 10 }}>
                    {row.partner.slice(0, 7)}...{row.partner.slice(-3)}
                  </td>
                  <td style={{ padding: "4px 6px", color: row.direction === "Outbound" ? "#60a5fa" : "#f59e0b" }}>
                    {row.direction}
                  </td>
                  <td style={{ padding: "4px 6px", textAlign: "right", fontFamily: "monospace" }}>
                    {row.T_ij.toFixed(0)}
                  </td>
                  <td style={{ padding: "4px 6px", textAlign: "right", fontFamily: "monospace" }}>
                    {row.P_ij.toFixed(4)}
                  </td>
                  <td
                    style={{
                      padding: "4px 6px",
                      textAlign: "right",
                      fontFamily: "monospace",
                      color: row.delta < 0 ? "#60a5fa" : "#f87171",
                    }}
                  >
                    {row.delta >= 0 ? "+" : ""}{row.delta.toFixed(0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Section 3: Why This P Value */}
      {topPartner && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#94a3b8", marginBottom: 12, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Why This P Value
          </div>
          <div style={{ fontSize: 11, color: "#94a3b8", lineHeight: 1.8, fontFamily: "monospace" }}>
            {(() => {
              const k = topPartner.k;
              const [origin, dest] = pairKeys[k];
              const omega_ij = snapshot.Omega_ij[k];
              const omega_ji = snapshot.Omega_ji[k];
              const l_ij = Lij[k];
              const l_ji = Lji[k];
              const P = snapshot.P[k];
              const Ltotal = l_ij + l_ji;
              const isWeighted = Ltotal > 0;

              return (
                <div>
                  <div style={{ marginBottom: 8, color: "#e2e8f0" }}>
                    Pair: <span style={{ color: "#60a5fa" }}>{origin.slice(0, 9)}...</span>
                    {" \u2194 "}
                    <span style={{ color: "#f59e0b" }}>{dest.slice(0, 9)}...</span>
                  </div>
                  <div style={{ marginBottom: 4 }}>
                    &Omega;<sub>ij</sub> = {omega_ij.toFixed(4)}
                    <span style={{ color: "#64748b", marginLeft: 8 }}>
                      (residents {origin.slice(0, 7)}... &rarr; jobs {dest.slice(0, 7)}...)
                    </span>
                  </div>
                  <div style={{ marginBottom: 4 }}>
                    &Omega;<sub>ji</sub> = {omega_ji.toFixed(4)}
                    <span style={{ color: "#64748b", marginLeft: 8 }}>
                      (residents {dest.slice(0, 7)}... &rarr; jobs {origin.slice(0, 7)}...)
                    </span>
                  </div>
                  <div style={{ marginBottom: 4 }}>
                    L<sub>ij</sub> = {l_ij.toFixed(1)}, L<sub>ji</sub> = {l_ji.toFixed(1)}
                    <span style={{ color: "#64748b", marginLeft: 8 }}>
                      ({isWeighted ? "weighted" : "equal-weight fallback"})
                    </span>
                  </div>
                  <div
                    style={{
                      marginTop: 8,
                      padding: "8px 12px",
                      backgroundColor: "rgba(99, 102, 241, 0.15)",
                      borderRadius: 6,
                      color: "#c7d2fe",
                    }}
                  >
                    {isWeighted ? (
                      <>
                        P = (L<sub>ij</sub> &middot; &Omega;<sub>ij</sub> + L<sub>ji</sub> &middot; &Omega;<sub>ji</sub>) / (L<sub>ij</sub> + L<sub>ji</sub>)
                        <br />
                        P = ({l_ij.toFixed(1)} &times; {omega_ij.toFixed(4)} + {l_ji.toFixed(1)} &times; {omega_ji.toFixed(4)}) / {Ltotal.toFixed(1)}
                        <br />
                        <strong style={{ color: "#e2e8f0" }}>P = {P.toFixed(6)}</strong>
                      </>
                    ) : (
                      <>
                        P = (&Omega;<sub>ij</sub> + &Omega;<sub>ji</sub>) / 2
                        <br />
                        P = ({omega_ij.toFixed(4)} + {omega_ji.toFixed(4)}) / 2
                        <br />
                        <strong style={{ color: "#e2e8f0" }}>P = {P.toFixed(6)}</strong>
                      </>
                    )}
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export Dropdown
// ---------------------------------------------------------------------------

function ExportButton() {
  const [open, setOpen] = useState(false);

  const files = [
    { name: "hex_geometries.geojson", label: "Hex Geometries (GeoJSON)" },
    { name: "pairs_alpha_sweep.csv", label: "Pair-Level Data (CSV)" },
    { name: "hex_summary.csv", label: "Hex Summary (CSV)" },
  ];

  return (
    <div style={{ position: "absolute", bottom: 16, right: 16, zIndex: 10 }}>
      {open && (
        <div
          style={{
            backgroundColor: "rgba(15, 23, 42, 0.95)",
            borderRadius: 8,
            padding: 8,
            marginBottom: 8,
            backdropFilter: "blur(8px)",
          }}
        >
          {files.map((f) => (
            <a
              key={f.name}
              href={`/${f.name}`}
              download={f.name}
              style={{
                display: "block",
                padding: "8px 12px",
                color: "#e2e8f0",
                textDecoration: "none",
                fontSize: 12,
                borderRadius: 4,
              }}
              onMouseEnter={(e) =>
                (e.target.style.backgroundColor = "rgba(99, 102, 241, 0.2)")
              }
              onMouseLeave={(e) =>
                (e.target.style.backgroundColor = "transparent")
              }
            >
              {f.label}
            </a>
          ))}
        </div>
      )}
      <button
        onClick={() => setOpen(!open)}
        style={{
          backgroundColor: "rgba(15, 23, 42, 0.92)",
          color: "#e2e8f0",
          border: "1px solid rgba(100, 116, 139, 0.3)",
          borderRadius: 8,
          padding: "8px 16px",
          cursor: "pointer",
          fontSize: 12,
          fontWeight: 600,
          backdropFilter: "blur(8px)",
        }}
      >
        Export Data
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------

function App() {
  const { data, loading, error } = usePrecomputedData();
  const [alpha, setAlpha] = useState(0.25);
  const [selectedHex, setSelectedHex] = useState(null);

  // Find nearest snapshot
  const snapIndex = useMemo(() => {
    if (!data) return 0;
    return findNearestAlphaIndex(data.snapshots.alpha_values, alpha);
  }, [data, alpha]);

  const snapshot = data ? data.snapshots.snapshots[snapIndex] : null;

  // Alpha max from the data
  const alphaMax = data
    ? data.snapshots.alpha_values[data.snapshots.alpha_values.length - 1]
    : 2.0;

  // Color scale
  const colorFn = useMemo(() => {
    if (!data) return () => [200, 200, 200];
    return makeColorScale(data.globalMin, data.globalMax);
  }, [data]);

  // Top N arcs (most-changed pairs)
  const arcData = useMemo(() => {
    if (!data || !snapshot) return [];

    const pairKeys = data.snapshots.pair_keys;
    const T = data.snapshots.T;
    const centroids = data.centroids;

    // Compute absolute flow change per pair
    const changes = [];
    for (let k = 0; k < pairKeys.length; k++) {
      const absChange = Math.abs((snapshot.P[k] - 1) * T[k]);
      if (absChange > 0) {
        changes.push({ k, absChange });
      }
    }
    changes.sort((a, b) => b.absChange - a.absChange);
    const topN = changes.slice(0, TOP_N_ARCS);

    return topN.map(({ k }) => {
      const [origin, dest] = pairKeys[k];
      const P = snapshot.P[k];
      const change = (P - 1) * T[k];
      const color = colorFn(P - 1);

      return {
        source: centroids[origin] || [0, 0],
        target: centroids[dest] || [0, 0],
        P,
        T: T[k],
        change,
        color: [...color, 153], // 0.6 opacity = 153/255
        width: 1 + Math.min(5, (T[k] / Math.max(...T)) * 5),
      };
    });
  }, [data, snapshot, colorFn]);

  // Hex layer with net change coloring
  const hexLayer = useMemo(() => {
    if (!data || !snapshot) return null;

    return new GeoJsonLayer({
      id: "hex-choropleth",
      data: data.geojson,
      filled: true,
      stroked: true,
      pickable: true,
      getFillColor: (f) => {
        const hexId = f.properties.hex_id;
        const change = snapshot.hex_net_change[hexId] || 0;
        const color = colorFn(change);
        return [...color, 178]; // 0.7 opacity
      },
      getLineColor: [255, 255, 255, 40],
      getLineWidth: 0.5,
      lineWidthUnits: "pixels",
      onClick: (info) => {
        if (info.object) {
          setSelectedHex(info.object.properties.hex_id);
        }
      },
      updateTriggers: {
        getFillColor: [snapIndex],
      },
    });
  }, [data, snapshot, colorFn, snapIndex]);

  // Arc layer
  const arcLayer = useMemo(() => {
    if (!arcData.length) return null;

    return new ArcLayer({
      id: "flow-arcs",
      data: arcData,
      getSourcePosition: (d) => d.source,
      getTargetPosition: (d) => d.target,
      getSourceColor: (d) => d.color,
      getTargetColor: (d) => d.color,
      getWidth: (d) => d.width,
      getHeight: 0.3,
      widthUnits: "pixels",
    });
  }, [arcData]);

  const layers = [hexLayer, arcLayer].filter(Boolean);

  // Handle map click to deselect
  const handleMapClick = useCallback(
    (info) => {
      if (!info.object && selectedHex) {
        setSelectedHex(null);
      }
    },
    [selectedHex]
  );

  if (loading) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#0f172a",
          color: "#e2e8f0",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ fontSize: 24, fontWeight: 700 }}>
          Loading visualization data...
        </div>
        <div style={{ fontSize: 14, color: "#64748b" }}>
          This may take a moment for large datasets.
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#0f172a",
          color: "#e2e8f0",
          flexDirection: "column",
          gap: 16,
          padding: 40,
        }}
      >
        <div style={{ fontSize: 24, fontWeight: 700, color: "#f87171" }}>
          Failed to load data
        </div>
        <div style={{ fontSize: 14, color: "#94a3b8", maxWidth: 500, textAlign: "center" }}>
          {error}
        </div>
        <div style={{ fontSize: 13, color: "#64748b", maxWidth: 500, textAlign: "center" }}>
          Make sure you have run the precomputation script first:
          <br />
          <code style={{ color: "#a5b4fc" }}>
            python scripts/precompute_viz_data.py
          </code>
          <br />
          and that the viz_data/ directory contains the output files.
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <DeckGL
        initialViewState={INITIAL_VIEW_STATE}
        controller={true}
        layers={layers}
        onClick={handleMapClick}
      >
        <Map
          mapboxAccessToken={MAPBOX_TOKEN}
          mapStyle={MAP_STYLE}
          reuseMaps
        />
      </DeckGL>

      <AlphaSlider
        alpha={alpha}
        alphaMax={alphaMax}
        onChange={setAlpha}
        percentChange={snapshot ? snapshot.percent_change : 0}
      />

      {snapshot && (
        <SummaryPanel
          snapshot={snapshot}
          PValues={snapshot.P}
        />
      )}

      {selectedHex && data && snapshot && (
        <InspectPanel
          hexId={selectedHex}
          metadata={data.metadata}
          snapshot={snapshot}
          pairKeys={data.snapshots.pair_keys}
          T={data.snapshots.T}
          Lij={data.snapshots.L_ij}
          Lji={data.snapshots.L_ji}
          centroids={data.centroids}
          onClose={() => setSelectedHex(null)}
        />
      )}

      <ExportButton />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mount
// ---------------------------------------------------------------------------

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
