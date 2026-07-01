"""Application service layer for the dashboard.

Service modules orchestrate persistence (ORM) and the pure simulator core.
Exports stay lazy so lightweight services can be imported without initializing
the Django model registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dashboard.services.agentic_service import AgenticService
    from dashboard.services.simulator_service import SimulatorService

__all__ = ["AgenticService", "SimulatorService"]


def __getattr__(name: str) -> Any:
    if name == "AgenticService":
        from dashboard.services.agentic_service import AgenticService

        return AgenticService
    if name == "SimulatorService":
        from dashboard.services.simulator_service import SimulatorService

        return SimulatorService
    raise AttributeError(name)
