# Call Audit Audio Pipeline

This document records the Call Audit audio flow, the Windows conversion and
Azure Speech failures found during local testing, and the changes made to fix
them.

## API

```http
POST /api/call-audit/analyze
Authorization: Bearer <access-token>
Accept: text/event-stream
Content-Type: multipart/form-data
```

Multipart form field:

| Field | Type | Description |
| --- | --- | --- |
| `file` | File | `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.wma`, `.aac`, or `.webm` audio |

The response is a Server-Sent Events stream. A successful request emits:

```text
converting -> transcribing -> analyzing -> complete
```

The server can emit `ping` events while a long operation is running. A failed
operation emits an `error` event with a `detail` value.

## End-to-end flow

1. `agents/call_audit/router.py` authenticates the user and accepts the file.
2. `services/blob_service.py` checks quota, uploads the original file to Azure
   Blob Storage, and updates the user's storage usage.
3. The router validates the filename extension and writes the bytes to a
   request-specific temporary directory.
4. `agents/call_audit/utils.py` invokes FFmpeg directly and normalizes the
   audio to 16 kHz, mono, 16-bit PCM WAV.
5. `agents/call_audit/service.py` reads the normalized PCM frames, divides long
   audio into chunks, wraps each chunk in a valid WAV container, and sends the
   WAV payloads to Azure Speech.
6. Transcript segments are sorted by timestamp and assembled chronologically.
7. The transcript is divided into text chunks and analyzed concurrently by the
   configured Azure AI Foundry Call Audit Agent.
8. Analysis chunks are merged and returned in the terminal `complete` event.
9. Agent usage is recorded and temporary input/output files are removed.

## Required configuration

```dotenv
BLOB_CONNECTION_STRING=<Azure Blob Storage connection string>
CONTAINER_NAME=user-uploads

AZURE_SPEECH_KEY=<Azure Speech resource key>
AZURE_SPEECH_REGION=<Azure Speech resource region>

AZURE_AI_ENDPOINT=<Azure AI Foundry project endpoint>
CALL_AUDIT_AGENT_ID=<deployed Call Audit agent ID>
```

Azure AI Foundry access uses `DefaultAzureCredential`; the process therefore
also needs a usable local or workload Azure identity.

## Local Windows runtime

Python 3.12 is used for reliable audio dependency compatibility:

```powershell
uv python install 3.12
uv venv .venv312 --python 3.12
uv pip install --python .venv312\Scripts\python.exe -r requirements.txt
uv pip install --python .venv312\Scripts\python.exe pydub imageio-ffmpeg
```

Verify the bundled FFmpeg path:

```powershell
.\.venv312\Scripts\python.exe -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
```

If Windows blocks the executable, unblock it and verify that it runs:

```powershell
Unblock-File -LiteralPath ".\.venv312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
& ".\.venv312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe" -version
```

Start the API without watching the virtual environment:

```powershell
.\.venv312\Scripts\python.exe -m uvicorn main:app --port 5000
```

## Problems found and changes made

### WAV conversion failed

Observed backend exception:

```text
FileNotFoundError: [WinError 2] The system cannot find the file specified
```

Although FFmpeg was available through `imageio-ffmpeg`, `pydub` called the
separate `ffprobe` program while opening the input. That executable was not
installed.

Change: `convert_to_wav()` now invokes the bundled FFmpeg executable directly.
This removes the hidden `ffprobe` dependency and still produces the Azure
Speech input format:

```text
PCM signed 16-bit little-endian
16,000 Hz
mono
WAV container
```

### Transcription produced no text

The original implementation read PCM frames from the converted WAV, discarded
the WAV header, and sent the raw frames with `Content-Type: audio/pcm`.

Azure's short-audio REST API expects a supported container such as PCM WAV.

Change: every fast-path, parallel, and conservative-retry request now wraps its
PCM frames in a complete WAV container and sends:

```http
Content-Type: audio/wav; codecs=audio/pcm; samplerate=16000
Accept: application/json
```

### Transcript ordering

Parallel Speech requests complete in nondeterministic order. The segment list
was sorted, but the transcript text was previously built from completion order.

Change: transcript text is now rebuilt from the timestamp-sorted segment list.

### Misleading analyzing event

The pipeline previously emitted `analyzing` before checking whether Speech
produced a transcript.

Change: it validates the transcript first and emits `analyzing` only when AI
analysis will actually begin.

## Troubleshooting

| Symptom | Likely cause | Check |
| --- | --- | --- |
| `WAV conversion failed` | FFmpeg missing, blocked, or unable to decode input | Backend log beginning `Audio conversion error with FFmpeg` |
| `Transcription produced no text` | Speech rejected audio, credentials are wrong, audio is silent, or language differs | STT status and recognition status in backend logs |
| HTTP `401` from Speech | Invalid Speech key | `AZURE_SPEECH_KEY` |
| HTTP `403` from Speech | Key/resource authorization problem | Azure resource and identity settings |
| HTTP `404` from Speech | Incorrect Speech region/endpoint | `AZURE_SPEECH_REGION` |
| HTTP `429` from Speech | Speech concurrency or quota exceeded | Azure quota and retry logs |
| Agent initialization failure | Foundry endpoint, agent ID, or Azure identity is invalid | `AZURE_AI_ENDPOINT`, `CALL_AUDIT_AGENT_ID`, Azure login |
| UI says stream ended before completion | Frontend did not preserve the backend terminal SSE error | Inspect the last SSE `error.detail` and backend log |

## Validation performed

- The changed Call Audit service and utility modules pass `py_compile`.
- FFmpeg conversion advanced successfully during manual API testing.
- Manual testing reached the Azure Speech transcription stage.
- Live success through Azure Speech and Azure AI Foundry still depends on valid
  external credentials, service availability, and audible test content.

## Remaining risks

- File extension validation currently occurs after Blob upload. An unsupported
  file can be uploaded before the request is rejected.
- A conversion, transcription, or analysis failure does not roll back the
  original Blob upload or storage counter.
- Speaker labels are alternating placeholders, not true speaker diarization.
- Focused automated tests are still needed for conversion, WAV payload
  construction, transcript ordering, retry behavior, and cleanup.

