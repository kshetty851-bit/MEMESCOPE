"""Pipeline health.

Answers a question `/live` and `/ready` cannot: *is the platform still doing
its job?* Both existing probes report the API process. Every one of them was
green throughout the four days discovery was dead, because the API was fine —
it was the scanner that had stopped, in a different container, and nothing
looked at what it had or had not written.

Health here is derived entirely from persisted state: the most recent row each
stage wrote, and the depth of the work each stage has left. A stage is never
reported healthy because its process is up.
"""

from app.health.service import PipelineHealthService

__all__ = ["PipelineHealthService"]
