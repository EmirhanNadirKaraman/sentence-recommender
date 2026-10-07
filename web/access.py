"""Expensive tools stay with the owner during the friends-only rollout.

The HTTP gate checks these before obtaining any Viewer or building a corpus.
Navigation uses the same policy; hiding a link alone is never authorization.
"""
OWNER_PAGES = frozenset({"/frontier", "/blocked", "/cover", "/api/cover-search", "/fix"})
OWNER_ACTIONS = frozenset({"/add-video", "/add-channel", "/replan", "/api/cover", "/fix"})
