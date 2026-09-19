import { useEffect, useLayoutEffect, useState } from "react";

import type { ControlApiConfig } from "../api/config";
import { fetchLatestFrame } from "../api/frames";
import { Empty, Panel } from "./Panel";

/** Plan §11.7: at least 1 fresh frame/second per active world. */
const FRAME_POLL_INTERVAL_MS = 1_000;

/** Plan §11.7 display rule: no fresh frame for 5 s ⇒ the tile shows FRAME_STALLED. */
const FRAME_STALL_AFTER_MS = 5_000;

export interface FrameWallCandidate {
  candidateId: string;
  sandboxId: string | null;
  jevDecision?: {
    decisionId: string;
    selectedActionLabel: string | null;
    confidence: number | null;
    modelName: string | null;
    chosenActionId: string;
  };
  action?: string | null;
  verification?: string | null;
  verdict?: "PASS" | "FAIL" | "ERROR" | "RUNNING" | null;
}

type FrameTileState =
  | { status: "loading" }
  | { status: "available"; blob: Blob; seq: number | null; receivedAtMs: number }
  | { status: "unavailable"; reason: string }
  | { status: "error"; reason: string };

export function FrameWall({
  runId,
  candidates,
  config = null,
}: {
  runId: string | null;
  candidates: FrameWallCandidate[];
  /**
   * Operator API config (base URL + bearer token). Reads are impossible without
   * it, so a missing config is rendered as a labelled unavailable state, never
   * as an empty image.
   */
  config?: ControlApiConfig | null;
}) {
  if (runId === null) {
    return (
      <Panel title="Frame wall — concurrent visual evidence" className="wide">
        <Empty>
          no committed run id yet — each tile streams real bytes from{" "}
          <code>GET /api/runs/{"{run_id}"}/frames/{"{candidate_id}"}/latest?after=…</code> only
          once a run is committed. No placeholder images and no looping animation: a tile without a
          committed frame stays labelled.
        </Empty>
        <p className="caption">
          Candidate, sandbox, Jev decision, executed action, verification and PASS/FAIL all come
          from committed control-plane/evaluation sources; missing data is labelled, never filled
          in.
        </p>
      </Panel>
    );
  }

  if (candidates.length === 0) {
    return (
      <Panel title="Frame wall — concurrent visual evidence" className="wide">
        <Empty>
          no candidate tiles committed for run <code>{runId}</code> yet — tiles appear when the
          committed evaluations / lifecycle evidence name A, B, C.
        </Empty>
      </Panel>
    );
  }

  return (
    <Panel title="Frame wall — concurrent visual evidence" className="wide">
      <div className="frame-wall">
        {candidates.map((candidate) => (
          <FrameTile key={candidate.candidateId} runId={runId} candidate={candidate} config={config} />
        ))}
      </div>
      <p className="caption">
        Bytes come from the committed latest-frame route (<code>Cache-Control: no-store</code>,
        operator bearer auth). The <code>after</code> sequence only advances from the
        server-announced frame sequence; the age is measured from dashboard receipt, and the 5 s{" "}
        <code>FRAME_STALLED</code> tag is the plan §11.7 display rule — a display/browser-evidence
        signal, never a payment or invariant failure. Missing facts render their labelled empty
        state.
      </p>
    </Panel>
  );
}

function FrameTile({
  runId,
  candidate,
  config,
}: {
  runId: string;
  candidate: FrameWallCandidate;
  config: ControlApiConfig | null;
}) {
  const frame = useLatestFrame(runId, candidate.candidateId, config);
  const objectUrl = useObjectUrl(frame.status === "available" ? frame.blob : null);
  const nowMs = useNow(frame.status === "available");

  const ageMs = frame.status === "available" ? nowMs - frame.receivedAtMs : null;
  const stalled = ageMs !== null && ageMs > FRAME_STALL_AFTER_MS;
  const frameLabel =
    frame.status === "available"
      ? `latest committed frame for candidate ${candidate.candidateId}: sequence ${
          frame.seq === null ? "not announced" : frame.seq
        }, received ${formatAge(ageMs ?? 0)}${stalled ? ", FRAME_STALLED" : ""}`
      : undefined;

  return (
    <article
      className="frame-tile"
      role="group"
      aria-label={`candidate ${candidate.candidateId} evidence tile`}
    >
      <header className="tile-head">
        <span className="tile-candidate">CANDIDATE {candidate.candidateId}</span>
        <VerdictBadge verdict={candidate.verdict ?? null} />
      </header>

      <div
        className={`frame-stage${stalled ? " stalled" : ""}`}
        role={frame.status === "available" ? "img" : undefined}
        aria-label={frameLabel ?? `no committed frame for candidate ${candidate.candidateId}`}
      >
        {objectUrl !== null && frame.status === "available" ? (
          <>
            <img src={objectUrl} alt="" />
            <span className="frame-overlay" aria-hidden="true">
              <span>seq {frame.seq === null ? "not announced" : frame.seq}</span>
              <span>{stalled ? `FRAME_STALLED · ${formatAge(ageMs ?? 0)}` : formatAge(ageMs ?? 0)}</span>
            </span>
          </>
        ) : (
          <FrameStageEmpty state={frame} />
        )}
      </div>

      <dl className="tile-facts">
        <div>
          <dt>Sandbox</dt>
          <dd className="mono">
            {candidate.sandboxId ? (
              candidate.sandboxId
            ) : (
              <span className="muted">sandbox id not committed yet</span>
            )}
          </dd>
        </div>
        <div>
          <dt>Jev decision</dt>
          <dd>
            <DecisionText decision={candidate.jevDecision} />
          </dd>
        </div>
        <div>
          <dt>Executed action</dt>
          <dd>
            {candidate.action ? candidate.action : <span className="muted">no action recorded yet</span>}
          </dd>
        </div>
        <div>
          <dt>Verification</dt>
          <dd>{candidate.verification ? candidate.verification : <span className="muted">unverified</span>}</dd>
        </div>
      </dl>
    </article>
  );
}

