#!/usr/bin/env python3
"""Legacy test-runner entry point. Delegate to the auto-discovering check engine.

All original CLI options that the current checker supports, including --clone,
--src and -v, are forwarded unchanged.
"""
import os
import runpy

if __name__ == "__main__":
    runpy.run_path(os.path.join(os.path.dirname(__file__), "check.py"), run_name="__main__")
