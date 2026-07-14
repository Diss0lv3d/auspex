# Technical debt — logged the moment it's taken

## TD-001 (S1) — OAuth identity keyed on email, not Google `sub`
**Where:** `auspex/auth.py` `get_or_create_user` (matches users by `(workspace_id, email)`).
**Risk:** For OAuth logins the immutable Google `sub` is stored but never compared to
the incoming one. Two takeover paths *once real OAuth is live*: (a) corporate email
recycling — a reissued address logs in and matches the prior holder's row; (b) first-bind —
a dev-login-created row (google_sub NULL) gets silently bound to whichever Google
account first presents that email.
**Why deferred:** OAuth is config-stubbed (503 until a client ID exists), so this is
not reachable today. The S1 `email_verified` check closes the unverified-email takeover.
The correct fix (look up by `sub` first; refuse to link when an email-matched row has a
different non-NULL `sub`) changes the provisioning contract and deserves its own focused
change with tests.
**HARD GATE:** must be fixed *before* any `GOOGLE_CLIENT_ID` is configured in any
environment. Raised by the S1 adversarial review (2/2 verifiers confirmed).
