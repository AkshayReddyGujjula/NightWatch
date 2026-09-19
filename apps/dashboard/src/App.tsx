import { BrowserBlockerPanel } from "./components/BrowserBlockerPanel";
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
        <BrowserBlockerPanel />
      </main>
      <footer className="footer">
        Read-only projection of committed control-plane evidence. A disconnected dashboard cannot
        create a lease or cancel verification. No number on this screen is ever mocked.
      </footer>
    </div>
  );
}