function FrameStageEmpty({ state }: { state: FrameTileState }) {
  if (state.status === "loading") {
    return (
      <p className="frame-none" role="status">
        <strong>awaiting committed frame</strong>
        <span className="frame-reason">reading the latest-frame route…</span>
      </p>
    );
  }
  if (state.status === "available") {
    // The bytes exist but the object URL has not been handed to the <img> yet.
    return (
      <p className="frame-none" role="status">
        <strong>committed frame received</strong>
        <span className="frame-reason">preparing the bytes for display…</span>
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <p className="frame-none error" role="status">
        <strong>frame read failed</strong>
        <span className="frame-reason">{state.reason}</span>
      </p>
    );
  }
  return (
    <p className="frame-none" role="status">
      <strong>no committed frame source yet</strong>
      <span className="frame-reason">{state.reason}</span>
    </p>
  );
}

function DecisionText({ decision }: { decision: FrameWallCandidate["jevDecision"] }) {
  if (decision === undefined) {
    return <span className="muted">no decision recorded yet</span>;
  }
  return (
    <span>
      <span>{decision.selectedActionLabel ?? "action label not committed"}</span>{" "}
      <code>{decision.chosenActionId}</code>
      <span className="muted">
        {" "}
        · confidence {decision.confidence ?? "not committed"} · model{" "}
        {decision.modelName ?? "not committed"} · decision{" "}
        <span className="mono">{decision.decisionId}</span>
      </span>
    </span>
  );
}

function VerdictBadge({ verdict }: { verdict: FrameWallCandidate["verdict"] | null }) {
  switch (verdict) {
    case "PASS":
      return <span className="badge pass">PASS</span>;
    case "FAIL":
      return <span className="badge fail">FAIL</span>;
    case "ERROR":
      return <span className="badge warn">ERROR</span>;
    case "RUNNING":
      return <span className="badge warn">RUNNING</span>;
    default:
      return <span className="badge idle">no result</span>;
  }
}

/**
 * Polls the latest-frame route for one tile at 1 Hz. The `after` sequence is
 * only ever the server-announced sequence from a previous 200; `unchanged`
 * responses keep the current bytes, and a 404/501 flips the tile to its
 * labelled "no committed frame source yet" state.
 */
function useLatestFrame(
  runId: string,
  candidateId: string,
  config: ControlApiConfig | null,
): FrameTileState {
  const [state, setState] = useState<FrameTileState>({ status: "loading" });
  const baseUrl = config?.baseUrl ?? null;
  const token = config?.token ?? null;

  useEffect(() => {
    setState({ status: "loading" });
    if (baseUrl === null || token === null || token === "") {
      setState({
        status: "unavailable",
        reason: "the operator token for frame reads is not configured on this dashboard yet",
      });
      return;
    }

    const readConfig: ControlApiConfig = { baseUrl, token };
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let afterSeq: number | null = null;

    const poll = async () => {
      try {
        const result = await fetchLatestFrame(readConfig, runId, candidateId, afterSeq);
        if (cancelled) return;
        if (result.available) {
          afterSeq = result.seq;
          setState({
            status: "available",
            blob: result.blob,
            seq: result.seq,
            receivedAtMs: Date.now(),
          });
        } else if (result.unchanged) {
          setState((previous) =>
            previous.status === "available"
              ? previous
              : { status: "unavailable", reason: result.reason },
          );
        } else {
          setState({ status: "unavailable", reason: result.reason });
        }
      } catch (error) {
        if (!cancelled) {
          setState({
            status: "error",
            reason: error instanceof Error ? error.message : String(error),
          });
        }
      }
      if (!cancelled) {
        timer = setTimeout(() => void poll(), FRAME_POLL_INTERVAL_MS);
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [runId, candidateId, baseUrl, token]);

  return state;
}

/** Object URL for the current bytes; revoked on replace and on unmount. */
function useObjectUrl(blob: Blob | null): string | null {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  // Layout effect: a received frame must never paint as the empty state for a
  // frame that already exists.
  useLayoutEffect(() => {
    if (blob === null) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);

  return objectUrl;
}

/** 1 Hz clock so the measured frame age keeps moving while a tile is live. */
function useNow(enabled: boolean): number {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = () => {
      if (cancelled) return;
      setNowMs(Date.now());
      timer = setTimeout(tick, FRAME_POLL_INTERVAL_MS);
    };
    timer = setTimeout(tick, FRAME_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [enabled]);

  return nowMs;
}

function formatAge(ageMs: number): string {
  const seconds = Math.max(0, Math.round(ageMs / 1000));
  return `${seconds}s ago`;
}
