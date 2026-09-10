"""
Re-export shim: the response-building helper and the two scope/access-control
checks used by every gg_app_connections submodule now live in response.py and
access.py respectively (split for line-count compliance). Kept here so
`from ._shared import ...` continues to work unchanged across the package.
"""

from .access import assert_member_access, assert_scope_exists
from .response import build_response

__all__ = ["assert_member_access", "assert_scope_exists", "build_response"]
