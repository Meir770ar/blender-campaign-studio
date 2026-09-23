"""Inspect the actual encoded delivery; flag visual diagnostics for human review."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
from campaign_common import run, sha256_file
from editorial import inspect
from audio_finish import loudness
from studio import load_json, write_new


def check(video, plan_path=None, edit_audit_path=None, audio_qa_path=None):
    plan={}
    video=Path(video).resolve(); info=inspect(video)
    stream=next((s for s in info['streams'] if s['codec_type']=='video'),None)
    if not stream: raise ValueError('Delivery has no video stream')
    duration=float(info['format']['duration'])
    report={'file':str(video),'sha256':sha256_file(video),'bytes':video.stat().st_size,'media':info,'errors':[]}
    if stream['codec_name']!='h264' or stream.get('pix_fmt')!='yuv420p': report['errors'].append('Expected H.264 yuv420p delivery')
    if plan_path:
        plan=load_json(plan_path)
        if (stream['width'],stream['height'])!=(plan['width'],plan['height']): report['errors'].append('Dimensions differ from plan')
        if abs(duration-plan['frames']/plan['fps'])>1/plan['fps']: report['errors'].append('Duration differs from plan')
        top,bottom=stream['avg_frame_rate'].split('/')
        if not float(bottom) or abs(float(top)/float(bottom)-plan['fps'])>.001: report['errors'].append('Frame rate differs from plan')
        expects_audio=any(c['kind']=='sound' for c in plan['clips'])
        if expects_audio and not any(s['codec_type']=='audio' for s in info['streams']): report['errors'].append('Expected audio missing')
    run(['ffmpeg','-v','error','-xerror','-i',video,'-f','null','-'],timeout=1800)
    _,log=run(['ffmpeg','-hide_banner','-i',video,'-an','-vf','blackdetect=d=0.2:pix_th=0.1,freezedetect=n=-50dB:d=1',
               '-f','null','-'],timeout=1800)
    report['visual_review_signals']=[line.strip() for line in log.splitlines() if 'black_start:' in line or 'freeze_' in line]
    targets={field: plan[field] for field in ('audio_target_lufs','audio_true_peak_max') if field in plan}
    report['audio_targets_source']='plan' if targets else 'none'
    if audio_qa_path:
        qa=load_json(audio_qa_path)
        if not isinstance(qa,dict) or 'target_lufs' not in qa or 'peak_limit' not in qa:
            raise ValueError('Audio QA report lacks target_lufs/peak_limit; pass the qa.json written by audio_finish.py')
        for field, key in (('audio_target_lufs','target_lufs'),('audio_true_peak_max','peak_limit')):
            targets.setdefault(field, qa[key])
        report['audio_qa']={'report':str(Path(audio_qa_path).resolve()),'sha256':sha256_file(audio_qa_path),'master_pass':qa.get('pass')}
        report['audio_targets_source']='plan+audio_qa' if report['audio_targets_source']=='plan' else 'audio_qa'
    if any(s['codec_type']=='audio' for s in info['streams']):
        report['audio_measurement']=loudness(video,-16,-1.5,9)
        if not targets:
            report.setdefault('warnings',[]).append('Loudness and true peak were measured but not gated: put audio_target_lufs/audio_true_peak_max in the plan or pass --audio-qa with the mix qa.json')
        for field, measured, tolerance in [('audio_target_lufs','input_i',1),('audio_true_peak_max','input_tp',0)]:
            if field not in targets: continue
            target=float(targets[field]); actual=float(report['audio_measurement'][measured])
            if not math.isfinite(target): raise ValueError(f'{field} must be finite')
            outside=abs(actual-target)>tolerance if field=='audio_target_lufs' else actual>target
            if not math.isfinite(actual) or outside:
                report['errors'].append(f'{field} failed: measured {actual}, target {target}')
    if edit_audit_path:
        evidence=load_json(edit_audit_path)
        report['edit_audit']={'report':str(Path(edit_audit_path).resolve()), 'sha256':sha256_file(edit_audit_path)}
        if evidence.get('schema_version')!=1 or evidence.get('technical_pass') is not True:
            report['errors'].append('Edit audit has not passed its technical checks')
        if evidence.get('target_sha256')!=report['sha256']:
            report['errors'].append('Edit audit belongs to different delivery bytes; audit the actual encoded copy')
        files=evidence.get('files')
        if not isinstance(files,dict):
            report['errors'].append('Edit audit source manifest is missing')
        else:
            for path, digest in files.items():
                if not Path(path).is_file() or sha256_file(path)!=digest:
                    report['errors'].append(f'Edit audit source changed or is missing: {Path(path).name}')
        report['edit_audit']['listening_and_motion_review_required']=True
    report['technical_pass']=not report['errors']; report['creative_listening_and_visual_review_required']=True
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--video',required=True); p.add_argument('--plan'); p.add_argument('--edit-audit'); p.add_argument('--audio-qa'); p.add_argument('--out',required=True)
    a=p.parse_args()
    try:
        report=check(a.video,a.plan,a.edit_audit,a.audio_qa); write_new(a.out,report)
        print(json.dumps({'technical_pass':report['technical_pass'],'report':str(Path(a.out).resolve())}))
        if not report['technical_pass']: sys.exit(1)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error: print(f'ERROR: {error}',file=sys.stderr); sys.exit(1)
