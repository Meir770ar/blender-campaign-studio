# Third-party notices

This repository is licensed under the MIT License (see `LICENSE`). It also contains, or refers to, the following third-party material.

## OpenClaw (MIT)

`_verification/20260909-provider-expansion/native-before/` contains unmodified source files of the OpenClaw xAI video-generation extension (`video-generation-provider.ts`, its test, `index.ts`, `openclaw.plugin.json`, the compiled `video-generation-provider-*.js` and a tool excerpt), and `native-after/` contains this project's patched versions of two of those files. They are included so that `scripts/activate_grok_patch.py` can apply and roll back the patch on a gateway you operate, and so that `scripts/test_grok_native.mjs` can verify it.

OpenClaw is distributed under the MIT License:

```
MIT License

Copyright (c) 2025 Peter Steinberger

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## External programs and services (not redistributed)

Blender, DaVinci Resolve Studio, FFmpeg, Chromium (through Playwright), Tesseract by Mirage, Whisper, and the ElevenLabs, Suno, HeyGen, xAI, Genspark, Magnific, Dzine, Google and WhatsApp services are used through their own installations, accounts and terms. Nothing from them is included in this repository. Fonts are never redistributed; the skill requires a font you have licensed.
