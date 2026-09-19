import { BrowserBlockerPanel } from "./components/BrowserBlockerPanel";
import { FrameWall } from "./components/FrameWall";
import { DecisionPanel, LedgerPanel, ReceiptPanel, WorldsPanel } from "./components/Panels";
import { ScenarioMatrix } from "./components/ScenarioMatrix";
import { StateStrip } from "./components/StateStrip";

export default function App() {
  return (
    <div className="app">
      <StateStrip />
      <main className="grid">
        <LedgerPanel />
        <WorldsPanel />
        <DecisionPanel />
        <ReceiptPanel />
        <ScenarioMatrix />
        {/* No committed run id is wired into this static projection yet, so the
            wall renders its explicit "no committed run id yet" state. Candidate
            labels are only ever passed in from committed evaluations/lifecycle
            evidence; the operator token (plan §15) is not configured here. */}
        <FrameWall runId={null} candidates={[]} />
        <BrowserBlockerPanel />
      </main>
      <footer className="footer">
        Read-only projection of committed control-plane evidence. A disconnected dashboard cannot
        create a lease or cancel verification. No number on this screen is ever mocked.
      </footer>
    </div>
  );
}
