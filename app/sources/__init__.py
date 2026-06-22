"""Data-source ingestion package (Phase 0).

Each module pulls from one external source (Garmin, Strava) and normalizes the
raw payload into rows for the additive tables in app.db. Network I/O and pure
normalization are kept strictly separate so the normalizers are unit-testable
offline against fixtures, with no credentials and no live calls.
"""
