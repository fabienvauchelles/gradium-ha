# Gradium wire protocol, as this integration uses it

Based on the public docs at https://docs.gradium.ai and on the API's observed
wire behaviour. Only what the integration relies on is written here. The fake server in `tests/fake_gradium/` plays these
sequences, so a change here is a change there.

## Endpoints and auth

| Use | Method and path | Notes |
|---|---|---|
| Voices | `GET /api/voices/?include_catalog=true&limit=1000` | Without `include_catalog` only the organisation's own voices come back |
| Credits | `GET /api/usages/credits` | Used to check a key in the config flow |
| TTS | WebSocket `/api/speech/tts` | One socket per request |
| STT | WebSocket `/api/speech/asr` | One socket per request |

Hosts: `api.gradium.ai` (region `global`) and `eu.api.gradium.ai` (region `eu`,
the default). REST is `https://<host>/api`, WebSocket `wss://<host>/api`.

Every call carries the header `x-api-key: <key>`. A bad or missing key:

- REST answers 401, `{"detail": "Invalid or expired API key"}` for a wrong key
  and `{"detail": "No authentication provided."}` for a missing one.
- WebSocket: the upgrade succeeds. A wrong key then gets
  `{"type": "error", "client_req_id": null, "message": "Invalid or expired API key\n...", "code": 1008}`
  and a close 1008; a missing key gets a bare close 1008,
  reason "No authentication provided.". Auth failure is only visible on the
  first receive.

Errors inside a session arrive as `{"type": "error", "message": ..., "code": ...}`
followed by a close: 1002 protocol, 1008 policy or auth, 1011 internal. Code
1008 also covers a missing subscription or a refused request, and nothing but
the free text tells them from a bad key. The client therefore resolves every
1008 with a `GET /usages/credits`: 401 means a bad key (reauth), a zero
balance means no credit left, anything else is a server error.

## TTS sequence

1. Connect `/api/speech/tts`.
2. Send `{"type": "setup", "model_name": "default", "voice_id": "<uid>", "output_format": "pcm_48000"}`.
3. Receive `ready` (15 to 27 ms after connect). It carries `sample_rate`
   (48000 for `pcm_48000`), `frame_size` and other fields the integration
   ignores.
4. Send the text as it comes, as `{"type": "text", "text": "..."}`, whole words
   only. The server inserts a space between two messages, so a word split
   across messages is spoken as two words, and a lone `?` would be spoken as a
   separate token. The integration holds the trailing word until whitespace
   follows it and glues punctuation to the word before it.
5. Send `{"type": "end_of_stream"}` once the text is complete.
6. Meanwhile, receive:
   - `audio`: `{"audio": <base64 PCM s16le mono>, "start_s", "stop_s", ...}`,
     80 ms per message (3840 samples at 48 kHz). Synthesis starts on partial
     text: the first audio arrived before the last text message was sent.
   - `text`: word alignment (`{"text": "D'accord,", "start_s", "stop_s"}`),
     ignored.
   - `end_of_stream`: the last message, then the server closes.

First audio: median 400 ms from before connect on `default`, about 100 ms on
`gradium-tts-beta`. Every clip ends with about 0.5 s of silence.

The integration wraps the PCM in a streaming WAV header (data size 0, as Home
Assistant's Wyoming TTS does) and returns `wav`; Home Assistant converts it for
the satellite with ffmpeg.

## STT sequence

1. Connect `/api/speech/asr`.
2. Send `{"type": "setup", "model_name": "default", "input_format": "pcm_16000", "json_config": {"language": "fr", "delay_in_frames": 7}}`.
3. Receive `ready` (47 to 115 ms after connect, including the connect). It
   reports the model rate (`sample_rate` 24000, `frame_size` 1920) whatever the
   input format.
4. Send audio as `{"type": "audio", "audio": <base64>}`, one 80 ms frame of
   2560 bytes (16 kHz s16le mono) per message. Home Assistant forwards 10 ms
   chunks of 320 bytes; the integration regroups them. Four silent frames
   (320 ms) go first: when speech starts within the first 200 ms of the
   stream, the model can drop a short first word ("Il fait 21 degrés" came
   back as "fait 21 degrés"); with 250 ms or more of lead-in it is kept.
5. Receive meanwhile:
   - `text`: a word or a few (`{"text": "Allume la", "start_s": 0.56}`), about
     0.56 s behind the audio. Each is closed by `end_text`.
   - `step`: every 80 ms, VAD probabilities for 0.5, 1, 2 and 3 s horizons.
     Ignored: Home Assistant's own VAD ends the turn.
6. When Home Assistant's stream ends: zero-pad the last partial frame to 2560
   bytes and send it, then send `{"type": "flush", "flush_id": 1}` right away.
7. Receive `{"type": "flushed", "flush_id": 1}`. Every word of the utterance
   has arrived by then.
8. Send `{"type": "end_of_stream"}` and close without waiting for the server's
   own `end_of_stream`.

The transcript is the `text` payloads joined with spaces. It has capitals,
punctuation and digits ("Mais un minuteur de 10 minutes.").

Why flush without drain frames: flushing right away gave the complete
transcript 248 to 276 ms after the last audio frame; sending 7 silent frames
first gave the same transcripts 484 to 527 ms after. Waiting for the server's
`end_of_stream` after `flushed` costs another 556 to 867 ms for nothing. Without
any flush, the server never ends a turn on its own.
