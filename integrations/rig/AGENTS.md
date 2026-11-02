# Rig memory adapter

This directory contains an additive adapter for existing memory owners. It does
not run the MARM server or create a new memory database. Retain full source bodies
and stable record IDs. Historical memory is not execution authority.

Run `python -m unittest discover -s integrations/rig -p 'test_*.py'`.
No changes to upstream symbols, Pi extensions, or source-pin guards belong here.
