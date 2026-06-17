from typing import Any, Dict, Optional, Protocol


class UiaDriver(Protocol):
    def find_element(self, selector: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def click_element(self, selector: Dict[str, Any]) -> None:
        raise NotImplementedError

    def set_text(self, selector: Dict[str, Any], value: str) -> None:
        raise NotImplementedError
