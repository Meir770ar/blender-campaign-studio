"""Compress and deliver one final viewing copy to the user's verified personal WAHA self-chat.

The WAHA host, self-chat id, session and credentials file come from connections.json (`whatsapp`
section); nothing personal is hard-coded here. The API key stays on the WAHA host."""
from __future__ import annotations
import argparse
import base64
from datetime import datetime
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys
from urllib.parse import quote
from campaign_common import atomic_json, digest_json, lock, new_directory, now, run, sha256_file
from editorial import inspect
from studio import load_json, number, write_new

def _whatsapp_config():
    path=Path(__file__).resolve().parent.parent/'connections.json'
    entry=(load_json(path).get('whatsapp') if path.is_file() else None) or {}
    return {'ssh_host':str(entry.get('ssh_host') or ''),'self_chat':str(entry.get('self_chat') or ''),
            'session':str(entry.get('session') or 'default'),
            'credentials_file':str(entry.get('credentials_file') or '/opt/waha/.credentials')}


_CONFIG=_whatsapp_config()
HOST=_CONFIG['ssh_host']
SELF_CHAT=_CONFIG['self_chat']
SESSION=_CONFIG['session']
CREDENTIALS_FILE=_CONFIG['credentials_file']
NOT_CONFIGURED='WhatsApp delivery is not configured: set whatsapp.ssh_host and whatsapp.self_chat in connections.json'


def api(endpoint, body=None):
    if not HOST or not SELF_CHAT: raise ValueError(NOT_CONFIGURED)
    # The key stays on the WAHA host; only an in-memory request crosses SSH. No public asset URL needed.
    code="""import sys,json,urllib.request,urllib.error
from pathlib import Path
payload=json.load(sys.stdin)
key=next(line.split('=',1)[1].strip() for line in Path(payload['credentials_file']).read_text().splitlines() if line.startswith('WAHA_API_KEY_PLAIN='))
req=urllib.request.Request('http://127.0.0.1:3000'+payload['endpoint'],data=json.dumps(payload['body']).encode() if payload['body'] is not None else None,headers={'X-Api-Key':key,'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(req,timeout=180) as response:
  result=json.load(response)
 print(json.dumps({'ok':True,'result':result}))
except urllib.error.HTTPError as error:
 print(json.dumps({'ok':False,'http_status':error.code}))
"""
    result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',HOST,shlex.join(['python3','-c',code])],
        input=json.dumps({'endpoint':endpoint,'body':body,'credentials_file':CREDENTIALS_FILE}).encode(),capture_output=True,timeout=210)
    if result.returncode: raise ValueError('WAHA transport failed; reconcile the recorded attempt before retrying')
    try: value=json.loads(result.stdout)
    except ValueError: raise ValueError('WAHA returned no structured receipt; do not resend') from None
    if not value.get('ok'): raise ValueError(f'WAHA HTTP {value.get("http_status")}; response withheld')
    return value['result']


def session_status():
    result=api('/api/sessions/'+SESSION)
    return {'working':result.get('status')=='WORKING','self_matches':result.get('me',{}).get('id')==SELF_CHAT}


