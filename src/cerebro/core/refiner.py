"""Senior Architect module: refinement and secret safety."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECRET_TOKEN = "[REDACTED_SECRET]"
_ENV_SECRET_ASSIGN_RE = re.compile(
    r'(?im)^\s*(?:export\s+)?([A-Z][A-Z0-9_]{2,})\s*=\s*([^\n#]+)'
)


@dataclass(slots=True)
class SecretRefiner:
    enabled: bool = True

    def clean_text(self, text: str) -> str:
        if not self.enabled:
            return text
        return _ENV_SECRET_ASSIGN_RE.sub(r'\1=' + _SECRET_TOKEN, text)
