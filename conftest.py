"""
Pytest-Konfiguration fuers ganze Projekt.

- ANTHROPIC_API_KEY wird gesetzt, BEVOR irgendein Testmodul importiert wird,
  damit analyzer.py beim Import nicht gegen einen fehlenden Key laeuft
  (analyzer.get_client() ist lazy, siehe analyzer.py -- das hier ist die
  Absicherung fuer den Fall, dass Tests trotzdem versehentlich den echten
  Client bauen).
"""
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-fuer-pytest")

