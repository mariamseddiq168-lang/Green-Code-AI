import { useState } from "react";
import {
  Leaf,
  LayoutDashboard,
  Code2,
  Zap,
  Settings,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Sparkles,
  ChevronDown,
} from "lucide-react";

const API_BASE = "http://127.0.0.1:8000";

const LANGUAGES = [
  { value: "python", label: "Python" },
  { value: "javascript", label: "JavaScript" },
  { value: "java", label: "Java" },
  { value: "cpp", label: "C++" },
];

function SeverityBadge({ severity }) {
  return (
    <span className={`severity-badge severity-${severity}`}>
      {severity}
    </span>
  );
}

function AccordionSection({ title, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="accordion-section">
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((prev) => !prev)}
      >
        <span>{title}</span>
        <ChevronDown
          size={18}
          className={open ? "chevron chevron-open" : "chevron"}
        />
      </button>
      {open && <div className="accordion-body">{children}</div>}
    </div>
  );
}

export default function App() {
  const [language, setLanguage] = useState("python");
  const [code, setCode] = useState("");

  const [analysisResult, setAnalysisResult] = useState(null);
  const [refactorResult, setRefactorResult] = useState(null);

  const [loading, setLoading] = useState(false);
  const [refactorLoading, setRefactorLoading] = useState(false);

  const [error, setError] = useState(null);

  async function handleAnalyze() {
    setError(null);
    setLoading(true);
    setAnalysisResult(null);

    try {
      const response = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data?.detail || "Analyze request failed. Please try again."
        );
      }

      setAnalysisResult(data);
    } catch (err) {
      setError(err.message || "Something went wrong while analyzing the code.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRefactor() {
    setError(null);
    setRefactorLoading(true);
    setRefactorResult(null);

    try {
      const response = await fetch(`${API_BASE}/refactor`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, language }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data?.detail || "Refactor request failed. Please try again."
        );
      }

      setRefactorResult(data);
    } catch (err) {
      setError(err.message || "Something went wrong while refactoring the code.");
    } finally {
      setRefactorLoading(false);
    }
  }

  const analysis = analysisResult?.result;
  const aiAnalysis = refactorResult?.ai_analysis;
  const diff = refactorResult?.diff;
  const validation = refactorResult?.validation;
  const energy = refactorResult?.energy;

  // If energy data exists, only treat the refactor as "improved" when it
  // actually used less energy than the original. Missing energy data does
  // not block showing the AI suggestion.
  const isRefactorImproved =
    energy?.original?.estimated_energy_joules != null &&
    energy?.refactored?.estimated_energy_joules != null
      ? energy.refactored.estimated_energy_joules <
        energy.original.estimated_energy_joules
      : true;

  const carbonSaved = energy?.carbon_comparison?.carbon_saved_grams_co2e;
  const carbonSavedPercent = energy?.carbon_comparison?.carbon_saved_percent;
  const carbonImproved = carbonSaved != null && carbonSaved > 0;

  return (
    <div className="app">
      {/* ================= Sidebar ================= */}
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-icon">
            <Leaf size={22} color="#166534" />
          </span>
          GreenCode AI
        </div>

        <nav>
          <div className="nav-item active">
            <LayoutDashboard size={18} />
            Dashboard
          </div>
          <div className="nav-item">
            <Code2 size={18} />
            Code Analysis
          </div>
          <div className="nav-item">
            <Zap size={18} />
            Energy
          </div>
          <div className="nav-item">
            <Leaf size={18} />
            Carbon
          </div>
          <div className="nav-item">
            <Settings size={18} />
            Settings
          </div>
        </nav>

        <div className="sidebar-footer">
          <Sparkles size={14} />
          Powered by Gemini
        </div>
      </aside>

      {/* ================= Main ================= */}
      <main className="main">
        <div className="header">
          <div className="eyebrow">
            <Leaf size={16} />
            Sustainable Software
          </div>
          <h1>GreenCode Dashboard</h1>
          <p>
            Analyze, optimize, and understand the environmental impact of
            your code.
          </p>
        </div>

        {/* Overview cards */}
        <div className="stats">
          <div className="card">
            <div className="card-icon">
              <Code2 size={22} color="#166534" />
            </div>
            <div>
              <h3>Code Analysis</h3>
              <p>Static complexity and efficiency signals for your code.</p>
            </div>
          </div>

          <div className="card">
            <div className="card-icon">
              <Zap size={22} color="#166534" />
            </div>
            <div>
              <h3>Energy</h3>
              <p>Measured CPU time and estimated power usage.</p>
            </div>
          </div>

          <div className="card">
            <div className="card-icon">
              <Leaf size={22} color="#166534" />
            </div>
            <div>
              <h3>Carbon</h3>
              <p>Estimated CO2e emissions before and after refactoring.</p>
            </div>
          </div>
        </div>

        {/* Code input section */}
        <div className="code-section">
          <div className="section-header">
            <div>
              <h2>Analyze Your Code</h2>
              <p>Paste your code, choose a language, and run the analysis.</p>
            </div>

            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
              {LANGUAGES.map((lang) => (
                <option key={lang.value} value={lang.value}>
                  {lang.label}
                </option>
              ))}
            </select>
          </div>

          <textarea
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Paste your code here..."
            spellCheck="false"
          />

          {error && (
            <div className="error-box">
              <AlertTriangle size={18} />
              {error}
            </div>
          )}

          <div className="action-row">
            <button
              className="primary-button"
              onClick={handleAnalyze}
              disabled={!code.trim() || loading || refactorLoading}
            >
              {loading ? (
                <>
                  <Loader2 size={18} className="spin" />
                  Analyzing...
                </>
              ) : (
                <>
                  <Code2 size={18} />
                  Analyze Code
                </>
              )}
            </button>

            <button
              className="secondary-button"
              onClick={handleRefactor}
              disabled={!code.trim() || loading || refactorLoading}
            >
              {refactorLoading ? (
                <>
                  <Loader2 size={18} className="spin" />
                  Refactoring...
                </>
              ) : (
                <>
                  <Sparkles size={18} />
                  Refactor Code
                </>
              )}
            </button>
          </div>
        </div>

        {/* Analysis results */}
        {analysis && (
          <div className="results-section">
            <div className="results-header">
              <h2>Analysis Results</h2>
              <p>
                {analysis.syntax_valid ? (
                  <span className="status-ok">
                    <CheckCircle2 size={16} /> Code is valid
                  </span>
                ) : (
                  <span className="status-error">
                    <XCircle size={16} /> Syntax error
                  </span>
                )}
              </p>
            </div>

            <div className="result-grid">
              <div className="result-card">
                <span>Complexity</span>
                <strong>{analysis.complexity?.notation ?? "-"}</strong>
              </div>
              <div className="result-card">
                <span>Functions</span>
                <strong>{analysis.function_count ?? "-"}</strong>
              </div>
              <div className="result-card">
                <span>Loops</span>
                <strong>{analysis.loop_count ?? "-"}</strong>
              </div>
              <div className="result-card">
                <span>Nested Loops</span>
                <strong>{analysis.nested_loop_count ?? "-"}</strong>
              </div>
            </div>

            {analysis.findings?.length > 0 && (
              <div className="findings">
                <h3>Findings</h3>
                {analysis.findings.map((finding, index) => (
                  <div className="finding-item" key={index}>
                    <div className="finding-item-header">
                      <strong>{finding.detector}</strong>
                      <SeverityBadge severity={finding.severity} />
                    </div>
                    <p>{finding.message}</p>
                    {finding.line != null && (
                      <span className="finding-line">Line {finding.line}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* AI Refactoring results */}
        {aiAnalysis && (
          <div className="results-section">
            <div className="results-header">
              <h2>AI Refactoring Results</h2>
              <p>Suggestions generated by Gemini.</p>
            </div>

            {/* Energy & Carbon comparison — always shown when available */}
            {energy && (
              <div className="subsection">
                <h3>Energy &amp; Carbon Comparison</h3>
                <div className="energy-comparison">
                  <div className="energy-card energy-original">
                    <span className="energy-card-title">Original</span>
                    <div className="energy-row">
                      <span>Execution Time</span>
                      <strong>
                        {energy.original?.execution_time_seconds?.toFixed(4)} s
                      </strong>
                    </div>
                    <div className="energy-row">
                      <span>Energy</span>
                      <strong>
                        {energy.original?.estimated_energy_joules?.toFixed(4)} J
                      </strong>
                    </div>
                    <div className="energy-row">
                      <span>Carbon</span>
                      <strong>
                        {energy.original?.estimated_carbon_grams_co2e?.toFixed(6)}{" "}
                        g CO2e
                      </strong>
                    </div>
                  </div>

                  <div className="energy-card energy-refactored">
                    <span className="energy-card-title">Refactored</span>
                    <div className="energy-row">
                      <span>Execution Time</span>
                      <strong>
                        {energy.refactored?.execution_time_seconds?.toFixed(4)} s
                      </strong>
                    </div>
                    <div className="energy-row">
                      <span>Energy</span>
                      <strong>
                        {energy.refactored?.estimated_energy_joules?.toFixed(4)} J
                      </strong>
                    </div>
                    <div className="energy-row">
                      <span>Carbon</span>
                      <strong>
                        {energy.refactored?.estimated_carbon_grams_co2e?.toFixed(6)}{" "}
                        g CO2e
                      </strong>
                    </div>
                  </div>
                </div>

                {carbonSaved != null && (
                  <div
                    className={
                      carbonImproved
                        ? "carbon-savings carbon-savings-good"
                        : "carbon-savings carbon-savings-bad"
                    }
                  >
                    <Leaf size={18} />
                    {carbonImproved ? "Carbon saved: " : "Carbon increased: "}
                    <strong>
                      {Math.abs(carbonSaved).toFixed(6)} g CO2e (
                      {Math.abs(carbonSavedPercent ?? 0).toFixed(2)}%)
                    </strong>
                  </div>
                )}
              </div>
            )}

            {!isRefactorImproved ? (
              <div className="not-improved-box">
                <XCircle size={20} />
                <div>
                  <strong>No improvement found</strong>
                  <p>
                    The AI-suggested refactor did not use less energy than
                    the original code in this run, so the suggestion is not
                    shown. Note: for very short-running snippets, timing
                    measurements can vary between runs — try a larger
                    example for a more reliable comparison.
                  </p>
                </div>
              </div>
            ) : (
              <>
                <AccordionSection title="Overall Assessment" defaultOpen>
                  <p>{aiAnalysis.overall_assessment}</p>
                </AccordionSection>

                {aiAnalysis.problems?.length > 0 && (
                  <AccordionSection title="AI Detected Problems">
                    {aiAnalysis.problems.map((problem, index) => (
                      <div className="finding-item" key={index}>
                        <div className="finding-item-header">
                          <strong>{problem.type}</strong>
                          <SeverityBadge severity={problem.severity} />
                        </div>
                        <p>{problem.explanation}</p>
                        <p className="finding-suggestion">
                          Suggestion: {problem.suggestion}
                        </p>
                        {problem.line != null && (
                          <span className="finding-line">
                            Line {problem.line}
                          </span>
                        )}
                      </div>
                    ))}
                  </AccordionSection>
                )}

                <AccordionSection title="Refactored Code">
                  <pre className="code-block">
                    <code>{aiAnalysis.refactored_code}</code>
                  </pre>
                </AccordionSection>

                <AccordionSection title="Explanation">
                  <p>{aiAnalysis.explanation}</p>
                </AccordionSection>

                {aiAnalysis.improvements?.length > 0 && (
                  <AccordionSection title="Improvements">
                    <ul className="improvements-list">
                      {aiAnalysis.improvements.map((improvement, index) => (
                        <li key={index}>{improvement}</li>
                      ))}
                    </ul>
                  </AccordionSection>
                )}

                <AccordionSection title="Estimated Impact">
                  <p>{aiAnalysis.estimated_impact}</p>
                </AccordionSection>

                {diff?.length > 0 && (
                  <AccordionSection title="Code Changes">
                    <div className="diff-view">
                      {diff.map((line, index) => (
                        <div
                          className={`diff-line diff-${line.type}`}
                          key={index}
                        >
                          <span className="diff-marker">
                            {line.type === "added" ? "+" : "-"}
                          </span>
                          <span className="diff-text">{line.line}</span>
                        </div>
                      ))}
                    </div>
                  </AccordionSection>
                )}

                <div className="subsection">
                  <h3>Validation</h3>
                  {validation ? (
                    <span className="status-ok">
                      <CheckCircle2 size={16} /> Refactoring validated
                      successfully
                    </span>
                  ) : (
                    <span className="status-error">
                      <XCircle size={16} /> Refactoring validation failed
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
