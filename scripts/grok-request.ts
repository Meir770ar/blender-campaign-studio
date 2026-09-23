// Request-only extension of the installed OpenClaw provider. Auth and transport stay native.
// Contracts: docs.x.ai/developers/model-capabilities/video/{generation,reference-to-video,extension}
const CAMPAIGN_XAI_CONTRACT = "20260909-v1.5-1080p";
const XAI_VIDEO_MODELS = [DEFAULT_XAI_VIDEO_MODEL, "grok-imagine-video-1.5"];

function resolveDurationSeconds(params: { durationSeconds?: number; min?: number; max?: number }): number | undefined {
  if (params.durationSeconds === undefined) return undefined;
  if (!Number.isInteger(params.durationSeconds) || params.durationSeconds! < (params.min ?? 1) || params.durationSeconds! > (params.max ?? 15)) {
    throw new Error(`xAI duration must be an integer from ${params.min ?? 1} to ${params.max ?? 15}; no request submitted.`);
  }
  return params.durationSeconds;
}

function resolveAspectRatio(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const normalized = normalizeOptionalString(value);
  if (!normalized || !XAI_VIDEO_ASPECT_RATIOS.has(normalized)) throw new Error("Unsupported xAI aspect ratio.");
  return normalized;
}

function resolveResolution(value: string | undefined): "480p" | "720p" | "1080p" | undefined {
  if (value === undefined) return undefined;
  const normalized = value.trim().toLowerCase();
  if (normalized !== "480p" && normalized !== "720p" && normalized !== "1080p") throw new Error("Unsupported xAI resolution.");
  return normalized;
}

function imageRole(input: VideoGenerationSourceInput): string {
  const role = normalizeOptionalString(input.role)?.toLowerCase() ?? "first_frame";
  if (!["first_frame", "last_frame", "reference_image"].includes(role)) throw new Error("Unsupported xAI image role.");
  return role;
}

function resolveXaiVideoMode(req: VideoGenerationRequest): "generate" | "referenceToVideo" | "edit" | "extend" {
  if (req.inputVideos?.length) return req.durationSeconds === undefined ? "edit" : "extend";
  return (req.inputImages ?? []).some(image => imageRole(image) !== "first_frame") ? "referenceToVideo" : "generate";
}

function buildCreateBody(req: VideoGenerationRequest): Record<string, unknown> {
  const model = normalizeOptionalString(req.model) ?? DEFAULT_XAI_VIDEO_MODEL;
  if (!XAI_VIDEO_MODELS.includes(model)) throw new Error("Unsupported xAI video model; no automatic model fallback.");
  const modern = model === "grok-imagine-video-1.5";
  const images = req.inputImages ?? [], videos = req.inputVideos ?? [];
  if ((req.inputAudios?.length ?? 0) > 0) throw new Error("Custom reference audio is not enabled on this subscription route.");
  if (req.audio !== undefined && typeof req.audio !== "boolean") throw new Error("xAI audio must be boolean.");
  if (videos.length > 1 || (videos.length && images.length)) throw new Error("xAI accepts one video, without image inputs.");
  const first = images.filter(image => imageRole(image) === "first_frame");
  const last = images.filter(image => imageRole(image) === "last_frame");
  const refs = images.filter(image => imageRole(image) === "reference_image");
  if (first.length > 1 || last.length > 1 || refs.length > 7) throw new Error("xAI supports one first frame, one last frame, and at most seven reference images.");
  if (!modern && (last.length || (first.length && refs.length))) throw new Error("Pinned last frames and mixed frame/reference inputs require grok-imagine-video-1.5.");
  if (typeof req.prompt !== "string" || !req.prompt.trim()) throw new Error("A video direction prompt is required.");
  const body: Record<string, unknown> = { model, prompt: req.prompt };
  const mode = resolveXaiVideoMode(req);
  if (mode === "edit" || mode === "extend") {
    if (req.resolution !== undefined || req.aspectRatio !== undefined || req.audio !== undefined) {
      throw new Error("Video edit/extend inherits source format and audio; omit resolution, aspectRatio and audio.");
    }
    body.video = { url: resolveInputVideoUrl(videos[0]) };
    if (mode === "extend") body.duration = resolveDurationSeconds({ durationSeconds: req.durationSeconds, min: 2, max: 10 });
    return body;
  }
  const resolution = resolveResolution(req.resolution) ?? XAI_VIDEO_DEFAULT_RESOLUTION;
  if (resolution === "1080p" && (!modern || mode !== "generate")) {
    throw new Error("1080p requires grok-imagine-video-1.5 text-to-video or a single first-frame image; reference/last-frame mode is capped at 720p.");
  }
  if (first.length) body.image = { url: resolveRequiredImageUrl(first[0]) };
  if (last.length) body.last_frame = { url: resolveRequiredImageUrl(last[0]) };
  if (refs.length) body.reference_images = refs.map(image => ({ url: resolveRequiredImageUrl(image) }));
  body.duration = resolveDurationSeconds({ durationSeconds: req.durationSeconds, min: 1,
    max: mode === "referenceToVideo" && !modern ? 10 : 15 }) ?? XAI_VIDEO_DEFAULT_DURATION_SECONDS;
  body.aspect_ratio = resolveAspectRatio(req.aspectRatio) ?? XAI_VIDEO_DEFAULT_ASPECT_RATIO;
  body.resolution = resolution;
  if (req.audio !== undefined) body.generate_audio = req.audio;
  return body;
}

