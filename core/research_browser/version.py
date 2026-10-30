"""Research Browser version metadata.

Stable under the contract described in the version-stability section of the
integration docs. Anything else is a private implementation detail.
"""

__all__ = ["BrowserVersion"]


class BrowserVersion:
    """Public, stable version data for the research browser module."""

    def __init__(self) -> None:
        self.module_name = "core.research_browser"
        self.version = BrowserVersion._current()
        self.revision = ""
        self.installed_by = ""
        self.install_root = ""
        self.install_state = "built"
        self.platform = ""
        self.py_version = ""
        self.supported_platforms = []
        self.wheel_is_platform_specific = True
        self._frozen = False
        self.module_file = ""

    @staticmethod
    def _current() -> str:
        return BrowserVersion._version()

    @staticmethod
    def _version() -> str:
        import core.research_browser as m
        return getattr(m, "__version__", "0.20.0")

    def as_dict(self, *, public: bool = False) -> dict:
        if public:
            return {
                "module": self.module_name,
                "version": self.version,
                "module_file": str(self.module_file or ""),
                "install_root": self.install_root,
                "install_state": self.install_state,
                "platform": self.platform,
                "py_version": self.py_version,
                "supported_platforms": list(self.supported_platforms),
                "wheel_is_platform_specific": bool(self.wheel_is_platform_specific),
            }
        return {
            "module": self.module_name,
            "version": self.version,
            "revision": self.revision,
            "installed_by": self.installed_by,
            "install_root": self.install_root,
            "install_state": self.install_state,
            "module_file": str(self.module_file or ""),
            "platform": self.platform,
            "py_version": self.py_version,
            "supported_platforms": list(self.supported_platforms),
            "wheel_is_platform_specific": bool(self.wheel_is_platform_specific),
            "_frozen": bool(self._frozen),
        }

    def __repr__(self) -> str:
        return f"BrowserVersion({self.module_name!r}, version={self.version!r})"


# A downstream consumer should be able to do this:
#   from core.research_browser import BrowserVersion
#   v = BrowserVersion()
#   print(v.version)   # "0.20.0" or newer
