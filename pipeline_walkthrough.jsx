import { useState, useMemo } from "react";

// ── Real validation data (Example 1: NYC Intra-City) ──
const TRACTS = {
  A: {
    id: "36061000700",
    label: "Tract 7 (FiDi / WTC)",
    edu: [0.0164, 0.0393, 0.0806, 0.4968, 0.3668],
    ind: [0.0000, 0.0001, 0.0000, 0.0203, 0.0011, 0.0325, 0.0686, 0.0140, 0.0345, 0.1977, 0.0124, 0.2329, 0.0185, 0.0651, 0.0128, 0.1518, 0.0102, 0.0402, 0.0420, 0.0451],
  },
  B: {
    id: "36061018400",
    label: "Tract 184 (East Harlem)",
    edu: [0.1789, 0.1969, 0.2763, 0.2235, 0.1244],
    ind: [0.0000, 0.0000, 0.0000, 0.0288, 0.0051, 0.0010, 0.0884, 0.0000, 0.0031, 0.0051, 0.0771, 0.0175, 0.0000, 0.0051, 0.1716, 0.2960, 0.0000, 0.0740, 0.1059, 0.1213],
  },
};

const L_AB = 0;
const L_BA = 23;
const T_AB = 2200;

// Default parameters
const W_E = [0.035, 0.085, 0.183, 0.384, 0.436];
const U_E = [0.098, 0.183, 0.317, 0.556, 0.674];
const W_O = [0.123,0.162,0.277,0.089,0.196,0.234,0.110,0.080,0.500,0.595,0.421,0.597,0.199,0.199,0.197,0.181,0.187,0.043,0.177,0.271];
const U_O = [0.20,0.25,0.37,0.19,0.22,0.52,0.14,0.19,0.72,0.76,0.60,0.80,0.79,0.31,0.83,0.25,0.30,0.08,0.31,0.41];

const EDU_LABELS = ["< HS", "HS Diploma", "Some College", "Bachelor's", "Advanced"];
const IND_LABELS = ["Ag/Fish","Mining","Utilities","Construction","Manufacturing","Wholesale","Retail","Transport","Info","Finance","Real Estate","Prof/Sci","Mgmt","Admin","Education","Healthcare","Arts","Food/Accom","Other Svc","Public Admin"];

// ── Computation functions (mirrors the Python module) ──
function computeJoint(a, b) {
  return a.map((ae, i) => b.map((bo, j) => 1 - (1 - ae) * (1 - bo)));
}
function computeDeltas(alpha, w_eo, u_eo) {
  return w_eo.map((row, i) => row.map((w, j) => Math.max(-w, Math.min(alpha * w, u_eo[i][j] - w))));
}
function computeWeights(dw, w_eo) {
  return w_eo.map((row, i) => row.map((w, j) => {
    const denom = 1 - w;
    return denom === 0 ? 1 : 1 - dw[i][j] / denom;
  }));
}
function computePhi(W_eo, indShares) {
  return EDU_LABELS.map((_, e) => W_eo[e].reduce((sum, w, o) => sum + w * indShares[o], 0));
}
function dot(a, b) { return a.reduce((s, v, i) => s + v * b[i], 0); }

// ── Color utilities ──
function heatColor(val, min, max) {
  const t = Math.max(0, Math.min(1, (val - min) / (max - min || 1)));
  const r = Math.round(59 + t * (220 - 59));
  const g = Math.round(130 + (1-t) * (90));
  const b_c = Math.round(246 - t * (200));
  return `rgb(${r},${g},${b_c})`;
}
function barColor(val) {
  if (val > 1.02) return "#22c55e";
  if (val < 0.98) return "#f97316";
  return "#94a3b8";
}

