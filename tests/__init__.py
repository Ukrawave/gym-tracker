"""Offline test suite for the Phase 0 data-ingestion foundation.

All tests run WITHOUT network access and WITHOUT real credentials. Garmin/Strava
payloads are represented by synthetic fixtures in tests/fixtures/ (clearly fake
values) shaped like the real API responses, to be replaced with real captures by
the orchestrator in Task 7.
"""
