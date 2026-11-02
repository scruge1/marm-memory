import { createHash } from 'node:crypto';

const sha = value => createHash('sha256').update(value).digest('hex');

export function receiverPayload(event, cwd, resolvedProject) {
  const p = event.provenance;
  if (event.schema !== 'rig-observer-event/v1' || p.privacy_eligibility !== 'reviewed_non_sensitive') {
    throw new Error('source privacy review required');
  }
  if (!cwd || resolvedProject !== p.project_scope) throw new Error('receiver cwd/project mapping not qualified');
  const payload = structuredClone(event.observer_event);
  if (Buffer.byteLength(JSON.stringify(payload.tool_input)) > 64000
    || Buffer.byteLength(JSON.stringify(payload.tool_response)) > 64000) throw new Error('native source payload would truncate');
  payload.cwd = cwd;
  return payload;
}

export function fetchedReceipt(event, toolRows, observationRows) {
  const p = event.provenance;
  const e = event.observer_event;
  if (!Array.isArray(toolRows) || !Array.isArray(observationRows)) throw new Error('native fetch unavailable');
  if (toolRows.length === 0) return { status: 'not_received', ack: null };
  if (toolRows.length !== 1) throw new Error('ambiguous native source');
  const row = toolRows[0];
  if (row.tool_use_id !== e.tool_use_id || row.content_session_id !== p.native_session_id
    || row.platform_source !== 'pi' || row.project !== p.project_scope || row.tool_name !== 'public_dialogue') {
    throw new Error('native source scope mismatch');
  }
  let input, output;
  try { input = JSON.parse(row.tool_input); output = JSON.parse(row.tool_response); }
  catch { throw new Error('native source payload clipped or invalid'); }
  if (JSON.stringify(input) !== JSON.stringify(e.tool_input)
    || output.text !== e.tool_response.text || output.truncated !== false
    || sha(output.text) !== p.sanitized_body_sha256) throw new Error('native source/body metadata mismatch');
  if (!row.observation_id) return { status: 'awaiting_or_uncertain_processing', ack: null,
    retry_policy: 'Do not infer safe replay from queue emptiness; native late-link failures need owner review.' };
  const matches = observationRows.filter(obs => String(obs.id) === String(row.observation_id));
  if (matches.length !== 1) throw new Error('linked observation fetch missing or ambiguous');
  const observation = matches[0];
  if (observation.project !== p.project_scope
    || !row.memory_session_id || observation.memory_session_id !== row.memory_session_id) {
    throw new Error('linked observation scope mismatch');
  }
  return { status: 'stored_and_fetch_confirmed', ack: {
    observation_ids: [String(observation.id)], tool_use_id: row.tool_use_id,
    source_content_sha256: input.source_content_sha256,
    sanitized_body_sha256: sha(output.text),
    native_tool_use_row_id: row.id,
    link_semantics: 'first observation in generated batch; not one-to-one semantic attribution',
  } };
}

export function nativeReceipt(store, event) {
  const p = event.provenance;
  // Native observations expose o.* only, so platform is established by the
  // supported platform-filtered SDK-session join, not a nonexistent field.
  const tools = store.getToolUsesByIds([event.observer_event.tool_use_id], {
    project: p.project_scope, contentSessionId: p.native_session_id, platformSource: 'pi',
  });
  const ids = tools.map(row => row.observation_id).filter(Number.isInteger);
  const observations = store.getObservationsByIds(ids, { project: p.project_scope, platformSource: 'pi' });
  return fetchedReceipt(event, tools, observations);
}