// ── Components ──
function StepHeader({ num, title, active, onClick }) {
  return (
    <button onClick={onClick} className={`w-full text-left px-4 py-3 rounded-lg border transition-all ${active ? "bg-indigo-50 border-indigo-300 shadow-sm" : "bg-white border-gray-200 hover:border-gray-300"}`}>
      <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-sm font-bold mr-3 ${active ? "bg-indigo-600 text-white" : "bg-gray-200 text-gray-600"}`}>{num}</span>
      <span className={`font-medium ${active ? "text-indigo-900" : "text-gray-700"}`}>{title}</span>
    </button>
  );
}

function BarChart({ data, labels, title, color, maxVal }) {
  const mx = maxVal || Math.max(...data, 0.01);
  return (
    <div className="mb-4">
      <div className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">{title}</div>
      <div className="space-y-1">
        {data.map((v, i) => (
          <div key={i} className="flex items-center gap-2">
            <div className="text-xs text-gray-600 w-24 text-right truncate">{labels[i]}</div>
            <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
              <div className="h-full rounded-full transition-all duration-500" style={{ width: `${Math.max(1, (v / mx) * 100)}%`, backgroundColor: color || "#6366f1" }} />
            </div>
            <div className="text-xs text-gray-500 w-12 text-right font-mono">{(v * 100).toFixed(1)}%</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HeatmapMini({ matrix, rowLabels, title, fmt }) {
  const flat = matrix.flat();
  const mn = Math.min(...flat);
  const mx = Math.max(...flat);
  return (
    <div className="mb-4">
      <div className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">{title}</div>
      <div className="overflow-x-auto">
        <div className="inline-grid gap-px" style={{ gridTemplateColumns: `80px repeat(${matrix[0].length}, 1fr)` }}>
          <div />
          {matrix[0].map((_, j) => <div key={j} className="text-center text-xs text-gray-400 px-1 truncate" style={{fontSize: 9, minWidth: 28}}>{IND_LABELS[j].slice(0,5)}</div>)}
          {matrix.map((row, i) => (
            <>
              <div key={`l${i}`} className="text-xs text-gray-600 text-right pr-2 flex items-center justify-end">{rowLabels[i]}</div>
              {row.map((v, j) => (
                <div key={`${i}-${j}`} className="flex items-center justify-center rounded text-xs font-mono" style={{ backgroundColor: heatColor(v, mn, mx), color: v > (mn+mx)/2 ? "#fff" : "#1e293b", minWidth: 28, height: 22, fontSize: 9 }}>
                  {fmt ? fmt(v) : v.toFixed(2)}
                </div>
              ))}
            </>
          ))}
        </div>
      </div>
    </div>
  );
}

function FlowDiagram({ omega_ij, omega_ji, L_ij, L_ji, P_ij, G_ij, T_ij, tractA, tractB }) {
  const barW = Math.max(20, Math.min(120, P_ij * 120));
  return (
    <div className="flex flex-col items-center gap-3 py-4">
      <div className="flex items-center gap-6 w-full max-w-2xl">
        <div className="flex-1 text-center p-3 rounded-lg bg-blue-50 border border-blue-200">
          <div className="text-xs text-blue-600 font-semibold">Residence</div>
          <div className="text-sm font-bold text-blue-900 truncate">{tractA}</div>
          <div className="text-xs text-blue-500 mt-1">Education mix</div>
        </div>
        <div className="flex flex-col items-center gap-1 min-w-36">
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400">L={L_ij}</span>
            <svg width="80" height="16"><line x1="0" y1="8" x2="70" y2="8" stroke="#94a3b8" strokeWidth="2" markerEnd="url(#arr)"/><defs><marker id="arr" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#94a3b8"/></marker></defs></svg>
          </div>
          <div className="text-xs font-mono font-bold" style={{ color: barColor(P_ij) }}>
            P = {P_ij.toFixed(4)}
          </div>
          <div className="flex items-center gap-1">
            <svg width="80" height="16"><line x1="70" y1="8" x2="0" y2="8" stroke="#94a3b8" strokeWidth="2" markerEnd="url(#arr2)"/><defs><marker id="arr2" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto-start-reverse"><path d="M8,0 L0,3 L8,6" fill="#94a3b8"/></marker></defs></svg>
            <span className="text-xs text-gray-400">L={L_ji}</span>
          </div>
        </div>
        <div className="flex-1 text-center p-3 rounded-lg bg-amber-50 border border-amber-200">
          <div className="text-xs text-amber-600 font-semibold">Workplace</div>
          <div className="text-sm font-bold text-amber-900 truncate">{tractB}</div>
          <div className="text-xs text-amber-500 mt-1">Industry mix</div>
        </div>
      </div>
      <div className="flex items-center gap-4 mt-2">
        <div className="text-center">
          <div className="text-xs text-gray-400">Baseline T</div>
          <div className="text-lg font-bold text-gray-700">{T_ij.toLocaleString()}</div>
        </div>
        <div className="text-2xl text-gray-300">&times;</div>
        <div className="text-center">
          <div className="text-xs text-gray-400">P_ij</div>
          <div className="text-lg font-bold" style={{ color: barColor(P_ij) }}>{P_ij.toFixed(4)}</div>
        </div>
        <div className="text-2xl text-gray-300">=</div>
        <div className="text-center">
          <div className="text-xs text-gray-400">Perturbed G</div>
          <div className="text-lg font-bold text-indigo-600">{G_ij.toFixed(0)}</div>
        </div>
        <div className="text-center ml-4 px-3 py-1 rounded-full text-sm font-semibold" style={{ backgroundColor: "#fef2f2", color: "#dc2626" }}>
          {((P_ij - 1) * 100).toFixed(1)}%
        </div>
      </div>
    </div>
  );
}

// ── Main App ──
export default function App() {
  const [alpha, setAlpha] = useState(0.25);
  const [step, setStep] = useState(0);

  const computed = useMemo(() => {
    const w_eo = computeJoint(W_E, W_O);
    const u_eo = computeJoint(U_E, U_O);
    const dw_eo = computeDeltas(alpha, w_eo, u_eo);
    const W_eo_mat = computeWeights(dw_eo, w_eo);
    const phi_A = computePhi(W_eo_mat, TRACTS.A.ind);
    const phi_B = computePhi(W_eo_mat, TRACTS.B.ind);
    const omega_AB = dot(TRACTS.A.edu, phi_B);
    const omega_BA = dot(TRACTS.B.edu, phi_A);
    const Ltot = L_AB + L_BA;
    const P_ij = Ltot > 0
      ? (L_AB * omega_AB + L_BA * omega_BA) / Ltot
      : (omega_AB + omega_BA) / 2;
    const G_ij = T_AB * P_ij;
    return { w_eo, u_eo, dw_eo, W_eo_mat, phi_A, phi_B, omega_AB, omega_BA, P_ij, G_ij };
  }, [alpha]);

  const steps = [
    { num: 1, title: "Who lives and works where?" },
    { num: 2, title: "Joint WFH propensity matrix" },
    { num: 3, title: "Apply alpha to get perturbation weights" },
    { num: 4, title: "Aggregate to tract-pair factor P" },
    { num: 5, title: "Perturbed flow G = T × P" },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-indigo-50 p-6">
      <div className="max-w-4xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">WFH Perturbation Pipeline</h1>
          <p className="text-sm text-gray-500 mt-1">Example 1: Financial District (Tract 7) to East Harlem (Tract 184), Manhattan</p>
        </div>

        {/* Alpha slider */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 mb-6 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Scaling factor &alpha;</span>
            <span className="text-lg font-mono font-bold text-indigo-600">{alpha.toFixed(2)}</span>
          </div>
          <input type="range" min="-1" max="2" step="0.01" value={alpha} onChange={e => setAlpha(+e.target.value)} className="w-full accent-indigo-600" />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>-1.0 (eliminate WFH)</span>
            <span>0 (no change)</span>
            <span>+2.0 (aggressive WFH)</span>
          </div>
        </div>

        {/* Step navigation */}
        <div className="grid grid-cols-5 gap-2 mb-6">
          {steps.map((s, i) => <StepHeader key={i} {...s} active={step === i} onClick={() => setStep(i)} />)}
        </div>

        {/* Step content */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm min-h-64">
          {step === 0 && (
            <div>
              <p className="text-sm text-gray-600 mb-4">Each tract has an <span className="font-semibold text-blue-700">education profile</span> (where people live) and an <span className="font-semibold text-amber-700">industry profile</span> (where people work). These come from ACS and LODES data respectively.</p>
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <div className="text-sm font-bold text-gray-800 mb-3">{TRACTS.A.label}</div>
                  <BarChart data={TRACTS.A.edu} labels={EDU_LABELS} title="Education (residence)" color="#3b82f6" maxVal={0.6} />
                  <BarChart data={TRACTS.A.ind.filter((_,i) => TRACTS.A.ind[i] > 0.02)} labels={IND_LABELS.filter((_,i) => TRACTS.A.ind[i] > 0.02)} title="Top industries (workplace)" color="#f59e0b" maxVal={0.3} />
                </div>
                <div>
                  <div className="text-sm font-bold text-gray-800 mb-3">{TRACTS.B.label}</div>
                  <BarChart data={TRACTS.B.edu} labels={EDU_LABELS} title="Education (residence)" color="#3b82f6" maxVal={0.6} />
                  <BarChart data={TRACTS.B.ind.filter((_,i) => TRACTS.B.ind[i] > 0.02)} labels={IND_LABELS.filter((_,i) => TRACTS.B.ind[i] > 0.02)} title="Top industries (workplace)" color="#f59e0b" maxVal={0.3} />
                </div>
              </div>
              <p className="text-xs text-gray-400 mt-4">FiDi is 86% bachelor's+advanced, heavy in finance/professional services. East Harlem is more mixed, with healthcare, education, and food services dominating.</p>
            </div>
          )}

          {step === 1 && (
            <div>
              <p className="text-sm text-gray-600 mb-4">For each of the 100 education-industry segments, the <span className="font-semibold">joint baseline propensity</span> w_eo combines education and industry WFH rates: w_eo = 1 - (1-w_e)(1-w_o). Higher values mean more people already work from home in that segment.</p>
              <HeatmapMini matrix={computed.w_eo} rowLabels={EDU_LABELS} title="Joint baseline WFH propensity (w_eo)" fmt={v => (v*100).toFixed(0) + "%"} />
              <p className="text-xs text-gray-400 mt-2">Advanced-degree workers in professional services (bottom-right) have ~77% combined WFH propensity. Less-than-HS workers in food service (top, toward right) are at ~8%.</p>
            </div>
          )}

          {step === 2 && (
            <div>
              <p className="text-sm text-gray-600 mb-4">Alpha = <span className="font-mono font-bold text-indigo-600">{alpha.toFixed(2)}</span> scales each segment's WFH rate proportionally, clamped by structural bounds. This produces <span className="font-semibold">perturbation weights</span> W_eo: the fraction of commute trips that survive. {alpha > 0 ? "Values below 1 mean fewer trips." : alpha < 0 ? "Values above 1 mean more trips." : "At alpha=0, all weights are 1 (no change)."}</p>
              <HeatmapMini matrix={computed.W_eo_mat} rowLabels={EDU_LABELS} title={`Perturbation weights W_eo (α = ${alpha.toFixed(2)})`} fmt={v => v.toFixed(2)} />
              <p className="text-xs text-gray-400 mt-2">{alpha > 0 ? "Lower values (darker) = more WFH = bigger trip reduction. High-education, high-telework industries see the largest effect." : alpha < 0 ? "Values above 1 mean WFH is decreasing, so more people commute. The effect is larger where baseline WFH was higher." : "All 1.00 means no perturbation."}</p>
            </div>
          )}

          {step === 3 && (
            <div>
              <p className="text-sm text-gray-600 mb-4">For each tract pair, the W_eo matrix gets weighted by the <span className="text-blue-600 font-semibold">residence education mix</span> and the <span className="text-amber-600 font-semibold">workplace industry mix</span> to produce a single directional factor &Omega;. Note the asymmetry: &Omega;(A&rarr;B) uses A's education with B's industry, while &Omega;(B&rarr;A) uses B's education with A's industry.</p>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div className="p-4 rounded-lg bg-blue-50 border border-blue-200">
                  <div className="text-xs font-semibold text-blue-600 mb-1">&Omega;(A&rarr;B): FiDi residents &rarr; E. Harlem jobs</div>
                  <div className="text-2xl font-mono font-bold text-blue-900">{computed.omega_AB.toFixed(4)}</div>
                  <div className="text-xs text-blue-500 mt-1">FiDi's highly educated residents &times; E. Harlem's healthcare/education jobs</div>
                </div>
                <div className="p-4 rounded-lg bg-amber-50 border border-amber-200">
                  <div className="text-xs font-semibold text-amber-600 mb-1">&Omega;(B&rarr;A): E. Harlem residents &rarr; FiDi jobs</div>
                  <div className="text-2xl font-mono font-bold text-amber-900">{computed.omega_BA.toFixed(4)}</div>
                  <div className="text-xs text-amber-500 mt-1">E. Harlem's mixed-education residents &times; FiDi's finance/professional jobs</div>
                </div>
              </div>
              <div className="p-4 rounded-lg bg-gray-50 border border-gray-200">
                <div className="text-xs font-semibold text-gray-500 mb-1">Symmetric P (LODES-weighted)</div>
                <p className="text-xs text-gray-500 mb-2">P = (L_AB&middot;&Omega;_AB + L_BA&middot;&Omega;_BA) / (L_AB + L_BA). Here L_AB=0, L_BA=23, so P is pulled entirely toward &Omega;_BA = {computed.omega_BA.toFixed(4)}.</p>
                <div className="text-2xl font-mono font-bold" style={{ color: barColor(computed.P_ij) }}>P = {computed.P_ij.toFixed(4)}</div>
              </div>
            </div>
          )}

          {step === 4 && (
            <div>
              <p className="text-sm text-gray-600 mb-4">The final step: multiply the Deep Gravity baseline flow by the symmetric perturbation factor. Drag the &alpha; slider to see how the perturbed flow changes in real time.</p>
              <FlowDiagram
                omega_ij={computed.omega_AB} omega_ji={computed.omega_BA}
                L_ij={L_AB} L_ji={L_BA}
                P_ij={computed.P_ij} G_ij={computed.G_ij} T_ij={T_AB}
                tractA={TRACTS.A.label} tractB={TRACTS.B.label}
              />
              <div className="mt-4 p-3 rounded-lg bg-indigo-50 border border-indigo-200 text-sm text-indigo-800">
                {alpha > 0 ? (
                  <span>At &alpha;={alpha.toFixed(2)}, the {T_AB.toLocaleString()} baseline trips between these tracts drop to <strong>{computed.G_ij.toFixed(0)}</strong>, a <strong>{((1-computed.P_ij)*100).toFixed(1)}%</strong> reduction. This reflects the high WFH potential of the finance and professional workers commuting from FiDi to East Harlem jobs (and vice versa).</span>
                ) : alpha < 0 ? (
                  <span>At &alpha;={alpha.toFixed(2)}, WFH is decreasing. The {T_AB.toLocaleString()} baseline trips grow to <strong>{computed.G_ij.toFixed(0)}</strong>, a <strong>{((computed.P_ij-1)*100).toFixed(1)}%</strong> increase as fewer workers stay home.</span>
                ) : (
                  <span>At &alpha;=0, no perturbation. The flow stays at {T_AB.toLocaleString()} trips.</span>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
