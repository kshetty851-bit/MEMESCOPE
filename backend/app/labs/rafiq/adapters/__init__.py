"""The `earlysignal.*` shims.

Rafiq's five strategy files were written against his own codebase. Rather than
rewrite them — which would make it impossible to tell his logic from ours the
first time a number disagreed — this package supplies the handful of types and
functions they import, so the strategies port with nothing changed but the
module path on their import lines.

Every module here is a small, separately testable unit with no I/O. The only
thing any of them knows about MEMESCOPE is the shape of a feed observation,
and that arrives as a plain mapping rather than as a model import.
"""
