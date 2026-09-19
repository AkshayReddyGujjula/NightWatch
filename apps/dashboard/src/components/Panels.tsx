import { Empty, Panel } from "./Panel";

export function LedgerPanel() {
  return (
    <Panel title="Trusted money truth">
      <Empty>
        No ledger rows yet. The append-only provider ledger is read through the control API —
        nothing on this dashboard is mocked.
      </Empty>
      <p className="caption">
        Expected evidence: one intent → two captures with distinct keys (the incident), then exactly
        one capture after activation.
      </p>
    </Panel>
  );
}

export function WorldsPanel() {
  return (
    <Panel title="Candidate worlds">
      <Empty>
        No candidate worlds. Three concurrent Modal Sandboxes (A/B/C) appear here with real sandbox
        ids and created / ready / finished / terminated timestamps.
      </Empty>
      <p className="caption">
        The overlap graph and measured peak concurrency come from lifecycle timestamps, never from
        an animation.
      </p>
    </Panel>
  );
}

export function DecisionPanel() {
  return (
    <Panel title="Decision">
      <Empty>
        No selection yet. Deterministic policy chooses the lowest-ranked live-eligible candidate that
        passes every required gate; a model never selects and never issues the lease.
      </Empty>
    </Panel>
  );
}

export function ReceiptPanel() {
  return (
    <Panel title="Receipt">
      <Empty>No receipt yet (final or explicitly partial).</Empty>
      <p className="caption">
        The receipt must carry <code>demo_mode</code> and <code>degraded_reasons</code> — including
        the browser-stack failure explicitly while browser scenarios are reduced.
      </p>
    </Panel>
  );
}
