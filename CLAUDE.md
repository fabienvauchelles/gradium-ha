# gradium-ha

Home Assistant custom integration for Gradium (gradium.ai) speech-to-text and
streaming text-to-speech. One HACS integration, domain `gradium`, no add-on,
no card, no PyPI requirement. Usable in Assist pipelines and with voice
satellites such as the Home Assistant Voice Preview Edition.

## What it does

A config entry holds an API key and a region (`eu` by default, `global`).
Setup lists the account's voices, which also validates the key. Two entities
on one service device: `stt.gradium` streams the assist pipeline's audio to
the ASR WebSocket and returns the transcript; `tts.gradium` streams text in
and 48 kHz PCM out over the TTS WebSocket, wrapped as WAV. One socket per
request, on Home Assistant's shared aiohttp session.

## Layers

Dependencies point inward. `client/` is the inner package: it knows the
Gradium protocol and imports nothing from Home Assistant. The modules around
it are adapters that import only from `custom_components.gradium.client`.

Inner, `custom_components/gradium/client/`:

- `__init__.py` the public API; nothing outside the package imports a submodule,
  except the tests patching `const`
- `const.py` URLs, paths, frame sizes, `REGION_ENDPOINTS`, `DEFAULT_TIMEOUTS`
- `errors.py` `GradiumError` and its subclasses: auth, credits exhausted, connection,
  timeout, server, and `GradiumPolicyError` (an unresolved 1008, never leaves the package)
- `models.py` `Region`, `Endpoint`, `Voice`, `Credits`, `TtsSettings`, `SttSettings`, `Timeouts`
- `pcm.py` streaming WAV header, and `PcmFramer` regrouping audio into 2560-byte frames
- `text_chunker.py` `WordChunker`: text deltas to whole words, punctuation kept on its word
- `socket.py` one WebSocket: JSON in and out, close codes and error messages to typed errors
- `rest.py` voices and credits, HTTP status to typed errors, payload parsing
- `refusal.py` resolves a 1008 refusal with a credits read: auth, credits or server error
- `tasks.py` cancelling and awaiting the helper task a session runs beside its main loop
- `tts.py` one TTS session: setup, ready, sender task, audio generator
- `stt.py` one STT session: setup, ready, reader task, framing, flush
- `client.py` `GradiumClient`, the facade and the only class the adapters build

Outer, `custom_components/gradium/`:

- `__init__.py` setup and unload; auth failure to `ConfigEntryAuthFailed`, others to `ConfigEntryNotReady`
- `const.py` domain, option keys, defaults, supported languages and models
- `data.py` runtime data (client and voice list) and the voice filtering rule
- `entity.py` the base entity and its service device
- `config_flow.py` user step, reauth; checks keys with a credits read
- `options_flow.py` voice, TTS model, language; reloads the entry on save
- `tts.py` `GradiumTtsEntity`, overrides `async_stream_tts_audio` only
- `stt.py` `GradiumSttEntity`, 16 kHz 16-bit mono PCM only
- `errors.py` client errors to translated `HomeAssistantError`, reauth on auth failure
- `diagnostics.py` entry data with the key redacted, region, voice counts
- `brand/` `icon.png` and `icon@2x.png`, a plain mark drawn for this project (no
  Gradium logo). Since Home Assistant 2026.3 a custom integration ships its own
  brand images, so nothing goes to `home-assistant/brands` (as in ohm-energie-ha)

## Decisions that are not obvious from the code

**STT flushes as soon as Home Assistant's stream ends, without drain frames.**
Measured: flush right away gave the full transcript 248 to 276 ms after the
last audio frame; seven silent frames first gave the same text at 484 to
527 ms. The server never ends a turn by itself, so without a flush the last
word can come 0.4 to 0.8 s late. Pinned by
`test_speech_is_framed_flushed_and_transcribed`, which asserts the exact
message sequence: setup, audio frames, flush, end_of_stream.

**STT sends 320 ms of silence before the caller's audio** (`STT_LEAD_IN_FRAMES`).
The model drops a short first word that starts within the first 200 ms of the
stream, and a Voice PE starts the stream right after its own wake word, with
no pre-roll from Home Assistant. 250 ms of lead-in was enough in tests; on a
live stream it costs no latency since it goes out while the server waits for
real audio. `delay_in_frames` does not help. Pinned by the STT tests, which
check the four zero frames and then the caller's audio byte for byte.

**STT never waits for the server's `end_of_stream`.** Every word has arrived
by `flushed`; the server's end costs another 0.5 to 0.9 s. Send
`end_of_stream`, then close.

**TTS text goes out as whole words.** The server puts a space between two
text messages, so a word split across LLM deltas would be spoken as two, and a
lone `?` (French puts a space before it) as a separate token. `WordChunker`
holds the trailing word until whitespace follows and keeps punctuation on its
word. Pinned by `test_streamed_message_is_sent_as_whole_words_and_speaks_early`,
which also proves audio arrives before the text is complete: the message
generator is gated on the first audio chunk, so a chunker that buffers to the
end makes the test time out.

