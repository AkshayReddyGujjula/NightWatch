import registryJson from "../../../../fixtures/scenarios.json";
import type { ScenarioRegistry } from "../generated/evaluation_ScenarioRegistry";
import { Panel } from "./Panel";

// The registry skeleton is Track A's frozen fixture — spec, not results. Every
// result cell stays empty until the control API returns committed evidence.
const registry = registryJson as ScenarioRegistry;

const CANDIDATES = ["A", "B", "C"] as const;

export function ScenarioMatrix() {
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
                <td key={candidate} className="cell-empty">
                  no result
                </td>
              ))}
            </tr>
          ))}
          {registry.negative_controls.map((control) => (
            <tr key={control.control_id} className="nc-row">
              <td className="mono">{control.control_id}</td>
              <td>oracle control</td>
              <td className="mono">must FAIL {control.must_fail.join(" ")}</td>
              {CANDIDATES.map((candidate) => (
                <td key={candidate} className="cell-empty">
                  not run
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">
        Registry loaded from <code>fixtures/scenarios.json</code> (frozen Track A fixture); results
        arrive from the control API. The negative controls must fail for their intended invariants —
        that is what makes every PASS above them trustworthy.
      </p>
    </Panel>
  );
}
