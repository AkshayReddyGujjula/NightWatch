export function StateStrip() {
  return (
    <header className="state-strip">
      <div className="brand">NIGHTWATCH</div>
      <dl className="state-facts">
        <div>
          <dt>Incident</dt>
          <dd className="muted">none yet</dd>
        </div>
        <div>
          <dt>State</dt>
          <dd>
            <span className="badge idle">IDLE</span>
          </dd>
        </div>
        <div>
          <dt>Elapsed</dt>
          <dd className="muted">—</dd>
        </div>
      </dl>
      <button
        type="button"
        className="safe-stop"
        disabled
        title="Wired to POST /api/incidents/{id}/safe-stop when the control API lands. Never restores the buggy path."
      >
        SAFE STOP
      </button>
    </header>
  );
}
