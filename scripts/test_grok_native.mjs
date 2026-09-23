import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const original = await readFile(new URL('../_verification/20260909-provider-expansion/native-before/video-generation-provider-PMWf4yep.js', import.meta.url), 'utf8');
const patched = await readFile(new URL('../_verification/20260909-provider-expansion/native-after/video-generation-provider-PMWf4yep.js', import.meta.url), 'utf8');
function load(source) {
  let authCalls = 0;
  const context = vm.createContext({ normalizeOptionalString: s => typeof s === 'string' ? s.trim() || undefined : undefined,
    toImageDataUrl: x => 'data:' + x.mimeType + ';base64,' + x.buffer.toString('base64'),
    isRecord: x => !!x && typeof x === 'object',
    resolveApiKeyForProvider: async () => { authCalls++; throw new Error('No network in tests'); } });
  const program = source.slice(source.indexOf('const DEFAULT_XAI_VIDEO_BASE_URL'), source.lastIndexOf('export {'));
  vm.runInContext(program + '\nglobalThis.subject={buildCreateBody,resolveCreateEndpoint,createXaiVideoGenerationProvider:buildXaiVideoGenerationProvider};', context);
  return { ...context.subject, authCalls: () => authCalls };
}
const api = load(patched), legacy = load(original);
const req = overrides => ({ model: 'grok-imagine-video-1.5', prompt: 'Slow camera push toward the subject.', cfg: {}, ...overrides });
const frame = role => ({ role, url: 'https://example.com/frame.png' });

test('reproduces 1080p downgrade in installed SDK and preserves it in patched request', () => {
  assert.equal(legacy.buildCreateBody(req({ resolution: '1080P' })).resolution, '720p');
  assert.equal(api.buildCreateBody(req({ resolution: '1080P' })).resolution, '1080p');
});
test('single first frame supports 1080p and explicit silent audio', () => {
  const body = api.buildCreateBody(req({ resolution: '1080P', inputImages: [frame('first_frame')], audio: false }));
  assert.equal(body.resolution, '1080p'); assert.equal(body.generate_audio, false); assert.ok(body.image.url);
});
test('first and last frame plus seven identity references use exact roles', () => {
  const body = api.buildCreateBody(req({ inputImages: [frame('first_frame'), frame('last_frame'), ...Array.from({ length: 7 }, () => frame('reference_image'))], durationSeconds: 15, audio: true }));
  assert.equal(body.reference_images.length, 7); assert.ok(body.last_frame.url); assert.equal(body.duration, 15);
  assert.equal(body.generate_audio, true); assert.equal(body.resolution, '720p');
});
test('unsupported models, modes, durations and roles reject before auth', async () => {
  for (const input of [{ resolution: '1080P', inputImages: [frame('last_frame')] },
    { resolution: '1080P', model: 'grok-imagine-video' }, { durationSeconds: 16 }, { durationSeconds: 2.5 },
    { inputImages: [frame('last_frame')], model: 'grok-imagine-video' },
    { inputImages: [frame('unknown')] }, { inputImages: [frame('first_frame'), frame('first_frame')] },
    { model: 'invented' }, { inputAudios: [{ url: 'https://example.com/voice.wav' }] }]) {
    await assert.rejects(api.createXaiVideoGenerationProvider().generateVideo(req(input)));
  }
  assert.equal(api.authCalls(), 0);
});
test('edit and extend use their dedicated native endpoints and inherit media format', () => {
  const video = { inputVideos: [{ url: 'https://example.com/source.mp4' }] };
  assert.equal(api.resolveCreateEndpoint(req(video)), '/videos/edits');
  assert.equal(api.resolveCreateEndpoint(req({ ...video, durationSeconds: 5 })), '/videos/extensions');
  assert.equal(api.buildCreateBody(req({ ...video, durationSeconds: 5 })).duration, 5);
  for (const x of [{ resolution: '720P' }, { audio: false }, { durationSeconds: 11 }, { inputImages: [frame('first_frame')] }]) {
    assert.throws(() => api.buildCreateBody(req({ ...video, ...x })));
  }
});
test('classic 720p requests retain their original body and capabilities expose true 1080p', () => {
  const input = req({ model: 'grok-imagine-video', resolution: '720P', durationSeconds: 6 });
  assert.equal(JSON.stringify(api.buildCreateBody(input)), JSON.stringify(legacy.buildCreateBody(input)));
  const p = api.createXaiVideoGenerationProvider();
  assert.ok(p.models.includes('grok-imagine-video-1.5'));
  assert.ok(p.capabilities.generate.resolutions.includes('1080P'));
  assert.equal(p.capabilities.imageToVideo.maxInputImages, 9);
});
