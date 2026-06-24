#!/usr/bin/env python3
"""outreach — moteur déterministe (IO Lemlist + état machine, zéro LLM).

Shim CLI : entrée stable `python3 scripts/routine.py <cmd>`. Toute la logique vit dans le package
`prospect_engine/` (api / state / receipts / dedup / delivery / config / cli).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prospect_engine.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
