# Third-party notices

CPython 3.11.9 Windows embeddable: PSF license in runtime/LICENSE.txt.
PySide6/Shiboken6 6.8.3: LGPLv3/GPL/commercial; unmodified shared Windows wheel
modules (unused WebEngine omitted). Original metadata in runtime/Lib/site-packages;
LGPL/GPL text in licenses/qt. Users may replace libraries and reverse engineer
for debugging modifications to LGPL components. Corresponding source:
https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/
https://download.qt.io/archive/qt/6.8/6.8.3/submodules/

FFmpeg/ffprobe: original Gyan GPLv3 build. Exact version/config/source commit in
licenses/ffmpeg/README.txt; GPL text in licenses/ffmpeg/LICENSE. Build resources:
https://www.gyan.dev/ffmpeg/builds/ . Executed as independent processes.

frei0r v3.7.1: GPL/compatible individual licenses, official Windows release;
SHA256 6c169ecddb8f70725a3e57694f0eb8284eaa20d7b710384711039e8a10ad6d23.
Original notices/headers in assets/frei0r. Exact upstream source archive in
third_party/frei0r-source-v3.7.1.tar.gz. https://github.com/dyne/frei0r/tree/v3.7.1

GL Transitions: original shaders, headers, MIT/BSD notices and LICENSE retained
in assets/gl-transitions. https://github.com/gl-transitions/gl-transitions
Real-ESRGAN NCNN: original Windows 20220424 executable/models, licenses in
assets/realesrgan. https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0
Whisper tiny multilingual: unmodified Systran CTranslate2 model files/card,
MIT notices alongside. https://huggingface.co/Systran/faster-whisper-tiny
OpenColorIO 2.6: BSD-3-Clause, https://github.com/AcademySoftwareFoundation/OpenColorIO .
Uses bundled studio ACES config to bake a bounded SDR LUT.
ModernGL/glcontext, Faster-Whisper/CTranslate2, NumPy, OpenCV, PySceneDetect,
PyAV, fontTools and transitive dependencies: original wheel metadata and license
files remain in runtime. BUILD_INPUTS.json records the exact wheel hashes.
Fonts: Google Fonts Noto Sans/Inter/Montserrat/Cormorant Garamond, original OFL
and source manifests in assets/fonts. SFX: 3 original procedural WAVs, CC0.
Installer: NSIS 3.11, https://nsis.sourceforge.io/ .

External user-provided engines: ComfyUI (GPL3), Qwen via Ollama (model-specific
terms), SAM 2, DeepFilterNet, Natron/OpenFX-Misc/Arena and MLT. They are not
bundled as running servers/hosts. Their model/code licenses apply separately.
ProPainter excluded due to non-commercial-only restriction. No proprietary
Sapphire/Dehancer/NeatVideo/RX plugins or commercial asset packs are redistributed.
The reference/pack_v4 files are user-supplied historical references, not executable
components or claims about this release.
