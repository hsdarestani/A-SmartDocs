"""Kompatibilitätsalias für den aktiven Analyseablauf in :mod:`app.asgi`."""

import sys

from . import asgi as _aktiver_ablauf

sys.modules[__name__] = _aktiver_ablauf