**The TTS socket opens lazily.** `_data_gen` yields the WAV header first and
connects when Home Assistant pulls audio. Closing the generator closes the
socket at once (`aclosing` plus the client's `finally`), pinned by
`test_consumer_stopping_early_closes_the_socket`.

**No `preferred_*` TTS option is supported.** Declaring them would make Home
Assistant pass them through instead of converting; the entity only produces
48 kHz WAV, so Home Assistant pops them and runs ffmpeg itself.

**The entity is named "Gradium" with `has_entity_name = False`.** With
`has_entity_name` and `name = None` the TTS manager refuses to generate
("TTS engine name is not set."). The chosen form keeps the ids `tts.gradium`
and `stt.gradium`, which the tests and pipelines rely on.

**The client reads `const.REGION_ENDPOINTS` and `const.DEFAULT_TIMEOUTS` at
construction, through the module.** Never bind them as default arguments: the
tests redirect both regions to the fake server and shrink the timeouts by
patching those two attributes.

**A bad key is only visible after the WebSocket upgrade, and 1008 is not
enough to name it.** Gradium accepts the upgrade, then sends a JSON error with
code 1008 and closes 1008 (a missing key: bare close 1008). A missing
subscription, no credit left or a refused request look the same apart from the
free text, which is no contract. `socket.py` raises `GradiumPolicyError` for any
1008; `GradiumClient` closes the socket, then `refusal.resolve_refusal` reads
the credits: 401 is `GradiumAuthError` (reauth), a zero balance is
`GradiumCreditsExhaustedError` (no reauth), anything else `GradiumServerError`.
Never map 1008 to auth directly: a wrong guess either hides a bad key or
starts a reauth that accepts the same key and loops. A 1000 close before the
expected terminal message is a connection error, not a success.

**An empty transcript is an empty SUCCESS, not an ERROR.** It is what the core
STT integrations return; the assist pipeline reports it as
`stt-no-text-recognized` (nothing heard), while ERROR reads as
`stt-stream-failed`.

**Closing a socket is bounded by `Timeouts.close` (2 s).** It is passed as
aiohttp's `ws_close`, whose default is 10 s, and `GradiumSocket.close` adds an
outer bound at twice that. The STT transcript is known at `flushed`, so a
server that never answers the close must not hold the pipeline.

**One entry only** (`single_config_entry` in the manifest). The options flow
filters voices by the saved language, so picking a voice of a new language
takes two saves; accepted to keep the flow free of network calls.

**Errors are never swallowed.** Every `except` maps to a typed error, an HA
result state (`SpeechResult` ERROR) or a translated `HomeAssistantError`, and
logs. `asyncio.CancelledError` is never caught.

## Testing

`make check` runs ruff, mypy (package only) and pytest. The tests drive Home
Assistant's public surfaces (config and options flows, `tts` media source and
result streams, the `stt` entity, diagnostics over HTTP) against
`tests/fake_gradium/`, an aiohttp server on 127.0.0.1 that reproduces the
measured wire behaviour: an error message and 1008 on a bad key (or a bare
1008, `AuthFailure`), 401 on REST, 80 ms audio chunks,
words lagging audio with the last word held until `flush`. Behaviours
(`TtsBehavior`, `SttBehavior`, `RestFailure`, `AuthFailure`, `remaining_credits`,
`stall_upgrade`) script failures; stalls end when the server stops; records keep
every client message, the decoded STT frames and whether the client closed.

The harness blocks sockets: `fake_gradium` requests `socket_enabled`, and the
harness still only lets connections through to 127.0.0.1. The TTS file cache
goes to `tmp_path`, and the ffmpeg version probe is patched out. Every TTS
request asks for `preferred_format: wav` so no conversion runs. Keys in tests
are made up; `assert_key_not_leaked` checks the debug-level logs and returned
texts. No test touches the real API or the real key file.

`requirements-test.txt` also pins `ha-ffmpeg` and `mutagen`: the harness never
installs component requirements, and `tts` needs both. Bump them with
`homeassistant` using the versions in the `tts` and `ffmpeg` manifests.

## Do not

- Log, echo, `repr` or put in an exception message the API key. It lives in the
  config entry and the `x-api-key` header only.
- Add a catch-all `except Exception`, or a silent fallback value.
- Close Home Assistant's shared aiohttp session.
- Add a PyPI requirement: the official `gradium` SDK opens its own session and
  pulls numpy.
- Wait for the server's `end_of_stream` in STT, or send drain frames before
  `flush`.
- Send partial words or punctuation alone to the TTS socket.
- Import Home Assistant from `client/`.
- Call the real Gradium API from tests or CI.
