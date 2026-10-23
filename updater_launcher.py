# -*- coding: utf-8 -*-
"""Tiny independently packaged updater (never launches a shell)."""
import multiprocessing
multiprocessing.freeze_support()
from updater_worker import main
if __name__ == "__main__":
    raise SystemExit(main())
