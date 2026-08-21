"""In-process store for long-running scout jobs.

A full scout takes four to five minutes, but the app sits behind a proxy that
abandons any request unanswered after ~100 seconds. So the work cannot happen
inside the request that asks for it: the client starts a job, then polls.

Jobs live in memory rather than in Redis. The service runs a single worker
process, so a dict is sufficient, and a restart loses in-flight jobs either
way — the thread doing the work dies with it. Finished briefs are durable
because they go to the brief cache, not to this store.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field, asdict

# Jobs are small, but a long-lived process would still accumulate them.
JOB_TTL_SECONDS = 3600

TOTAL_STAGES = 5


@dataclass
class Job:
    id: str
    query: str
    status: str = "running"  # running | done | error
    stage: int = 0
    total_stages: int = TOTAL_STAGES
    message: str = "Starting research..."
    share_key: str | None = None
    # Lets the frontend explain quota exhaustion differently from a crash,
    # without parsing prose out of the error message.
    error_kind: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, query: str, share_key: str | None = None) -> Job:
        job = Job(id=uuid.uuid4().hex, query=query, share_key=share_key)
        with self._lock:
            self._purge_expired()
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            job.updated_at = time.time()

    def _purge_expired(self) -> None:
        """Caller must hold the lock."""
        cutoff = time.time() - JOB_TTL_SECONDS
        for job_id in [j.id for j in self._jobs.values() if j.updated_at < cutoff]:
            del self._jobs[job_id]
