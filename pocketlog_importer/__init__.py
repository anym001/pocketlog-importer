"""PocketLog importer.

Reads bank CSV exports (easybank, dadat), applies a rules whitelist to enrich
and filter bookings, and imports the result into PocketLog via its CSV API.
"""

# PEP 440-valid placeholder for local/dev checkouts; the Docker build overwrites
# this line with the real version (APP_VERSION, from the git tag).
__version__ = "0.0.0.dev0"
