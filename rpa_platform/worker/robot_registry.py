from typing import Any, Dict, Optional

from rpa_platform.storage.sqlite_store import SQLiteStore
from rpa_platform.worker.browser_profile import BrowserProfileConfig


class RobotRegistry:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def register_robot(
        self,
        name: str,
        host: str,
        browser_profile_path: Optional[str] = None,
        browser_profile: Optional[BrowserProfileConfig] = None,
        capabilities: Optional[Dict[str, Any]] = None,
    ) -> str:
        merged_capabilities = dict(capabilities or {})
        if browser_profile is not None:
            browser_profile_path = browser_profile.profile_path
            merged_capabilities.update(browser_profile.to_capabilities())
        if browser_profile_path is None:
            raise ValueError("browser_profile_path is required")
        return self.store.register_robot(
            name=name,
            host=host,
            browser_profile_path=browser_profile_path,
            capabilities=merged_capabilities,
        )
