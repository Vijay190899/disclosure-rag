"""Throwaway probes that answer a single yes or no question before design work commits to it.

Spikes are not part of the shipped package. They are excluded from mypy and from the
annotation lint rules, and their dependencies live in the ``spike`` extra so they never
reach the runtime image.
"""
