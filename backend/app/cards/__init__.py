"""Custom cards: a card described as data, never as code.

``schema`` is what a definition may say, ``load`` reads and checks one,
``store`` keeps them, ``formula`` calculates and ``pipeline`` turns the answers
of a service into the finished values a card shows.
"""

# ⚠️ ``schema`` first, whichever module of the package is asked for: ``buttons`` is built from parts of ``schema`` and
# ``schema`` takes it in, so the other way round would find a half-read module.
from . import schema  # noqa: E402, F401
