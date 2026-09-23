// Reuse the user's existing Suno client; never import/copy credentials into this skill.
import {readFileSync, writeFileSync, existsSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const [command, modulePath, requestPath] = process.argv.slice(2);
const emit = (value) => process.stdout.write(JSON.stringify(value) + '\n');
try {
  if (!existsSync(modulePath)) throw new Error('client_missing');
  const {SunoClient} = await import(pathToFileURL(modulePath).href);
  const client = new SunoClient();
  if (!client.cookie) { emit({ok:false, status:'blocked', reason:'suno_login_missing', submitted:false}); process.exit(0); }
  if (command === 'probe') {
    const response = await client.getCredits();
    emit({ok:response.status === 200, status:response.status === 200 ? 'authenticated' : 'blocked',
      http_status:response.status, credits:response.status === 200 ? response.body?.total_credits_left ?? response.body?.credits_left ?? null : null,
      generation_tested:false});
  } else {
    const request = JSON.parse(readFileSync(requestPath, 'utf8').replace(/^\uFEFF/, ''));
    if (command === 'submit') {
      // Fail closed: an unknown/failed captcha check is never treated as permission to submit.
      const check = await client.api('/api/c/check', {method:'POST', body:{ctype:'generation'}});
      if (check.status !== 200 || check.body?.required !== false) {
        emit({ok:false,status:'blocked',reason:check.body?.required === true ? 'captcha_required' : 'captcha_check_unavailable',submitted:false});
      } else {
        const response = await client.api('/api/generate/v2/', {method:'POST',body:{
          prompt:request.lyrics || '', tags:request.style, title:request.title || '', mv:request.model,
          make_instrumental:request.instrumental, generation_type:'TEXT',
          continue_clip_id:request.extend_clip_id || null,
          continue_at:request.extend_clip_id ? request.extend_at_seconds : null,
          task:request.extend_clip_id ? 'extend' : null, token:null}});
        const clips = response.body?.clips || (Array.isArray(response.body) ? response.body : []);
        const ids = clips.map(c => c.id).filter(id => typeof id === 'string');
        emit({ok:response.status === 200 && ids.length > 0, status:ids.length ? 'accepted' : 'unknown',
          http_status:response.status, submitted:true, ids});
      }
    } else if (command === 'status') {
      if (!Array.isArray(request.ids) || !request.ids.length || request.ids.some(id => !/^[a-zA-Z0-9-]+$/.test(id))) throw new Error('invalid_clip_ids');
      const response = await client.api('/api/feed/v2?ids=' + request.ids.join(','));
      const clips = response.body?.clips || (Array.isArray(response.body) ? response.body : []);
      emit({ok:response.status === 200,http_status:response.status,clips:clips.filter(c => request.ids.includes(c.id)).map(c => ({
        id:c.id,status:c.status,audio_url:c.audio_url || null,duration:c.metadata?.duration ?? null}))});
    } else throw new Error('unsupported_command');
  }
} catch (error) {
  // Do not echo provider response bodies, cookie, JWT or arbitrary exception data.
  emit({ok:false,status:'unknown',reason:'suno_transport_or_client_error',error_type:error?.name || 'Error'});
  process.exitCode = 1;
}
