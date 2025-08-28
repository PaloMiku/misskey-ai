from __future__ import annotations

__all__ = [
	"GalInfoError",
	"GameNotFoundError",
	"APIParamError",
	"APIServerError",
]


class GalInfoError(Exception):
	"""Base exception for galinfo plugin."""


class GameNotFoundError(GalInfoError):
	"""Raised when game search yields no result."""


class APIParamError(GalInfoError):
	"""Raised when API returns parameter error (e.g. code 614)."""


class APIServerError(GalInfoError):
	"""Raised when API returns non-zero unexpected code."""

