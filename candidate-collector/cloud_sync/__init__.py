"""Cloud sync package for TTC candidate-collector.

Synchronizes local SQLite data to an upstream PostgreSQL/RDS instance so that
multiple AI tools (Claude / OpenCode / Codex) can share the same long-term
truth source.
"""
