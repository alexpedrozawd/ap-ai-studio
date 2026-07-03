// Cliente fetch tipado para o backend FastAPI (webui/backend). Nenhuma logica de
// negocio aqui - so' monta as chamadas HTTP e tipa as respostas.

const API_BASE = "/api";

export interface VramInfo {
  used_mb: number;
  free_mb: number;
  total_mb: number;
}

export interface StatusResponse {
  comfyui_up: boolean;
  vram: VramInfo | null;
  disk_free_gb: number;
  disk_total_gb: number;
}

export interface JobCreateResponse {
  job_id: string;
}

export type JobState = "queued" | "running" | "done" | "error";

export interface JobStatusResponse {
  id: string;
  mode: string;
  status: JobState;
  returncode: number | null;
  log_tail: string[];
  output_ready: boolean;
  secondary_output_ready: boolean;
}

async function handleResponse<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data);
    } catch {
      // corpo nao era JSON - mantem o statusText
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export async function getStatus(): Promise<StatusResponse> {
  return handleResponse(await fetch(`${API_BASE}/status`));
}

export async function startComfyUI(): Promise<{ starting?: boolean; already_running?: boolean }> {
  return handleResponse(await fetch(`${API_BASE}/comfyui/start`, { method: "POST" }));
}

export async function stopComfyUI(): Promise<{ stopped: boolean }> {
  return handleResponse(await fetch(`${API_BASE}/comfyui/stop`, { method: "POST" }));
}

export interface FaceswapJobParams {
  source: File;
  target: File;
  chunkSeconds?: number;
  dryRun?: boolean;
}

export async function createFaceswapJob(params: FaceswapJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("source", params.source);
  form.append("target", params.target);
  if (params.chunkSeconds) form.append("chunk_seconds", String(params.chunkSeconds));
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/faceswap`, { method: "POST", body: form }));
}

export interface VideoJobParams {
  prompt: string;
  width?: number;
  height?: number;
  numFrames?: number;
  sourceImage?: File;
  dryRun?: boolean;
}

export async function createVideoJob(params: VideoJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("prompt", params.prompt);
  if (params.width) form.append("width", String(params.width));
  if (params.height) form.append("height", String(params.height));
  if (params.numFrames) form.append("num_frames", String(params.numFrames));
  if (params.sourceImage) form.append("source_image", params.sourceImage);
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/video`, { method: "POST", body: form }));
}

export interface InpaintJobParams {
  sourceImage: File;
  maskImage: File;
  prompt?: string;
  useDepthControlnet?: boolean;
  controlnetStrength?: number;
  dryRun?: boolean;
}

export async function createInpaintJob(params: InpaintJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("source_image", params.sourceImage);
  form.append("mask_image", params.maskImage);
  if (params.prompt) form.append("prompt", params.prompt);
  if (params.useDepthControlnet) {
    form.append("use_depth_controlnet", "true");
    form.append("controlnet_strength", String(params.controlnetStrength ?? 0.6));
  }
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/inpaint`, { method: "POST", body: form }));
}

export interface RemoveBgJobParams {
  target: File;
  dryRun?: boolean;
}

export async function createRemoveBgJob(params: RemoveBgJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("target", params.target);
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/removebg`, { method: "POST", body: form }));
}

export interface TtsJobParams {
  text: string;
  language?: string;
  speaker?: string;
  speakerWav?: File;
  dryRun?: boolean;
}

export async function createTtsJob(params: TtsJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("text", params.text);
  form.append("language", params.language ?? "pt");
  if (params.speaker) form.append("speaker", params.speaker);
  if (params.speakerWav) form.append("speaker_wav", params.speakerWav);
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/tts`, { method: "POST", body: form }));
}

export interface DubJobParams {
  audio: File;
  video: File;
  dryRun?: boolean;
}

export async function createDubJob(params: DubJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("audio", params.audio);
  form.append("video", params.video);
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/dub`, { method: "POST", body: form }));
}

export interface DenoiseJobParams {
  target: File;
  wantInstrumental?: boolean;
  dryRun?: boolean;
}

export async function createDenoiseJob(params: DenoiseJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("target", params.target);
  if (params.wantInstrumental) form.append("want_instrumental", "true");
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/denoise`, { method: "POST", body: form }));
}

export interface MusicJobParams {
  prompt: string;
  duration?: number;
  dryRun?: boolean;
}

export async function createMusicJob(params: MusicJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("prompt", params.prompt);
  if (params.duration) form.append("duration", String(params.duration));
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/music`, { method: "POST", body: form }));
}

export interface MasterJobParams {
  original: File;
  processedVideo: File;
  fps?: number;
  dryRun?: boolean;
}

export async function createMasterJob(params: MasterJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("original", params.original);
  form.append("processed_video", params.processedVideo);
  if (params.fps) form.append("fps", String(params.fps));
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/master`, { method: "POST", body: form }));
}

export interface UpscaleJobParams {
  target: File;
  fps?: number;
  dryRun?: boolean;
}

export async function createUpscaleJob(params: UpscaleJobParams): Promise<JobCreateResponse> {
  const form = new FormData();
  form.append("target", params.target);
  if (params.fps) form.append("fps", String(params.fps));
  if (params.dryRun) form.append("dry_run", "true");
  return handleResponse(await fetch(`${API_BASE}/jobs/upscale`, { method: "POST", body: form }));
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  return handleResponse(await fetch(`${API_BASE}/jobs/${jobId}`));
}

export function jobOutputUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/output`;
}

export function jobSecondaryOutputUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/output-secondary`;
}
