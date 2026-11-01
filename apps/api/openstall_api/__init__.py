"""OpenStall API: webhooks, orders, PayPal, passports, and the MCP storefront at /mcp."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("openstall")
except PackageNotFoundError:  # run from a source tree that was never pip-installed
    __version__ = "0.0.0+unknown"
