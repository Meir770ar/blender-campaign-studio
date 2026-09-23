# Editorial decisions and finishing

## Source understanding

Use `editorial.py analyze` for each supplied source to build content-hashed metadata, scene-change candidates, silence/black diagnostics and contact frames. Use `--transcribe` when speech matters; the installed whisper-local emits word timestamps. Analysis does not assign artistic quality or remove footage automatically. Read the transcript, inspect contact frames, and watch/listen to shortlisted intervals. Image softness can be intentional depth of field; silence can be the emotional beat.

Maintain source IDs and actual timecodes. Mark unusable/weak sections with evidence, then select takes by meaning, performance, clarity, continuity and camera quality. Never edit a quote into a new meaning or confuse a retake with a new statement. Preserve breaths and purposeful pauses. For a dialogue cut, inspect near each timestamp and leave an appropriate handle outside the spoken word.

## EDL as the editable source of truth

Write an EDL with source-relative in/out seconds, a narrative beat and a reason for every selected range. `editorial.py conform` verifies ranges, prevents cuts through known words, extracts normalized local segments, remaps transcript words to output time, and emits a Blender plan. Do not guess output caption timestamps after cutting.

Plan J/L cuts explicitly: picture and audio can start/end differently. The Blender timeline accepts separate sound strips; for advanced overlapping edits, use the conformed assets and author explicit picture/audio ranges in plan.json. Use cutaways to support continuity when warranted, not to conceal a misleading quote. Match cuts should connect action, shape, eyeline or sound; transitions need an intended visual relationship. Do not place a transition on every boundary.

The rough cut must work without decorative effects. Watch at 1x with sound, then silently when intended for autoplay. Remove repetitions and clarify the narrative before polishing. Choose the strongest opening from the actual material rather than always adding a title card. Rhythm follows meaning, performance and music structure; do not mechanically cut every beat.

## Hebrew captions and motion

Use the conformed word timing and `captions.py` to build reviewed phrase groups, RTL rendered text states and timed Blender overlay strips. Retain original typography specs and source words. Word emphasis should land on the spoken/meaningful word. Brand names and key terms can hold a fixed brand color through `brand_words` in the caption style; the spoken-word emphasis then colors the other words, or is disabled with `highlight_color: null`. Read the complete phrase, numbers and embedded English after shaping; inspect each aspect at phone size. Do not split combining marks. Masked/3D titles can be authored as separate Blender shots; font-outline shaping must preserve the same logical Hebrew text.

## Sound

### Action-synchronous Foley is a separate gate

Loudness, a non-silent waveform and master/export correlation do not prove the correct sound or sync. Before mixing foreground Foley, write `foley-events.json` against the locked picture hash. For each event record the actual object/material/action, zero-based picture contact/release frame (and uncertainty/occlusion), selected source hash and in/out samples, the audible attack offset INSIDE that source segment, and the resulting timeline attack sample. Place the audible attack at the visual event, not the start of an untrimmed file. Default timing tolerance is one frame; document wider visual uncertainty rather than claiming frame-exact precision.

Count visible contacts, not walking rhythm: do not add footsteps on leg lift/swing or assume a regular cadence. Use one isolated contact per step; avoid a second recorded step hidden in the tail. Separate heel/toe scuff only when the picture and listening justify it. After changing the edit, remap affected events from source to timeline and invalidate the previous sync review.

Verify sound identity by listening to the actual selected portion, not its filename, generation prompt or catalog label. A plastic screw cap requires plastic thread/seal release and restrained pressure hiss; a metal can-tab snap, crown-cap pop or cap drop is not an interchangeable opening sound. If listening is unavailable, retain an explicit pending semantic review, use a documented real recording where possible and give a short isolated Foley review with the picture to a listener. Do not relabel numerical QA as perceptual approval.

Check foreground Foley solo with picture at 1x, then the full mix and final encoded export in the intended player. Preserve both event timing evidence and listener findings; never describe sound as fully verified until both are present. A user report of wrong object or sync rejects that event regardless of prior technical PASS.

