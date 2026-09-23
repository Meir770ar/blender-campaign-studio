"""Preview, apply or roll back the reviewed native SDK patch. No generation calls."""
import argparse
import base64
import hashlib
import json
import sys
from campaign_common import atomic_json, now
from provider_jobs import ROOT, load_json, ssh

PACKAGE = ROOT / '_verification' / '20260909-provider-expansion'
ALLOWED = {'/app/extensions/xai/video-generation-provider.ts', '/app/dist/video-generation-provider-PMWf4yep.js'}
TRANSACTION = r"""
const fs=require('fs'), crypto=require('crypto');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const allowed=new Set(['/app/extensions/xai/video-generation-provider.ts','/app/dist/video-generation-provider-PMWf4yep.js']);
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
if(p.files.length!==2||new Set(p.files.map(f=>f.remote)).size!==2)throw new Error('Invalid patch package');
const files=p.files.map(f=>{
 if(!allowed.has(f.remote))throw new Error('Unexpected patch target');
 const before=fs.readFileSync(f.remote), after=Buffer.from(f.content,'base64');
 if(hash(after)!==f.target_sha256)throw new Error('Package content hash mismatch');
 return {...f,before,after,current:hash(before)};
});
if(files.every(f=>f.current===f.target_sha256)) {console.log(JSON.stringify({changed:false,already_applied:true}));process.exit(0);}
if(files.some(f=>f.current!==f.expected_sha256&&f.current!==f.target_sha256))throw new Error('Native provider changed; refusing to overwrite it');
const written=[];
try {
 for(const f of files){
  if(f.current===f.target_sha256)continue;
  const temp=f.remote+'.campaign-'+process.pid+'.tmp';
  const stat=fs.statSync(f.remote);
  fs.writeFileSync(temp,f.after,{flag:'wx',mode:stat.mode});
  fs.chownSync(temp,stat.uid,stat.gid);
  fs.renameSync(temp,f.remote);written.push(f);
 }
}catch(error){for(const f of written)fs.writeFileSync(f.remote,f.before);throw error;}
console.log(JSON.stringify({changed:true,hashes:files.map(f=>({file:f.remote,sha256:hash(fs.readFileSync(f.remote))}))}));
"""


def package(rollback=False):
    manifest = load_json(PACKAGE / 'native-after' / 'manifest.json')
    files = []
    for row in manifest['files']:
        if row['remote'] not in ALLOWED:
            raise ValueError('Unexpected deployment target')
        data = (PACKAGE / ('native-before' if rollback else 'native-after') / row['file']).read_bytes()
        target = row['before_sha256'] if rollback else row['after_sha256']
        if hashlib.sha256(data).hexdigest() != target:
            raise ValueError('Local deployment artifact changed; rebuild and retest the patch')
        files.append({'remote': row['remote'], 'expected_sha256': row['after_sha256'] if rollback else row['before_sha256'],
                      'target_sha256': target, 'content': base64.b64encode(data).decode('ascii')})
    return {'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--approval-evidence')
    args = parser.parse_args()
    payload = package(args.rollback)
    config = load_json(ROOT / 'connections.json')
    c = config['grok']
    if not args.apply:
        print(json.dumps({'preview': True, 'host': c['ssh_host'], 'container': c['container'],
                          'files': [{k:v for k,v in row.items() if k != 'content'} for row in payload['files']],
                          'restart_gateway': True, 'generation_calls': 0, 'rollback': args.rollback}, indent=2))
        return
    if not args.approval_evidence or not args.approval_evidence.strip():
        raise ValueError('Explicit current-task approval for the remote patch and gateway restart is required')
    record = {'at': now(), 'approval': args.approval_evidence, 'rollback': args.rollback, 'state': 'activating'}
    receipt = PACKAGE / ('rollback-receipt.json' if args.rollback else 'activation-receipt.json')
    atomic_json(receipt, record)
    record['transaction'] = json.loads(ssh(c, ['docker', 'exec', '-i', c['container'], 'node', '-e', TRANSACTION],
                                          json.dumps(payload).encode('utf-8')))
    atomic_json(receipt, record)
    ssh(c, ['docker', 'restart', c['container']], timeout=45)
    record['state'] = 'restarted_pending_probe'
    atomic_json(receipt, record)
    print(json.dumps({'state': record['state'], 'receipt': str(receipt),
                      'next': 'Run provider_jobs.py probe grok after the gateway starts; no generation was submitted.'}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
