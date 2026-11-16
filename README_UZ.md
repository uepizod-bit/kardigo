# KADRGO Studio 6.0.2 — AI Integration Alpha

Foydalanuvchi yuborgan v0.1 ZIP asosida. Bu dastlabki integratsiya alpha, yakuniy
professional mahsulot emas. Montaj yadrosi (24 test), CPU integratsiyalari va Qt oyna lifecycle sinovi Windows Server 2022 da bajarildi. Installer faqat successful CI natijasidan olinadi. GPU va amaliy ish jarayoni alohida tekshiriladi.

Windows: Setup.exe -> Install -> ish stolidagi KADRGO Studio 6.
To'liq amaliy yo'riqnoma: packaging/BOSHLASH.txt (installer ichida BOSHLASH.txt).

Asosiy yadro: ko'p yo'lakli taymlayn, 24 look, 58 xfade, kino effektlari, SRT,
klassik retush, audio ducking/limiter, lokal SQLite kutubxona, backup/undo.
AI / Rang markazida 12 vosita: Whisper tiny, PySceneDetect, OCIO/ACES, GL,
frei0r, Real-ESRGAN; optional Qwen/Ollama, ComfyUI, SAM, DeepFilterNet;
tashqi Natron/OFX va melt/MLT loyiha ko'priklari.

Optional servis/modelga ehtiyoj dastur oynasida va BOSHLASH.txt da yozilgan.
SAM maska PNG chiqaradi, avtomatik compositing yo'q. OFX/MLT ichki host emas.
Whisper tiny bor, o'zbekcha real nutq aniqligi o'lchanmagan. Real-ESRGAN Vulkan
GPU talab qiladi; generativ face enhancement yo'q, yuz bilan solishtiring.

5.1 loyiha formati boshqa, avtomatik migratsiya yo'q; v0.1 mos. Oldingi
fayllarni saqlang. Ushbu dastur 6 uchun alohida papkaga o'rnatiladi.

Manbadan: Python 3.11, FFmpeg/ffprobe, pip install -r requirements-windows.txt;
python -m kadrgo. Optional SAM/DeepFilterNet uchun mos alohida Python muhitini
AI markazida ko'rsating. Qwen va ComfyUI faqat localhost HTTP orqali ulanadi.

Sinov: python tests/test_engine.py va python tests/test_integrations.py.
Windows build: packaging/assemble.py + packaging/windows.nsi. Rasmiy Win64
wheel/embedded runtime yig'iladi; bu native Windows testini almashtirmaydi.
