import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { stripTypeScriptTypes } from 'node:module';
import { fileURLToPath } from 'node:url';
import { join, basename } from 'node:path';

const root = fileURLToPath(new URL('../_verification/20260909-provider-expansion/', import.meta.url));
const before = join(root, 'native-before'), after = join(root, 'native-after');
const manifest = JSON.parse(await readFile(join(before, 'manifest.json'), 'utf8'));
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const entry = name => manifest.find(row => basename(row.remote) === name);
async function original(name) {
  const data = await readFile(join(before, name));
  if (sha(data) !== entry(name)?.sha256) throw new Error(`Baseline hash changed: ${name}`);
  return data.toString('utf8');
}
function replaceOnce(source, old, value) {
  if (source.split(old).length !== 2) throw new Error(`Patch anchor changed: ${old.slice(0, 70)}`);
  return source.replace(old, value);
}
let source = await original('video-generation-provider.ts');
const request = await readFile(new URL('./grok-request.ts', import.meta.url), 'utf8');
source = source.slice(0, source.indexOf('function resolveDurationSeconds(')) + request +
  source.slice(source.indexOf('function resolveCreateEndpoint('));
source = replaceOnce(source, 'function isReferenceImage(input: VideoGenerationSourceInput): boolean {\n  return normalizeOptionalString(input.role)?.toLowerCase() === "reference_image";\n}\n\n', '');
source = replaceOnce(source, 'models: [DEFAULT_XAI_VIDEO_MODEL]', 'models: XAI_VIDEO_MODELS');
source = source.replaceAll('resolutions: ["480P", "720P"]', 'resolutions: ["480P", "720P", "1080P"]');
source = replaceOnce(source, 'maxInputImages: 7,', 'maxInputImages: 9,');
// Video edits/extensions preserve their source format. Generation modes expose the audio toggle.
source = source.replaceAll('supportsResolution: true,', 'supportsResolution: true,\n        supportsAudio: true,');
source = replaceOnce(source, 'videoToVideo: {\n        enabled: true,\n        maxVideos: 1,\n        maxInputVideos: 1,\n        maxDurationSeconds: 15,\n        supportsAspectRatio: true,\n        supportsResolution: true,\n        supportsAudio: true,',
  'videoToVideo: {\n        enabled: true,\n        maxVideos: 1,\n        maxInputVideos: 1,\n        maxDurationSeconds: 10,\n        supportsAspectRatio: false,\n        supportsResolution: false,\n        supportsAudio: false,');
source = replaceOnce(source, 'async generateVideo(req) {\n      const auth', 'async generateVideo(req) {\n      const createBody = buildCreateBody(req); // Validate before OAuth refresh or any provider request.\n      const auth');
source = replaceOnce(source, 'body: buildCreateBody(req),', 'body: createBody,');
source = replaceOnce(source, 'const DEFAULT_GENERATED_VIDEO_MAX_BYTES = 16 * 1024 * 1024;',
  'const DEFAULT_GENERATED_VIDEO_MAX_BYTES = 64 * 1024 * 1024; // Bounded headroom for native 1080p.');
source = replaceOnce(source, 'requestId,\n            status:', 'requestId,\n            contract: CAMPAIGN_XAI_CONTRACT,\n            requestedResolution: createBody.resolution,\n            status:');
source = replaceOnce(source, '      try {\n        await assertOkOrThrowHttpError(response, "xAI video generation failed");',
  '      let acceptedRequestId: string | undefined;\n      try {\n        await assertOkOrThrowHttpError(response, "xAI video generation failed");');
source = replaceOnce(source, '        const completed = await pollXaiVideo({',
  '        acceptedRequestId = requestId;\n        const completed = await pollXaiVideo({');
source = replaceOnce(source, '      } finally {\n        await release();\n      }\n    },',
  '      } catch (error) {\n        if (acceptedRequestId) throw new Error(`xAI request ${acceptedRequestId} was accepted, but collection did not complete. Reconcile that request; do not regenerate.`, { cause: error });\n        throw error;\n      } finally {\n        await release();\n      }\n    },');
const originalBundle = await original('video-generation-provider-PMWf4yep.js');
const imports = originalBundle.slice(0, originalBundle.indexOf('//#region'));
const exports = originalBundle.slice(originalBundle.lastIndexOf('export {'));
const body = stripTypeScriptTypes(source.slice(source.indexOf('const DEFAULT_XAI_VIDEO_BASE_URL')), { mode: 'strip' })
  .replace('export function buildXaiVideoGenerationProvider', 'function buildXaiVideoGenerationProvider');
await mkdir(after, { recursive: true });
const files = { 'video-generation-provider.ts': source, 'video-generation-provider-PMWf4yep.js': imports + body + '\n' + exports };
const rows = [];
for (const [name, content] of Object.entries(files)) {
  await writeFile(join(after, name), content);
  rows.push({ remote: entry(name).remote, file: name, before_sha256: entry(name).sha256, after_sha256: sha(content) });
}
await writeFile(join(after, 'manifest.json'), JSON.stringify({ contract: '20260909-v1.5-1080p', files: rows }, null, 2));
console.log(JSON.stringify({ prepared: true, directory: after, files: rows.length, deployed: false }));