Keep narration, dialogue, music, ambience and effects as separate source assets. `audio_finish.py` renders an explicit sound plan with trims/delays, user-selected cleanup, music ducking driven by speech, per-track `gain_keys` envelopes (linear in dB, for swells, dips and transition lifts that ducking alone cannot direct) and measured two-pass loudness. A musical change of character is two music tracks overlapped with fades and envelopes, planned against the narration clock from `narration_plan.py layout`; not a single generated track hoped to change at the right second. Set delivery targets in the sound plan; a web target is not a broadcast standard. Clean only identified problems. Avoid excessive denoising, compressed breaths, clipped consonants or music that pumps distractingly. Leave space and contrast; sound design is not a whoosh on every cut.

Measure the finished file for loudness/true peak and listen on headphones and a small speaker where possible. Automated metering does not prove intelligibility, accurate pronunciation or a good musical edit. Report what could not be listened to.

### Audio lessons enforced in the runtime

`audio_finish.py` resamples to 48 kHz, trims by sample counts, resets timestamps, delays by samples and pads/trims to the final sample count. This prevents delayed source tails being truncated by time-based trimming. Check selected onsets, late sections and tails on individual stems and encoded output; whole-file LUFS can conceal a missing music ending. Deliberate silence remains valid and must not be filled merely to pass an energy check.

Transcription of non-speech may hallucinate words, including timestamps beyond the clip duration. Treat these as uncertain findings; inspect/listen to the actual interval before editing where possible. A conservative omission when listening is unavailable must be documented as such, not described as confirmed speech removal.

AAC can raise true peaks compared with the WAV. Leave measured encoding headroom and validate the final file against the plan's `audio_target_lufs` (within 1 LU) and `audio_true_peak_max` (strict ceiling). `delivery_qa.py` enforces those fields when supplied; a plan without them is measurement-only for loudness. Do not equate these web delivery targets with a broadcaster specification, and do not claim perceptual approval from correlation or meters.

## Color and image integrity

Read source primaries/transfer/range before normalization. Protect HDR/log sources from an implicit SDR conversion; make and test an explicit color-management plan. Match exposure, white balance, skin/product color and contrast between adjacent shots before the creative look. Generated clips may need matching too; neither a blanket grade nor a blanket ban is appropriate. Do not use a global LUT to hide inconsistent source treatment. Keep the original files and record any corrections.

Conform SDR sources to a single resolution/fps/SAR for assembly. Pick crop versus fit deliberately; maintain a focal-point plan for vertical variants. Use proxies for interactive work and original/conformed masters for delivery. Test color at the actual delivery encoding; inspect highlights, black levels and gradients.

## Revisions and completion

For cumulative community-film revisions, read [community-film-editing.md](community-film-editing.md) and copy `templates/revision-contract.template.md`. Preserve the approved speech/content/speed and music baseline unless the request changes them. Derive picture, image movement, words and sound cues from the same source-to-output clock. Inspect dense windows around changed joins in the encoded master and authoritative copy. A clock-map audit checks declared evidence, not actual motion.

Use `edit_audit.py` when continuity, audio onset or preservation is at issue. It distinguishes an adjacent-sample step from an RMS energy jump, checks selected audio intervals without stereo cancellation, and compares decoded PCM exactly outside allowed repair intervals and within protected speech intervals. Its signals require listening; its PASS is technical only. `audio_finish.py` now rejects all-zero selected SFX by default; an intentionally silent SFX requires `expect_signal:false` and a nonempty `silence_reason`. Nonzero sound still needs identity, sync and in-mix audibility review. Replace an existing duck envelope from the dry music source rather than applying ducking twice.

Translate free-form feedback into a delta: affected beat/timecode, desired change, dependencies, preserved decisions and acceptance check. Record why; do not change unrelated approved sections. Re-render only impacted layers/shots and the necessary final assembly. Keep v001/v002 with their plans; never represent an old render as the new result.

Final review: narrative and brand → motion and continuity → Hebrew and timing → audio → technical delivery. Use a timestamped defect list with critical/major/minor severity. Verify corrected moments from the final encoded file, not only component previews. A critical factual, rights, pronunciation, RTL or missing-media problem prevents describing the film as ready. Present subjective alternatives when they matter, and stop revision loops according to the agreed deadline/budget.
