import { Panel } from "./Panel";

export function BrowserBlockerPanel() {
  return (
    <Panel title="Browser stack — REDUCED" className="blocker">
      <p>
        <strong>
          Browser scenarios are declared <code>ERROR_BROWSER_STACK</code>.
        </strong>{" "}
        Two driver-level blockers were measured on CUA Driver 0.28.2; the world's browser never
        reaches a typed snapshot, so no browser journey is claimed anywhere in this demo.
      </p>
      <ol>
        <li>
          Typed navigate and snapshot refuse a fresh <code>about:blank</code> page under an
          origin-scoped bounded manifest (<code>protected_resource_scope_invalid</code> /{" "}
          <code>authorization_host_failed</code>); the check runs on the current, opaque origin.
        </li>
        <li>
          Existing-profile attach fails its endpoint proof against a live, PID-owned loopback
          endpoint (<code>browser_requires_setup</code> after restart).
        </li>
      </ol>
      <p className="caption">
        Full evidence chain: <code>infra/BROWSER_STACK_NOTES.md</code>. No substitute browser
        controller is used (ADR-007). This panel is status, never a screenshot posing as a live
        session.
      </p>
    </Panel>
  );
}
