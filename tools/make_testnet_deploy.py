#!/usr/bin/env python3
"""Builds contract_testnet_deploy.py from contract_deploy.py by replacing the
time constants only. Usage: make_testnet_deploy.py [--check]"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "contract_deploy.py")
TARGET = os.path.join(ROOT, "contract_testnet_deploy.py")
CHANGES = (
    ("CHALLENGE_WINDOW_SECONDS = 3 * 24 * 3600", "CHALLENGE_WINDOW_SECONDS = 180"),
    ("RESOLUTION_TIMEOUT_SECONDS = 3 * 24 * 3600", "RESOLUTION_TIMEOUT_SECONDS = 300"),
)


def build():
    text = open(SOURCE).read()
    for old, new in CHANGES:
        if text.count(old) != 1:
            raise SystemExit("constant not found exactly once: " + old)
        text = text.replace(old, new)
    return text


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        sys.exit(0 if open(TARGET).read() == text else 1)
    open(TARGET, "w").write(text)
    print("wrote", TARGET)
