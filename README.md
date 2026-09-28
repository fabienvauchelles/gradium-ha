# gradium-ha

Home Assistant integration for Gradium speech-to-text and streaming
text-to-speech, usable in Assist pipelines and with voice satellites such as
the Home Assistant Voice Preview Edition.

This is an unofficial community project. It is not affiliated with, endorsed
by, or supported by Gradium.

## What you get

Add your Gradium API key, and two entities show up on one service device:

- **`stt.gradium`**, speech-to-text. The audio goes to Gradium while you are
  still speaking, and the transcript is asked for the moment Home Assistant
  decides you have stopped.
- **`tts.gradium`**, text-to-speech that takes streamed text. When the
  conversation agent writes its answer bit by bit, words go to Gradium as they
  arrive and audio starts coming back before the answer is finished.

French, English, German, Spanish and Portuguese are supported on both sides.
The voice list is the Gradium catalogue plus the custom voices of your
Gradium organisation.

## Why it exists

Gradium streams both ways over a WebSocket, which fits the way Home
Assistant's assist pipeline already works:
audio in as it is captured, text out as the language model writes it. Doing it
as a native integration, rather than through a Wyoming server, saves a
container and a network hop and needs no extra Python package: it uses Home
Assistant's own HTTP session.

## Install

1. **HACS.** Open HACS, then Custom repositories, add
   `https://github.com/fabienvauchelles/gradium-ha` as an **Integration**, and
   download **Gradium**. Restart Home Assistant Core: a new integration is not
   picked up by a config reload.
2. **Add the integration.** Settings > Devices & services > Add integration >
   **Gradium**.
3. **Use it in a voice assistant.** Settings > Voice assistants, open your
   assistant, and pick **Gradium** as the speech-to-text and text-to-speech
   engine, with the language you speak.

Home Assistant 2026.9 or later is required.

## Configuration

- **API key.** Created in the Gradium dashboard. It is checked with a credits
  read before the entry is saved, so a typo is caught right away.
- **Region.** `Europe` (the default) sends every request to
  `eu.api.gradium.ai`; `Global` uses `api.gradium.ai`.

Only one Gradium entry can exist.

## Options

Settings > Devices & services > Gradium > Configure:

- **Default voice.** Voices of the saved language, plus your custom voices.
  To see the voices of another language, save that language first, then open
  the options again. Default: Gaspard, a French male voice.
- **Text-to-speech model.** `default`, or `gradium-tts-beta`.
- **Language.** The text-to-speech default language, and the speech-to-text
  language when the pipeline asks for one Gradium does not support.

Saving the options reloads the integration. A single text-to-speech call can
also override the voice and the model with the `voice` and `model` options.

## Entities

| Entity | What it does |
|---|---|
| `tts.gradium` | Text-to-speech. Returns 48 kHz mono WAV; Home Assistant converts it to what the speaker asks for |
| `stt.gradium` | Speech-to-text. Accepts what the assist pipeline sends: 16 kHz, 16-bit, mono PCM |

Both belong to the **Gradium** service device.

## Gradium account

Using Gradium requires a Gradium account; review Gradium's terms and pricing
for your use case.

## What is stored

The API key goes into the Home Assistant config entry, which is where Home
Assistant keeps integration secrets. It is sent only in the `x-api-key` header
to Gradium, never logged, and replaced with `**REDACTED**` in the diagnostics
download. The voice list is kept in memory and read again at each start.
Nothing else is stored.

## Troubleshooting

- **"Gradium refused the API key".** The key was revoked or mistyped. Home
  Assistant asks for a new one under Settings > Devices & services; the
  integration reloads once it is accepted. On the wire this is a 401 on REST, or a WebSocket closed with
  code 1008 that a credits read then confirms with a 401.
- **"Gradium has no credit left".** The Gradium account has no credit left.
  The key is fine, so no new one is asked for.
- **"Gradium did not answer in time".** No connection within 10 seconds, no
  `ready` within 5 seconds, no audio for 10 seconds once the whole text was
  sent, or no final transcript within 3 seconds after you stopped talking. Usually network trouble; the next request opens a new
  connection.
- **Speech-to-text returns nothing and the assistant says it did not
  understand.** Gradium heard no words (silence or a false wake), which Home
  Assistant reports as "no text recognized", not as a failure.
- **The integration stays in "retrying setup".** Gradium could not be reached
  or answered with a server error while the voices were listed. Home Assistant
  retries on its own.

The diagnostics download (Settings > Devices & services > Gradium > the three
dots) holds the region and the number of voices, and never the key.

## Development

```
make build   # provision .venv with Home Assistant and the test harness
make check   # ruff + mypy + pytest, fails on any
make test    # tests on their own
```

Home Assistant 2026.9 needs Python 3.14, which `make build` provisions through
uv.

The integration is layered: `custom_components/gradium/client/` speaks
Gradium's REST and WebSocket protocol and imports nothing from Home Assistant;
the modules around it adapt it to Home Assistant's config entries, `stt` and
`tts` entities. The tests run the real client against a fake Gradium server on
loopback, through Home Assistant's own config flow, `tts` and `stt` APIs. They
never reach the real API.

The wire protocol as the integration uses it:
[`docs/protocol.md`](docs/protocol.md).

## License

`LicenseRef-FSL-1.1-MIT`, the Functional Source License 1.1 with an MIT future
license. See [`LICENSE`](LICENSE).
