#!/usr/bin/env node
/**
 * Thin one-shot call into the Antigravity / Google AI Pro subscription client
 * (agy-cloudcode.mjs). The prompt is read from stdin (robust for long Hebrew /
 * newlines), and the result text is written to stdout.
 *
 *   node agy_call.mjs text            < prompt
 *   node agy_call.mjs video <path>    < prompt      (path triggers video analysis)
 *
 * Each call runs in a fresh, isolated session that is deleted afterwards, so
 * nothing leaks between a script draft, a shot review and a master review.
 * Set AGY_CLOUDCODE to override the client path; AGY_CLOUDCODE_MODEL to override
 * the model. No API key — auth is the subscription OAuth inside agy-cloudcode.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';

const AGY = process.env.AGY_CLOUDCODE || path.join(os.homedir(), '.grok-claui', 'agy-cloudcode.mjs');
const mode = process.argv[2];
const mediaPath = process.argv[3] || '';

if (!['text', 'video'].includes(mode)) {
  console.error('usage: node agy_call.mjs text|video [mediaPath] < prompt');
  process.exit(2);
}
if (mode === 'video' && !(mediaPath && fs.existsSync(mediaPath))) {
  console.error('video mode needs an existing media path: ' + mediaPath);
  process.exit(2);
}
if (!fs.existsSync(AGY)) {
  console.error('agy-cloudcode client not found: ' + AGY);
  process.exit(2);
}

const prompt = fs.readFileSync(0, 'utf8');
if (!prompt.trim()) {
  console.error('empty prompt on stdin');
  process.exit(2);
}

// For video the path is appended so agy-cloudcode detects it and strips it from
// the instruction text; for text the prompt is sent as-is.
const message = mode === 'video' ? `${prompt}\n\n${mediaPath}` : prompt;

const sessionId = 'skill-' + randomUUID();
const sessionFile = path.join(os.homedir(), '.grok-claui', 'sessions', `agy-chat-${sessionId}.json`);

try {
  const { handleUserMessage } = await import(pathToFileURL(AGY).href);
  const out = await handleUserMessage(message, { sessionId });
  process.stdout.write(out || '');
} catch (e) {
  console.error(e && (e.stack || e.message) ? (e.stack || e.message) : String(e));
  process.exit(1);
} finally {
  try { if (fs.existsSync(sessionFile)) fs.unlinkSync(sessionFile); } catch {}
}
