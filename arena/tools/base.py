"""
Base class for Arena CLI coding tools.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseTool(ABC):
    """Abstract base tool for agentic execution."""

    name: str = "base_tool"
    description: str = ""

    def __init__(self, cwd: str):
        self.cwd = cwd

    @abstractmethod
    def execute(self, params: Dict[str, Any]) -> str:
        """Run tool with given parameter dict and return string output."""
        pass

