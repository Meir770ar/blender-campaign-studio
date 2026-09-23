# Video-conditioned Foley: researched candidates and bounded adoption

Research date: 2026-09-07. Source review only: none of these candidates has been installed, benchmarked or approved on the current film. Do not repeat claims of perfect synchronization from repository marketing as established results.

## Candidate assessment

| Tool | Relevant capability | Practical limitation / adoption status |
| --- | --- | --- |
| [HunyuanVideo-Foley](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley) | Video + text conditioned 48k audio, XL/XXL, CLI and community ComfyUI integration | Official README lists XL 16GB VRAM / 8GB offload, XXL 20GB / 12GB offload; Linux primary support. Best first hardware-feasibility candidate for a dedicated Foley pilot, not a proven winner. [License](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley/blob/main/LICENSE) has territory restrictions including outputs (EU/UK/South Korea excluded) and other conditions; not an unrestricted global advertising default. |
| [MMAudio](https://github.com/hkchengrex/MMAudio) | Synchronized V2A, CLI, roughly 6GB VRAM reported for default inference | Code MIT but checkpoints CC BY-NC 4.0; unsuitable as the default commercial production route. Ubuntu tested. Sync encoder center-crops frames; ensure action/feet remain in view. |
| [LTX-2.3 Foley V2A](https://github.com/Lightricks/ComfyUI-LTXVideo) | [Official workflow](https://docs.ltx.io/open-source-model/feature-guides/audio/video-to-audio-foley) generates audio while holding input video fixed; intended SFX-only output | Requires base 22B model, text encoder and Foley LoRA. Docs validate 2.3, not 2.5; short-clip training and seed-sensitive quiet scenes, including footsteps. [Model card](https://huggingface.co/Lightricks/LTX-2.3-22b-LoRA-Foley-V2A) has access conditions, community license and additional dataset-term notes. Hardware and license eligibility remain to verify for this exact workflow. |
| [ControlFoley](https://github.com/xiaomi-research/controlfoley) | Conditions on video + reference sound, including reference timbre independent of timing | Useful research direction for exact object timbre; code Apache 2.0, weights CC BY-NC 4.0. Not a commercial default. |
| [Synchformer](https://github.com/v-iashin/Synchformer) | Predicts temporal offset between audio and video; synchronizability model also provided | A diagnostic, not a Foley editor or guarantee of frame-perfect contact. Sparse, occluded and repeated events require caution. It cannot repair wrong sound identity or multiple independently mistimed events with a single global shift. |

Older [FoleyCrafter](https://github.com/open-mmlab/FoleyCrafter) provides temporal conditioning and a `--temporal_align` route, but should not displace a better-tested candidate merely because a wrapper is easier to find. Review base-model/checkpoint terms separately from repository code licenses.

## Reusable production route

1. Lock each shot's selected source frames and fps. Export a silent analysis proxy without changing time; preserve exact master picture separately. Verify that the conditioning crop retains the sound-producing action. Treat a separate feet/hand crop as an inference choice requiring review, not a replacement output image.
2. Generate a Foley-only candidate from video plus a precise material/action prompt, excluding speech/music. Keep narration/music/ambience on independent buses. Return a WAV/stem and event/shot manifest, not a replacement picture edit.
3. Cache by source bytes, in/out frames, fps, crop, model/checkpoint hash, prompt, settings and seed. Reuse unchanged shot audio; invalidate only changed shots. Load models once per approved batch rather than once per event.
4. Limit the pilot to the current 3.5-second ascent and 2.75-second cap shot. Retain the existing audio for A/B comparison. Allow at most two explicitly budgeted candidates per shot; no open-ended regeneration or automatic paid retry. Any external execution, download/access acceptance or paid operation must follow current task authority.
5. Record setup/download time separately from warm inference time, GPU/VRAM, clip duration, seed, selected outcome and listener correction time. Success means a clear improvement in sound identity and perceived alignment with less manual correction, not just faster generation. Do not promise a speed figure before measurement.
6. Check sync independently of the generated event schedule: isolated Foley + original picture at 1x, then full mix. Use sync models only to flag likely offset/uncertainty. Small remaining errors may receive one bounded manual nudge per event; a repeated or ambiguous failure returns to source/action selection rather than another lengthy blind alignment loop.
7. Integrate only a pilot that passes both current problem shots. Keep an exact-length WAV, source-bound manifest and editable Blender sound strip. Quantized/offloaded variants need their own measured quality/runtime result.

## Evidence boundary

The old workflow compared the export to the waveform placed by the agent. That verified muxing, not whether the placement was correct. A video-conditioned model addresses the missing visual conditioning, but it still requires actual listening and can fail. Do not mark a proposed adapter as installed or the skill as automatically synchronized until an executable integration and a listener-accepted pilot exist.
