"""Immutable orchestration evidence layered on the existing control store."""

from __future__ import annotations

from apps.contracts.evaluation import CandidateEvaluation
from apps.contracts.incident import GeminiDiagnosis, IncidentCapsule
from services.control_store import ControlStore


class OrchestrationControlStore(ControlStore):
    """Control store plus frozen capsule, diagnosis and candidate outcomes."""

    def __init__(self, db_path: str = ":memory:") -> None:
        super().__init__(db_path)
        with self.lock:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incident_capsules (
                    incident_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gemini_diagnoses (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_evaluations (
                    run_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, candidate_id)
                );
                """
            )
            self.connection.commit()

    def save_capsule(self, capsule: IncidentCapsule) -> None:
        with self.lock:
            snapshot = self.connection.execute(
                "SELECT run_id FROM incidents WHERE incident_id = ?", (capsule.incident_id,)
            ).fetchone()
            if snapshot is None or snapshot["run_id"] != capsule.run_id:
                raise KeyError(capsule.incident_id)
            payload = capsule.model_dump_json()
            existing = self.connection.execute(
                "SELECT payload_json FROM incident_capsules WHERE incident_id = ?",
                (capsule.incident_id,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload:
                    raise ValueError("frozen incident capsule is immutable")
                return
            self.connection.execute(
                """
                INSERT INTO incident_capsules (incident_id, run_id, payload_json)
                VALUES (?, ?, ?)
                """,
                (capsule.incident_id, capsule.run_id, payload),
            )
            self.connection.commit()

    def get_capsule(self, incident_id: str) -> IncidentCapsule:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload_json FROM incident_capsules WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        if row is None:
            raise KeyError(incident_id)
        return IncidentCapsule.model_validate_json(row["payload_json"], strict=True)

    def save_diagnosis(self, run_id: str, diagnosis: GeminiDiagnosis) -> None:
        with self.lock:
            payload = diagnosis.model_dump_json()
            existing = self.connection.execute(
                "SELECT payload_json FROM gemini_diagnoses WHERE run_id = ?", (run_id,)
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload:
                    raise ValueError("committed Gemini diagnosis is immutable")
                return
            self.connection.execute(
                "INSERT INTO gemini_diagnoses (run_id, payload_json) VALUES (?, ?)",
                (run_id, payload),
            )
            self.connection.commit()

    def get_diagnosis(self, run_id: str) -> GeminiDiagnosis:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload_json FROM gemini_diagnoses WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return GeminiDiagnosis.model_validate_json(row["payload_json"], strict=True)

    def save_candidate_evaluations(
        self, run_id: str, evaluations: list[CandidateEvaluation]
    ) -> None:
        candidate_ids = [evaluation.candidate_id for evaluation in evaluations]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate evaluations must be unique")
        with self.lock, self.connection:
            for evaluation in evaluations:
                payload = evaluation.model_dump_json()
                existing = self.connection.execute(
                    """
                    SELECT payload_json FROM candidate_evaluations
                    WHERE run_id = ? AND candidate_id = ?
                    """,
                    (run_id, evaluation.candidate_id),
                ).fetchone()
                if existing is not None:
                    if existing["payload_json"] != payload:
                        raise ValueError("committed candidate evaluation is immutable")
                    continue
                self.connection.execute(
                    """
                    INSERT INTO candidate_evaluations (run_id, candidate_id, payload_json)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, evaluation.candidate_id, payload),
                )

    def get_candidate_evaluations(self, run_id: str) -> list[CandidateEvaluation]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT payload_json FROM candidate_evaluations
                WHERE run_id = ? ORDER BY candidate_id
                """,
                (run_id,),
            ).fetchall()
        return [
            CandidateEvaluation.model_validate_json(row["payload_json"], strict=True)
            for row in rows
        ]