def compress(source, output, max_mib=15, max_edge=1280):
    source=Path(source).resolve()
    number(max_mib,'max_mib',1,100); number(max_edge,'max_edge',320,1920)
    info=inspect(source); video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
    if not video: raise ValueError('Source has no video')
    if video.get('color_transfer') in ('smpte2084','arib-std-b67') or video.get('color_primaries')=='bt2020':
        raise ValueError('WhatsApp copy requires a reviewed SDR master')
    duration=float(info['format']['duration']); maximum=int(max_mib*1024*1024)
    audio=any(s['codec_type']=='audio' for s in info['streams'])
    rate=video.get('avg_frame_rate','0/1').split('/'); fps=float(rate[0])/float(rate[1]) if float(rate[1]) else 0
    if fps<=0 or duration<=0: raise ValueError('Unknown duration/frame rate')
    output=new_directory(output)
    ratio=min(1,max_edge/max(video['width'],video['height']))
    width=max(2,int(video['width']*ratio)//2*2); height=max(2,int(video['height']*ratio)//2*2)
    vf=f'scale={width}:{height},setsar=1,format=yuv420p'
    if fps>30: vf+=',fps=30'
    base=['ffmpeg','-v','error','-i',source,'-map','0:v:0','-map','0:a:0?','-vf',vf,'-c:v','libx264','-preset','medium']
    tail=['-c:a','aac','-b:a','128k','-ar','48000','-movflags','+faststart','-n']
    candidate=output/'viewing-crf22.mp4'
    run(base+['-crf','22']+tail+[candidate],timeout=3600,log=output/'compression.log')
    if candidate.stat().st_size>maximum:
        bitrate=int(maximum*8*.94/duration)-(128000 if audio else 0)
        if bitrate<500000: raise ValueError('Size budget would require excessive quality loss; choose a larger approved viewing-copy budget')
        passlog=output/'two-pass'
        run(base+['-b:v',str(bitrate),'-pass','1','-passlogfile',passlog,'-an','-f','null','-'],timeout=3600,log=output/'pass1.log')
        candidate=output/'viewing-sized.mp4'
        run(base+['-b:v',str(bitrate),'-pass','2','-passlogfile',passlog]+tail+[candidate],timeout=3600,log=output/'pass2.log')
    final=inspect(candidate); stream=next(s for s in final['streams'] if s['codec_type']=='video')
    if candidate.stat().st_size>maximum or abs(float(final['format']['duration'])-duration)>max(.1,2/fps):
        raise ValueError('Compressed size/duration check failed')
    if stream['codec_name']!='h264' or stream.get('pix_fmt')!='yuv420p': raise ValueError('Unexpected viewing-copy encoding')
    if audio and not any(s['codec_type']=='audio' for s in final['streams']): raise ValueError('Compression lost audio')
    run(['ffmpeg','-v','error','-xerror','-i',candidate,'-f','null','-'],timeout=1800)
    report={'master':str(source),'master_sha256':sha256_file(source),'copy':str(candidate),'copy_sha256':sha256_file(candidate),
        'bytes':candidate.stat().st_size,'max_bytes':maximum,'width':stream['width'],'height':stream['height'],
        'duration':float(final['format']['duration']),'master_preserved':True,'visual_review_required':True}
    # Sizing guidance for long copies: 15 MiB over 150 s is ~800 kbps, visibly soft at 720p.
    kbps=round(candidate.stat().st_size*8/float(final['format']['duration'])/1000)
    report['total_kbps']=kbps
    if stream['width']>=1280 and kbps<1500:
        suggested=math.ceil(float(final['format']['duration'])*1700/8/1024)+1
        report['quality_note']=(f'{kbps} kbps total is low for {stream["width"]}x{stream["height"]}; for a cleaner viewing copy rerun '
                                f'compress with --max-mib {suggested} (the master is untouched)')
    write_new(output/'compression.json',report)
    return report


def prepare(copy, deliveries, caption, evidence):
    copy=Path(copy).resolve()
    if not evidence.strip(): raise ValueError('Record the user instruction authorizing this final self-delivery')
    if not HOST or not SELF_CHAT: raise ValueError(NOT_CONFIGURED)
    info=inspect(copy)
    video=next((s for s in info['streams'] if s['codec_type']=='video'),{})
    if copy.suffix.lower()!='.mp4' or video.get('codec_name')!='h264' or video.get('pix_fmt')!='yuv420p':
        raise ValueError('Use a validated compressed H.264 MP4 copy')
    if copy.stat().st_size>100*1024*1024: raise ValueError('Viewing copy exceeds the helper safety cap')
    identity={'sha256':sha256_file(copy),'chat':SELF_CHAT,'session':SESSION}
    folder=Path(deliveries).resolve()/digest_json(identity); folder.mkdir(parents=True,exist_ok=True)
    with lock(folder/'.lock'):
        if not (folder/'delivery.json').exists():
            atomic_json(folder/'delivery.json',{'id':folder.name,**identity,'copy':str(copy),'caption':caption,
                'approval_evidence':evidence,'state':'prepared','created_at':now()})
    return folder


def send(folder):
    folder=Path(folder).resolve()
    with lock(folder/'.lock'):
        job=load_json(folder/'delivery.json')
        if job['state']!='prepared': raise ValueError('Delivery already attempted; check its receipt instead of sending twice')
        if job['chat']!=SELF_CHAT or job['session']!=SESSION: raise ValueError('Only the verified personal self-chat is supported')
        if sha256_file(job['copy'])!=job['sha256']: raise ValueError('Viewing copy changed after preparing delivery')
        health=session_status()
        if not all(health.values()): raise ValueError('Personal WAHA session is not WORKING or identity differs; do not switch accounts')
        job.update(state='sending',attempted_at=now()); atomic_json(folder/'delivery.json',job)
        body={'session':SESSION,'chatId':SELF_CHAT,'caption':job['caption'],'asNote':False,'convert':False,
              'file':{'mimetype':'video/mp4','filename':'campaign-'+job['sha256'][:16]+'.mp4',
                      'data':base64.b64encode(Path(job['copy']).read_bytes()).decode()}}
        try:
            result=api('/api/sendVideo',body)
            message_id=result.get('id'); message_id=message_id.get('_serialized') if isinstance(message_id,dict) else message_id
            if not message_id: raise ValueError('No message identifier in WAHA receipt')
            job.update(state='accepted',message_id=message_id,ack=result.get('ack'),accepted_at=now())
        except Exception:
            job['state']='unknown'; atomic_json(folder/'delivery.json',job)
            raise ValueError('Delivery result uncertain; reconcile the original attempt, do not resend') from None
        atomic_json(folder/'delivery.json',job)
        return {k:job[k] for k in ('state','message_id','ack')}


def status(folder):
    folder=Path(folder).resolve()
    with lock(folder/'.lock'):
        job=load_json(folder/'delivery.json')
        if not job.get('message_id'): return {'state':job['state'],'reconcile_required':job['state']!='prepared'}
        result=api('/api/'+SESSION+'/chats/'+quote(SELF_CHAT,safe='')+'/messages/'+quote(job['message_id'],safe=''))
        ack=result.get('ack')
        job.update(ack=ack,checked_at=now())
        if isinstance(ack,(int,float)) and ack>=2: job['state']='delivered'
        atomic_json(folder/'delivery.json',job)
        return {'state':job['state'],'message_id':job['message_id'],'ack':ack}


def video_hash(message):
    """Read the video digest from the observed WAHA/Baileys message envelope."""
    value=message
    for key in ('_data','message','videoMessage','fileSha256'):
        if not isinstance(value,dict): return None
        value=value.get(key)
    if isinstance(value,dict): value=value.get('data')
    try:
        if isinstance(value,str): raw=base64.b64decode(value,validate=True)
        elif isinstance(value,list) and all(isinstance(v,int) and not isinstance(v,bool) and 0<=v<=255 for v in value): raw=bytes(value)
        else: return None
    except ValueError:
        return None
    return raw.hex() if len(raw)==32 else None


def reconcile(folder, limit=100):
    """Read recent self-chat receipts; bind one uncertain attempt, never send again."""
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=500:
        raise ValueError('reconcile limit must be an integer from 1 to 500')
    folder=Path(folder).resolve()
    with lock(folder/'.lock'):
        job=load_json(folder/'delivery.json')
        if job.get('chat')!=SELF_CHAT or job.get('session')!=SESSION:
            raise ValueError('Only the verified personal self-chat is supported')
        if job.get('message_id'):
            return {'state':job['state'],'message_id':job['message_id'],'use_status':True}
        if job.get('state') not in ('sending','unknown') or not job.get('attempted_at'):
            raise ValueError('Reconciliation requires a recorded uncertain attempt; do not send as a probe')
        attempt=datetime.fromisoformat(job['attempted_at'])
        if attempt.tzinfo is None: raise ValueError('attempted_at must include a timezone')
        if sha256_file(job['copy'])!=job['sha256']:
            raise ValueError('Viewing copy changed after preparing delivery')
        health=session_status()
        if not all(health.values()):
            raise ValueError('Personal WAHA session is not WORKING or identity differs')
        messages=api('/api/'+SESSION+'/chats/'+quote(SELF_CHAT,safe='')+'/messages?limit='+str(limit)+'&downloadMedia=false')
        if not isinstance(messages,list): raise ValueError('Unexpected WAHA message-list response; do not resend')
        matches={}
        for message in messages:
            if not isinstance(message,dict) or message.get('fromMe') is not True: continue
            timestamp=message.get('timestamp')
            if isinstance(timestamp,bool) or not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp): continue
            # Five seconds allows clock/rounding skew, never an arbitrary older matching video.
            if timestamp<attempt.timestamp()-5 or timestamp>datetime.now(attempt.tzinfo).timestamp()+5: continue
            if video_hash(message)!=job['sha256']: continue
            mid=message.get('id'); mid=mid.get('_serialized') if isinstance(mid,dict) else mid
            if isinstance(mid,str) and mid: matches[mid]=message
        if len(matches)!=1:
            return {'state':job['state'],'reconcile_required':True,'matching_messages':len(matches),
                    'scanned_messages':len(messages),'reason':'No unique outgoing hash and attempt-time match; do not resend'}
        mid,message=next(iter(matches.items())); ack=message.get('ack')
        delivered=isinstance(ack,(int,float)) and not isinstance(ack,bool) and math.isfinite(ack) and ack>=2
        job.update(state='delivered' if delivered else 'accepted',message_id=mid,ack=ack,
                   reconciled_at=now(),reconciled_by='unique outgoing video SHA256 and attempt timestamp')
        atomic_json(folder/'delivery.json',job)
        return {'state':job['state'],'message_id':mid,'ack':ack,'reconciled':True}


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('probe')
    q=sub.add_parser('compress'); q.add_argument('--source',required=True); q.add_argument('--out-dir',required=True)
    q.add_argument('--max-mib',type=float,default=15); q.add_argument('--max-edge',type=int,default=1280)
    q=sub.add_parser('prepare'); q.add_argument('--copy',required=True); q.add_argument('--deliveries',required=True)
    q.add_argument('--caption',default='הסרטון המוכן — עותק צפייה מכווץ.'); q.add_argument('--evidence',required=True)
    for name in ('send','status'):
        q=sub.add_parser(name); q.add_argument('--delivery',required=True)
    q=sub.add_parser('reconcile'); q.add_argument('--delivery',required=True); q.add_argument('--limit',type=int,default=100)
    a=p.parse_args()
    if a.command=='probe': result=session_status()
    elif a.command=='compress': result=compress(a.source,a.out_dir,a.max_mib,a.max_edge)
    elif a.command=='prepare': result={'delivery':str(prepare(a.copy,a.deliveries,a.caption,a.evidence))}
    elif a.command=='send': result=send(a.delivery)
    elif a.command=='reconcile': result=reconcile(a.delivery,a.limit)
    else: result=status(a.delivery)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try: main()
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        print(f'ERROR: {error}',file=sys.stderr); sys.exit(1)
