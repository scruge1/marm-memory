# Existing rig memory retrieval

Upstream: https://github.com/Lyellr88/marm-memory
Fork: https://github.com/scruge1/marm-memory
Reviewed upstream pin: f0ae8ca77a0c0c19407edf9c5bc303cffa460fdf (2.58.0).
Local integration branch: integration/cross-harness-memory-20261003.

This adapter adopts MARM's scoped retrieval and visible truncation mechanisms.
It reads the existing rig-memory.db through SQLite mode=ro and query_only.
It does not install MARM, create another store, register a tool, or start a server.

The old rig-memory.py search output clips bodies to 200 characters and omits IDs.
The additive adapter returns full bodies, IDs, source locators and body hashes.
The source hash identifies the retrieved body, not operational truth. Every record
remains raw_history with unknown state until the existing verification owner binds
it to reviewed evidence. Existing validated_memory_query.py and
memory_retrieval_policy.py retain their authority and safeguards.

## Contract

- Status: ok, empty, unavailable, unsupported_scope or invalid_query.
- Retrieval mode: lexical_fts or source_fetch. No semantic substitution.
- Project: exact SQLite equality. Platform: rig. Session: unsupported because the
  native mem table has no session attribution; never infer it from body text.
- Body: complete when within the aggregate response budget (32,000 characters
  by default). Every clipped body reports original length, identity and hash.
  Optional body_limit reports clipping. Use --id and an explicit larger
  --body-budget (maximum 1,048,576 characters) to fetch a longer source.
- Results: limit+1 probe reports truncation and suggests narrowing the query.
- Source: file URI with mem record ID, body SHA256, source timestamp. The native
  timestamp has no time zone; the adapter explicitly preserves that uncertainty.
- Current source generation, validity, review and supersession are external owner
  decisions. Search cannot establish them.

Semantic discovery remains with the existing MemPalace/SystemPalace tools.
Their source binding and safe-text filtering are handled by the existing validated
memory query owner. Do not flatten its verified and raw lanes into one score.

## Use

```sh
python3 rig_memory_adapter.py --query CallMeIE --limit 5
python3 rig_memory_adapter.py --id 42
python3 rig_memory_adapter.py --query escalation --project callmeie --limit 10
```

Exit 0 means ok or an honestly empty result. Exit 2 means retrieval was not usable.
No package installation is required. Python 3.10+ standard library only.

## Maintenance and rollback

Owner: existing foldterm memory integration. No separate update scheduler.
Check upstream through the fork/upstream Git remotes. Pin and review candidates.
Installed/running/accepted states are recorded in the private study receipt, not
in this public-source README. Run the isolated tests before replacing source.
The first deployment adds only files beside validated-memory-query. Rollback is
to stop using the additive CLI; the original CLI, stores, extensions and timers
are unchanged. Native Pi registration and later-task recall acceptance are pending.

Never put session exports, private query results, credentials or local databases
in this repository. The GitHub fork currently contains unchanged upstream only.
