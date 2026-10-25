# Public automation output safety

Publishing credentials are used only for the intended provider requests. Treat both
this repository and its media mirror as public. Never print or persist raw OAuth
responses, exceptions, request URLs/headers, or notification topic names.

`publish.publish()` returns fixed success/error diagnostics. `watchdog.save_json()`
removes arbitrary historical details while keeping status, attempts and timestamps
for retry and duplicate prevention. The workflow sanitizes the existing log before
committing even when publishing fails. Provider reference IDs are intentionally no
longer retained; the watchdog does not use them for deduplication.

The media mirror accepts only final JPG/MP4 assets; never place credential files in
rendered output. Audio matrix values pass as quoted environment arguments, not
interpolated shell source.

Run the offline tests (no credentials, network or installed requests required):

    python -m unittest discover -s tests -v
    python -m compileall -q .

Tests use synthetic canaries and a blocked/mock HTTP transport. They cover provider
and OAuth failures, success responses, private notifications, GET authentication,
historical state sanitation and successful-post deduplication.

This change does not revoke credentials, change access/visibility, rewrite history,
or remove existing Actions logs/artifacts. Historical public state needs a separate
owner-approved incident response if it contained sensitive data. No live publishing
or credential-validity tests were run.
