import registryJson from "../../../../fixtures/scenarios.json";
import {
  UNAVAILABLE_RESULTS,
  negativeControlCell,
  scenarioCell,
  type EvaluationResults,
  type ResultCellView,
} from "../api/matrix";
import type { ScenarioRegistry } from "../generated/evaluation_ScenarioRegistry";
import type { CandidateId } from "../generated/evaluation_ScenarioResult";
import { Panel } from "./Panel";

// The registry skeleton is Track A's frozen fixture — spec, not results. Result
// cells render exclusively from committed results handed in by the API client;
// until a source is frozen every cell is labelled, never guessed (api/matrix.ts).
const registry = registryJson as ScenarioRegistry;

const CANDIDATES: CandidateId[] = ["A", "B", "C"];

function ResultCell({ view }: { view: ResultCellView }) {
  return (
    <span className={`result ${view.tone}`} title={view.trace}>
      {view.label}
    </span>
  );
}

export function ScenarioMatrix({ results = UNAVAILABLE_RESULTS }: { results?: EvaluationResults }) {
  return (
    <Panel title="Scenario matrix — S01–S08 + negative controls" className="wide">
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Surface</th>
            <th>Required invariants</th>
            {CANDIDATES.map((candidate) => (
              <th key={candidate}>{candidate}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {registry.scenarios.map((scenario) => (
            <tr key={scenario.scenario_id}>
              <td className="mono">{scenario.scenario_id}</td>
              <td>{scenario.surface}</td>
              <td className="mono">{scenario.invariants.join(" ")}</td>
              {CANDIDATES.map((candidate) => (
                <td key={candidate}>
                  <ResultCell view={scenarioCell(candidate, scenario.scenario_id, results)} />
                </td>
              ))}
            </tr>
          ))}
          {registry.negative_controls.map((control) => (
            <tr key={control.control_id} className="nc-row">
              <td className="mono">{control.control_id}</td>
              <td title={control.description}>oracle control</td>
              <td className="mono">must FAIL {control.must_fail.join(" ")}</td>
              <td colSpan={CANDIDATES.length}>
                <ResultCell view={negativeControlCell(control, results)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">
        Registry loaded from <code>fixtures/scenarios.json</code> (frozen Track A fixture). Result
        cells render committed evidence only. Until the control API serves per-scenario and
        negative-control results, every cell stays labelled <code>no result</code> /{" "}
        <code>not run</code> — never a guess. A negative control that fails its intended invariants
        is the expected outcome; one that passes is a red flag.
      </p>
    </Panel>
  );
}
