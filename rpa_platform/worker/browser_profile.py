from dataclasses import dataclass


class BrowserProfileConfigError(ValueError):
    """Raised when a worker browser profile config is incomplete."""


@dataclass(frozen=True)
class BrowserProfileConfig:
    browser_type: str
    profile_path: str
    jdy_entry_url: str
    wecom_entry_url: str

    def __post_init__(self) -> None:
        browser_type = self.browser_type.strip().lower()
        if browser_type not in ("chromium", "chrome", "edge"):
            raise BrowserProfileConfigError("browser_type must be chromium, chrome, or edge")
        object.__setattr__(self, "browser_type", browser_type)
        self._require_text("profile_path", self.profile_path)
        self._require_url("jdy_entry_url", self.jdy_entry_url)
        self._require_url("wecom_entry_url", self.wecom_entry_url)

    @staticmethod
    def _require_text(field: str, value: str) -> None:
        if not value or not str(value).strip():
            raise BrowserProfileConfigError("%s is required" % field)

    @staticmethod
    def _require_url(field: str, value: str) -> None:
        BrowserProfileConfig._require_text(field, value)
        text = str(value).strip()
        if not (text.startswith("https://") or text.startswith("http://")):
            raise BrowserProfileConfigError("%s must be an http(s) URL" % field)

    def to_capabilities(self) -> dict:
        return {
            "browser_type": self.browser_type,
            "entry_urls": {
                "jdy": self.jdy_entry_url,
                "wecom": self.wecom_entry_url,
            },
        }
