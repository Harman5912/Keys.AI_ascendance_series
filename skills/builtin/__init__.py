"""Builtin skills.

One module per skill:

    SKILL = {...}                    manifest (see skills/manifest.py)
    def run(parameters, ctx): ...    the capability
    def verify(): ...                optional cheap proof it works here

A module whose name starts with ``_`` is a helper, not a skill, and is skipped by
discovery.
"""
