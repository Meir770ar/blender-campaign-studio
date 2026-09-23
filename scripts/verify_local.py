"""Explicit local integration check using synthetic calibration media; no provider generation."""
import argparse
import json
from pathlib import Path
from campaign_common import new_directory, run
from studio import write_new, find_blender, main as studio_main, ffprobe
from editorial import analyze, conform
from audio_finish import finish
from captions import build


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--out-dir',required=True); p.add_argument('--font',required=True)
    a=p.parse_args(); out=new_directory(a.out_dir); scripts=Path(__file__).resolve().parent
    run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=red:s=320x180:r=24:d=2',
         '-f','lavfi','-i','color=c=blue:s=320x180:r=24:d=2','-f','lavfi','-i','color=c=green:s=320x180:r=24:d=2',
         '-f','lavfi','-i','sine=frequency=500:sample_rate=48000:duration=6','-filter_complex',
         '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]','-map','[v]','-map','3:a','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-n',out/'source.mp4'])
    report={'synthetic_calibration_only':True,'paid_generations':0}
    report['analysis']=analyze(out/'source.mp4',out/'analysis')
    if not any(abs(t-2)<.1 for t in report['analysis']['scene_candidates']): raise ValueError('Scene detector missed known synthetic cut')
    words={'words':[{'word':'שלום','start':.1,'end':.7},{'word':'עולם','start':.8,'end':1.4},
                    {'word':'גרסה','start':2.1,'end':2.7},{'word':'\u20662026\u2069','start':2.8,'end':3.4}]}
    write_new(out/'source-words.json',words)
    write_new(out/'edl.json',{'fps':24,'width':320,'height':180,'cuts':[
        {'source':'source.mp4','in':2,'out':4,'words_path':'source-words.json','reason':'Known blue segment tests reordered timecodes'},
        {'source':'source.mp4','in':0,'out':2,'words_path':'source-words.json','reason':'Known red segment tests the second edit'}]})
    report['conform']=conform(out/'edl.json',out/'conform')
    mapped=json.loads((out/'conform/words.json').read_text(encoding='utf-8'))['words']
    if mapped[0]['word']!='גרסה' or abs(mapped[2]['start']-2.1)>.001: raise ValueError('Conform word mapping failed')
    # Verify actual picture identity after reordering, not just metadata and filenames.
    import subprocess
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(out/'conform/cut-001.mp4'),'-frames:v','1','-vf','scale=1:1',
                        '-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,check=True).stdout
    if len(raw)!=3 or raw[2]<raw[0]+100: raise ValueError('Conformed picture does not match the selected blue interval')
    style={'width':320,'height':180,'font_file':str(Path(a.font).resolve()),'font_size':28,'padding':16,'align':'center',
           'vertical':'bottom','color':'#ffffff','highlight_color':'#ffd36a','max_words':3,'max_chars':30}
    write_new(out/'caption-style.json',style)
    report['captions']=build(out/'conform/words.json',out/'caption-style.json',out/'captions',24,10)
    run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=700:sample_rate=48000:duration=4','-af',
         "volume=0.7,volume='if(between(t,1,3),1,0)':eval=frame",'-c:a','pcm_s24le','-n',out/'voice.wav'])
    run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=200:sample_rate=48000:duration=4',
         '-c:a','pcm_s24le','-n',out/'music.wav'])
    write_new(out/'mix.json',{'duration':4,'target_lufs':-18,'tracks':[
        {'path':'voice.wav','role':'voice'},{'path':'music.wav','role':'music','gain_db':-8,'fade_in':.05,'fade_out':.1}]})
    report['audio']=finish(out/'mix.json',out/'audio')
    # Music energy at 200 Hz must drop while speech is present (use premaster, before global normalization).
    import numpy as np
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(out/'audio/premaster.wav'),'-ac','1','-f','f32le','-'],capture_output=True,check=True).stdout
    samples=np.frombuffer(raw,dtype=np.float32)
    def band(start):
        x=samples[int(start*48000):int((start+.25)*48000)]
        return abs(np.sum(x*np.exp(-2j*np.pi*200*np.arange(len(x))/48000)))
    if band(1.8) >= band(.4)*.85: raise ValueError('Speech-driven ducking did not attenuate the music band')
    report['ducking_verified']=True
    plan=json.loads((out/'conform/plan.json').read_text(encoding='utf-8'))
    plan['clips']=[x for x in plan['clips'] if x['kind']!='sound']
    plan['clips']+=json.loads((out/'captions/overlays.json').read_text(encoding='utf-8'))['clips']
    plan['clips'].append({'id':'master','kind':'sound','path':str(out/'audio/master.wav'),'start':1,'duration':96,'channel':3})
    write_new(out/'final-plan.json',plan)
    studio_main(['assemble','--plan',str(out/'final-plan.json'),'--out-dir',str(out/'assembly'),'--render'])
    report['assembly']=ffprobe(out/'assembly/preview.mp4')
    # Calibration GLB, not a generated customer asset or a claim of commercial art direction.
    script=out/'make-calibration.py'
    write_new(script,"import bpy\nfrom pathlib import Path\nbpy.ops.object.select_all(action='SELECT')\nbpy.ops.object.delete(use_global=False)\nbpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8)\nbpy.context.object.name='Technical calibration sphere'\nbpy.ops.export_scene.gltf(filepath="+repr(str(out/'calibration.glb'))+",export_format='GLB')\n")
    blender=find_blender()
    run([blender,'--background','--factory-startup','--python-exit-code','1','--python',script],timeout=180,log=out/'calibration.log')
    write_new(out/'product.json',{'template':'product-stage','model':'calibration.glb','width':160,'height':90,'fps':24,'frames':3,'samples':8})
    # Use the user's existing technical typography fixture as an alpha layer over an extracted calibration frame.
    run(['ffmpeg','-v','error','-i',out/'source.mp4','-frames:v','1','-n',out/'background.png'])
    title=next((out/'captions').glob('*.png'))
    write_new(out/'parallax.json',{'template':'artwork-parallax','width':160,'height':90,'fps':24,'frames':3,'samples':8,
        'layers':[{'image':'background.png','depth':-1,'width':11}, {'image':str(title),'depth':1,'width':8}]})
    for name in ('product','parallax'):
        run([blender,'--background','--factory-startup','--python-exit-code','1','--python',scripts/'shot_templates.py',
             '--','--spec',out/f'{name}.json','--out-dir',out/name,'--render'],timeout=900,log=out/f'{name}.log')
        report[name]=ffprobe(out/name/'shot.mp4')
    premium_spec={
        'version':1,'shot_id':'calibration-hero',
        'intent':'Reveal the calibration surface with one controlled reflection, then hold a stable product frame for visual review.',
        'model':'calibration.glb','width':160,'height':90,'fps':24,'frames':24,'samples':8,
        'camera':{'lens_mm':70,'distance':6,'height_offset':.1,'travel':.3,
                  'yaw_start_deg':-7,'yaw_end_deg':2,'fstop':5.6},
        'motion':{'settle_fraction':.75,'sweep_side':'left'},
        'lighting':{'key_energy':800,'fill_energy':200,'rim_energy':900,'sweep_energy':1100},
        'look':{'background_rgba':[.02,.03,.04,1],'floor_roughness':.4,'world_strength':.02,'glare':False}}
    vertical_spec=json.loads(json.dumps(premium_spec))
    vertical_spec.update(shot_id='calibration-vertical-glare',
                         intent='Verify tall delivery framing while the installed Blender 5.1 compositor applies a restrained glow.',
                         width=90,height=160,frames=12)
    vertical_spec['motion']['sweep_side']='right'
    vertical_spec['look']['glare']=True
    variants={'premium-product':premium_spec,'premium-product-vertical-glare':vertical_spec}
    report['premium_product']={}
    for name,spec in variants.items():
        write_new(out/f'{name}.json',spec)
        run([blender,'--background','--factory-startup','--python-exit-code','1','--python',scripts/'premium_product.py',
             '--','--spec',out/f'{name}.json','--out-dir',out/name,'--preview'],
            timeout=900,log=out/f'{name}.log')
        manifest=json.loads((out/name/'render-manifest.json').read_text(encoding='utf-8'))
        if len(manifest['rendered'])!=3 or not all(Path(path).is_file() for path in manifest['rendered']):
            raise ValueError(f'{name} did not create all preview evidence frames')
        report['premium_product'][name]={'manifest':str(out/name/'render-manifest.json'),
             'preview_frames':manifest['rendered'],'action_end_frame':manifest['action_end_frame'],
             'framing_distance':manifest['framing_distance'],'blender_version':manifest['blender_version'],
             'visually_reviewed':False}
    write_new(out/'verification.json',report)
    print(json.dumps({'verification':str(out/'verification.json'),'result':'passed'},indent=2))


if __name__=='__main__': main()
