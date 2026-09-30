"""Tab registry: the UI shows these in order. Add a Tab subclass here to add a screen."""
from .base import Tab
from .cover import CoverTab
from .create import CreateTab
from .editor import EditorTab
from .instrumental import InstrumentalTab
from .library import LibraryTab
from .restyle import RestyleTab

TABS: list[type[Tab]] = [CreateTab, RestyleTab, EditorTab, InstrumentalTab, CoverTab, LibraryTab]

__all__ = ["TABS", "Tab"]
