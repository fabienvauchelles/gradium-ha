# Changelog

## 0.1.1

### Fixed

- Speech-to-text no longer drops a short first word spoken right at the start
  of the stream, as happens when a satellite detects its own wake word: 320 ms
  of silence now goes to Gradium before the audio.
- Speech-to-text accepts region-tagged languages such as `fr-FR`, `fr-BE`,
  `en-US` or `pt-BR`, each sent to Gradium as its base language. Home
  Assistant used to refuse them with HTTP 415.
- Error messages from the WebSocket name the failure once instead of twice,
  for example "Gradium refused the API key: HTTP 401 on the WebSocket upgrade".

### Changed

- Reworded the docstrings of the credit and voice reads.

## 0.1.0

First release.

- Speech-to-text entity `stt.gradium` streaming Home Assistant's 16 kHz audio
  to Gradium over a WebSocket as it arrives, and flushing as soon as the
  pipeline's voice activity detection ends the turn.
- Silence or a false wake gives Home Assistant an empty transcript, which it
  reports as "no text recognized" rather than as a speech-to-text failure.
- Text-to-speech entity `tts.gradium` that accepts streamed text: words go to
  Gradium as the conversation agent writes them, and audio comes back before
  the answer is complete.
- Config flow with the API key and the region (Europe by default), and options
  for the voice, the TTS model and the language.
- A wrong API key starts the reauth flow on both entities: Gradium closes with
  code 1008 for every refusal, so the integration checks the key with a
  credits read before deciding. An empty credit balance is reported as
  "Gradium has no credit left" and does not ask for a new key.
- Closing a Gradium connection cannot hold the voice pipeline for more than a
  few seconds when the server does not answer the close.
- Diagnostics with the key redacted, and a brand icon for the integration page.
