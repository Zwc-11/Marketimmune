"""Application service layer for the dashboard.

Service modules orchestrate persistence (ORM) and the pure simulator
core (`marketimmune.simulator`). Views call these — never the ORM
directly — so that the HTTP surface stays declarative and unit-testable.
"""

from dashboard.services.agentic_service import AgenticService
from dashboard.services.simulator_service import SimulatorService

__all__ = ["AgenticService", "SimulatorService"]
