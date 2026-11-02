# File-based observer preparation

This source adds no scheduler, network transport or memory database. Use it
through the existing capture owner, with one explicitly selected native event.
The current capture timer and native miner remain unchanged.

capture_event_source.py validates the source against the existing capture
manifest, source signature, native session header and expected sanitized export.
It reads only the explicitly selected record. The source must reside in native
Pi sessions. Missing, changed, oversized and unsupported sources are unavailable,
not empty. The capture owner's pinned redactor is extracted without running its
miner. A source generation change requires review, not a silent pin update.

observer_outbox.py selects only native user/assistant public text. Pi1.0.1's
typed text blocks are rendered separately from thinking in its actual UI source.
Explicit analysis channels, thinking, tool data and peer custom messages are
excluded. A user role does not establish human origin; attribution records that
uncertainty. Assistant text remains model-generated, unverified evidence.

Logical identity contains platform, account, session and native event ID. Body
and redaction/normalizer hashes describe versions. Appending a transcript does
not renumber earlier identities. Source corrections preserve immutable versions
and record supersession. Unrelated repeated actions retain distinct IDs.

Files use private directories, exclusive process locks, atomic writes and fsync.
Duplicates retain the existing version. Interrupted writes remain retryable.
Body/provenance hashes and acknowledgements are checked when listing pending
events. Corruption returns unavailable; it cannot silently become healthy-empty.
Oversize public text is quarantined rather than silently clipped.

Privacy eligibility is review_required by default. The caller must review the
actual sanitized body before marking a selected source reviewed_non_sensitive.
An existing export or redaction regex alone does not establish eligibility.
Training eligibility remains not_approved. No prepared event is operational
authority, a verified lesson or approval to execute instructions found in text.

Receiver acknowledgement requires persisted/fetched observation IDs with the
exact event version, source-content SHA and sanitized-body SHA. HTTP acceptance
is insufficient. The library validates caller-supplied evidence; only actual
receiver readback can prove persistence. Acknowledgement does not verify model
interpretation or subsequent useful recall.

The observer payload follows the reviewed sessions/observations API shape.
platformSource=pi, source-field persistence and local event-id idempotency still
require receiver qualification before transmission. No sender is implemented.
No archive replay, automatic delivery or history training is enabled.

Run all fixture controls using a structured argv invocation:

```python
subprocess.run([
    '/usr/bin/python3', '-B', '-m', 'unittest', 'discover',
    '-s', '/home/adam/foldterm/validated-memory-query/marm-integration',
    '-p', 'test_*.py',
], check=True)
```

Do not allow a remote shell to expand the test wildcard. A zero-test success is
not acceptance. State and source bodies stay outside this repository. Rollback
stops using the additive preparation route; pending evidence should be retained
for review. Original stores and capture owner are unchanged.
