"""
DevWatch operations module — domain operations with validation, rate-limiting, and audit logging.
Provides deep interfaces for code review operations, decoupled from HTTP transport.
"""

from devwatch.operations.review_operations import ReviewOperations

__all__ = ["ReviewOperations"]
