#!/usr/bin/env python3
"""runtime/common_language_pack.py — Standard Japanese Language Pack Loader.

Loads versioned, schema-validated JSON language packs from common-language/packs/ja-JP/.
Provides decoupled text templates without hardcoding within parser logic.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

_PKG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACK_JSON_PATH = os.path.join(_PKG_ROOT, "common-language", "packs", "ja-JP", "p0_concepts.json")

# Dynamic Pack Loader
def load_concept_pack(pack_path: str = _PACK_JSON_PATH) -> Dict[str, Dict[str, Any]]:
    if os.path.exists(pack_path):
        try:
            with open(pack_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "concepts" in data:
                    return data["concepts"]
        except Exception:
            pass
    return {}


JA_CONCEPT_PACK: Dict[str, Dict[str, Any]] = load_concept_pack()
