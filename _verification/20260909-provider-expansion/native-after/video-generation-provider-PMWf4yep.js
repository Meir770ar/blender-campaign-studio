import { c as normalizeOptionalString } from "./string-coerce-DW4mBlAt.js";
import { c as isRecord } from "./utils-CRO4LGEB.js";
import { u as readResponseWithLimit } from "./http-body-CHWaxK2e.js";
import { m as readProviderJsonResponse, r as assertOkOrThrowHttpError } from "./provider-http-errors-HGLTiqMh.js";
import { r as extensionForMime } from "./mime-BaK8UYea.js";
import { a as fetchProviderOperationResponse, c as postJsonRequest, g as waitProviderOperationPollInterval, h as resolveProviderOperationTimeoutMs, i as fetchProviderDownloadResponse, n as createProviderOperationDeadline, p as resolveProviderHttpRequestConfig, r as createProviderOperationTimeoutResolver } from "./shared-CZMxJ_eJ.js";
import "./string-coerce-runtime-ZbuYDJgZ.js";
import "./response-limit-runtime-B7RO3Er4.js";
import { r as isProviderApiKeyConfigured } from "./provider-auth-BHcCmABv.js";
import "./media-mime-CMow-3uR.js";
import { a as resolveApiKeyForProvider } from "./provider-auth-runtime-C07lB0Zw.js";
import "./provider-http-DjXS2nxd.js";
import { d as toImageDataUrl } from "./image-generation-5MolosOP.js";
const DEFAULT_XAI_VIDEO_BASE_URL = "https://api.x.ai/v1";
const DEFAULT_XAI_VIDEO_MODEL = "grok-imagine-video";
const DEFAULT_TIMEOUT_MS = 600_000;
const POLL_INTERVAL_MS = 5_000;
const MAX_POLL_ATTEMPTS = 120;
const XAI_VIDEO_ASPECT_RATIOS = new Set(["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]);
const XAI_VIDEO_MALFORMED_RESPONSE = "xAI video generation response malformed";
// xAI documents these as the only meaningful values; everything else (queued,
// processing, submitted, pending, in_progress, ...) means "keep polling".
const XAI_VIDEO_TERMINAL_FAILURE_STATUSES = new Set(["failed", "error", "expired", "cancelled"]);
const XAI_VIDEO_DEFAULT_DURATION_SECONDS = 8;
const XAI_VIDEO_DEFAULT_ASPECT_RATIO = "16:9";
const XAI_VIDEO_DEFAULT_RESOLUTION = "720p";
const DEFAULT_GENERATED_VIDEO_MAX_BYTES = 64 * 1024 * 1024; // Bounded headroom for native 1080p.

                               
                      
           
                  
                     
           
  

                               
                      
                                                                             
                                                    
                 
           
                 
           
           
                  
                     
           
  

                                   
               
                  
                    
                
  

async function readXaiVideoJson(response          )                                   {
  let payload         ;
  try {
    payload = await readProviderJsonResponse         (response, "xAI video generation response");
  } catch (error) {
    if (error instanceof Error && error.message.endsWith(": malformed JSON response")) {
      throw new Error(XAI_VIDEO_MALFORMED_RESPONSE, { cause: error });
    }
    throw error;
  }
  if (!isRecord(payload)) {
    throw new Error(XAI_VIDEO_MALFORMED_RESPONSE);
  }
  return payload;
}

function xaiErrorMessage(payload                         )                     {
  const error = payload.error;
  if (error === undefined || error === null) {
    return undefined;
  }
  if (!isRecord(error)) {
    throw new Error(XAI_VIDEO_MALFORMED_RESPONSE);
  }
  return normalizeOptionalString(error.message);
}

function readXaiCreateResponse(payload                         )                         {
  return {
    request_id: normalizeOptionalString(payload.request_id),
    error: xaiErrorMessage(payload) ? { message: xaiErrorMessage(payload) } : null,
  };
}

function readXaiStatusResponse(payload                         )                         {
  const video = payload.video;
  if (video !== undefined && video !== null && !isRecord(video)) {
    throw new Error(XAI_VIDEO_MALFORMED_RESPONSE);
  }
  return {
    request_id: normalizeOptionalString(payload.request_id),
    status: normalizeOptionalString(payload.status) ?? "",
    video: isRecord(video) ? { url: normalizeOptionalString(video.url) } : null,
    error: xaiErrorMessage(payload) ? { message: xaiErrorMessage(payload) } : null,
  };
}

function resolveXaiVideoBaseUrl(req                        )         {
  return (
    normalizeOptionalString(req.cfg?.models?.providers?.xai?.baseUrl) ?? DEFAULT_XAI_VIDEO_BASE_URL
  );
}

function resolveGeneratedVideoMaxBytes(req                        )         {
  const configured = req.cfg.agents?.defaults?.mediaMaxMb;
  if (typeof configured === "number" && Number.isFinite(configured) && configured > 0) {
    return Math.floor(configured * 1024 * 1024);
  }
  return DEFAULT_GENERATED_VIDEO_MAX_BYTES;
}

function resolveImageUrl(input                                        )                     {
  if (!input) {
    return undefined;
  }
  const inputUrl = normalizeOptionalString(input.url);
  if (inputUrl) {
    return inputUrl;
  }
  if (!input.buffer) {
    throw new Error("xAI image-to-video input is missing image data.");
  }
  return toImageDataUrl({ ...input, buffer: input.buffer, defaultMimeType: "image/png" });
}

function resolveRequiredImageUrl(input                            )         {
  const imageUrl = resolveImageUrl(input);
  if (!imageUrl) {
    throw new Error("xAI image-to-video input is missing image data.");
  }
  return imageUrl;
}

function resolveInputVideoUrl(input                                        )                     {
  if (!input) {
    return undefined;
  }
  const url = normalizeOptionalString(input.url);
  if (url) {
    return url;
  }
  if (input.buffer) {
    throw new Error("xAI video editing currently requires a remote mp4 URL input.");
  }
  throw new Error("xAI video editing input is missing video data.");
}

// Request-only extension of the installed OpenClaw provider. Auth and transport stay native.
// Contracts: docs.x.ai/developers/model-capabilities/video/{generation,reference-to-video,extension}
const CAMPAIGN_XAI_CONTRACT = "20260909-v1.5-1080p";
const XAI_VIDEO_MODELS = [DEFAULT_XAI_VIDEO_MODEL, "grok-imagine-video-1.5"];

function resolveDurationSeconds(params                                                          )                     {
  if (params.durationSeconds === undefined) return undefined;
  if (!Number.isInteger(params.durationSeconds) || params.durationSeconds  < (params.min ?? 1) || params.durationSeconds  > (params.max ?? 15)) {
    throw new Error(`xAI duration must be an integer from ${params.min ?? 1} to ${params.max ?? 15}; no request submitted.`);
  }
  return params.durationSeconds;
}

function resolveAspectRatio(value                    )                     {
  if (value === undefined) return undefined;
  const normalized = normalizeOptionalString(value);
  if (!normalized || !XAI_VIDEO_ASPECT_RATIOS.has(normalized)) throw new Error("Unsupported xAI aspect ratio.");
  return normalized;
}

function resolveResolution(value                    )                                        {
  if (value === undefined) return undefined;
  const normalized = value.trim().toLowerCase();
  if (normalized !== "480p" && normalized !== "720p" && normalized !== "1080p") throw new Error("Unsupported xAI resolution.");
  return normalized;
}

function imageRole(input                            )         {
  const role = normalizeOptionalString(input.role)?.toLowerCase() ?? "first_frame";
  if (!["first_frame", "last_frame", "reference_image"].includes(role)) throw new Error("Unsupported xAI image role.");
  return role;
}

function resolveXaiVideoMode(req                        )                                                      {
  if (req.inputVideos?.length) return req.durationSeconds === undefined ? "edit" : "extend";
  return (req.inputImages ?? []).some(image => imageRole(image) !== "first_frame") ? "referenceToVideo" : "generate";
}

function buildCreateBody(req                        )                          {
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
  const body                          = { model, prompt: req.prompt };
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

function resolveCreateEndpoint(req                        )         {
  switch (resolveXaiVideoMode(req)) {
    case "edit":
      return "/videos/edits";
    case "extend":
      return "/videos/extensions";
    default:
      return "/videos/generations";
  }
}

async function pollXaiVideo(params   
                    
                   
                     
                  
                        
 )                                  {
  const deadline = createProviderOperationDeadline({
    timeoutMs: params.timeoutMs,
    label: `xAI video generation request ${params.requestId}`,
  });
  for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
    const response = await fetchProviderOperationResponse({
      stage: "poll",
      url: `${params.baseUrl}/videos/${params.requestId}`,
      init: {
        method: "GET",
        headers: params.headers,
      },
      timeoutMs: createProviderOperationTimeoutResolver({
        deadline,
        defaultTimeoutMs: DEFAULT_TIMEOUT_MS,
      }),
      fetchFn: params.fetchFn,
      provider: "xai",
      requestFailedMessage: "xAI video status request failed",
    });
    const payload = readXaiStatusResponse(await readXaiVideoJson(response));
    const normalizedStatus = payload.status.toLowerCase();
    if (normalizedStatus === "done") {
      return payload;
    }
    if (XAI_VIDEO_TERMINAL_FAILURE_STATUSES.has(normalizedStatus)) {
      throw new Error(
        normalizeOptionalString(payload.error?.message) ??
          `xAI video generation ${normalizedStatus}`,
      );
    }
    // Any other status (queued, processing, submitted, pending, in_progress,
    // empty, …) is non-terminal: keep polling.
    await waitProviderOperationPollInterval({ deadline, pollIntervalMs: POLL_INTERVAL_MS });
  }
  throw new Error(`xAI video generation task ${params.requestId} did not finish in time`);
}

async function downloadXaiVideo(params   
              
                                         
                        
                   
 )                               {
  const response = await fetchProviderDownloadResponse({
    url: params.url,
    init: { method: "GET" },
    timeoutMs: params.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    fetchFn: params.fetchFn,
    provider: "xai",
    requestFailedMessage: "xAI generated video download failed",
  });
  const mimeType = normalizeOptionalString(response.headers.get("content-type")) ?? "video/mp4";
  const buffer = await readResponseWithLimit(response, params.maxBytes, {
    onOverflow: ({ maxBytes }) =>
      new Error(`xAI generated video download exceeds ${maxBytes} bytes`),
  });
  return {
    buffer,
    mimeType,
    fileName: `video-1.${extensionForMime(mimeType)?.slice(1) ?? "mp4"}`,
  };
}

function buildXaiVideoGenerationProvider()                          {
  return {
    id: "xai",
    label: "xAI",
    defaultModel: DEFAULT_XAI_VIDEO_MODEL,
    defaultTimeoutMs: DEFAULT_TIMEOUT_MS,
    models: XAI_VIDEO_MODELS,
    isConfigured: ({ agentDir }) =>
      isProviderApiKeyConfigured({
        provider: "xai",
        agentDir,
      }),
    capabilities: {
      generate: {
        maxVideos: 1,
        maxDurationSeconds: 15,
        aspectRatios: [...XAI_VIDEO_ASPECT_RATIOS],
        resolutions: ["480P", "720P", "1080P"],
        supportsAspectRatio: true,
        supportsResolution: true,
        supportsAudio: true,
      },
      imageToVideo: {
        enabled: true,
        maxVideos: 1,
        maxInputImages: 9,
        maxDurationSeconds: 15,
        aspectRatios: [...XAI_VIDEO_ASPECT_RATIOS],
        resolutions: ["480P", "720P", "1080P"],
        supportsAspectRatio: true,
        supportsResolution: true,
        supportsAudio: true,
      },
      videoToVideo: {
        enabled: true,
        maxVideos: 1,
        maxInputVideos: 1,
        maxDurationSeconds: 10,
        supportsAspectRatio: false,
        supportsResolution: false,
        supportsAudio: false,
      },
    },
    async generateVideo(req) {
      const createBody = buildCreateBody(req); // Validate before OAuth refresh or any provider request.
      const auth = await resolveApiKeyForProvider({
        provider: "xai",
        cfg: req.cfg,
        agentDir: req.agentDir,
        store: req.authStore,
      });
      if (!auth.apiKey) {
        throw new Error("xAI API key missing");
      }

      const fetchFn = fetch;
      const deadline = createProviderOperationDeadline({
        timeoutMs: req.timeoutMs,
        label: "xAI video generation",
      });
      const { baseUrl, allowPrivateNetwork, headers, dispatcherPolicy } =
        resolveProviderHttpRequestConfig({
          baseUrl: resolveXaiVideoBaseUrl(req),
          defaultBaseUrl: DEFAULT_XAI_VIDEO_BASE_URL,
          allowPrivateNetwork: false,
          defaultHeaders: {
            Authorization: `Bearer ${auth.apiKey}`,
            "Content-Type": "application/json",
          },
          provider: "xai",
          capability: "video",
          transport: "http",
        });
      // Per-submit idempotency key prevents accidental double-charging if
      // the request is replayed. Polls intentionally reuse `headers` without it.
      const submitHeaders = new Headers(headers);
      submitHeaders.set("x-idempotency-key", crypto.randomUUID());
      const { response, release } = await postJsonRequest({
        url: `${baseUrl}${resolveCreateEndpoint(req)}`,
        headers: submitHeaders,
        body: createBody,
        timeoutMs: resolveProviderOperationTimeoutMs({
          deadline,
          defaultTimeoutMs: DEFAULT_TIMEOUT_MS,
        }),
        fetchFn,
        allowPrivateNetwork,
        dispatcherPolicy,
      });
      let acceptedRequestId                    ;
      try {
        await assertOkOrThrowHttpError(response, "xAI video generation failed");
        const submitted = readXaiCreateResponse(await readXaiVideoJson(response));
        const requestId = normalizeOptionalString(submitted.request_id);
        if (!requestId) {
          throw new Error(
            normalizeOptionalString(submitted.error?.message) ??
              "xAI video generation response missing request_id",
          );
        }
        acceptedRequestId = requestId;
        const completed = await pollXaiVideo({
          requestId,
          headers,
          timeoutMs: resolveProviderOperationTimeoutMs({
            deadline,
            defaultTimeoutMs: DEFAULT_TIMEOUT_MS,
          }),
          baseUrl,
          fetchFn,
        });
        const videoUrl = normalizeOptionalString(completed.video?.url);
        if (!videoUrl) {
          throw new Error(XAI_VIDEO_MALFORMED_RESPONSE);
        }
        const video = await downloadXaiVideo({
          url: videoUrl,
          timeoutMs: createProviderOperationTimeoutResolver({
            deadline,
            defaultTimeoutMs: DEFAULT_TIMEOUT_MS,
          }),
          fetchFn,
          maxBytes: resolveGeneratedVideoMaxBytes(req),
        });
        return {
          videos: [video],
          model: normalizeOptionalString(req.model) ?? DEFAULT_XAI_VIDEO_MODEL,
          metadata: {
            requestId,
            contract: CAMPAIGN_XAI_CONTRACT,
            requestedResolution: createBody.resolution,
            status: completed.status,
            videoUrl,
            mode: resolveXaiVideoMode(req),
          },
        };
      } catch (error) {
        if (acceptedRequestId) throw new Error(`xAI request ${acceptedRequestId} was accepted, but collection did not complete. Reconcile that request; do not regenerate.`, { cause: error });
        throw error;
      } finally {
        await release();
      }
    },
  };
}

export { buildXaiVideoGenerationProvider as t };
