"""PocketLog importer.

Reads bank CSV exports (easybank, dadat), applies a rules whitelist to enrich
and filter bookings, and imports the result into PocketLog via its CSV API.
"""

__version__ = "dev"
