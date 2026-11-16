# KADRGO Studio 6.0.1 alpha sinovlari

23/23 original montaj testi o'tdi: real FFmpeg render, preview/eksport rang,
Unicode, audio sinxron, 24 look, 58 o'tish, retush sintetik piksel, undo/fuzz,
backup, bekor qilish va boshqa sinovlar. Rang matritsasi tuzatildi, test
chegarasi oshirilmadi. Original media ustiga eksport bloklandi, staging natija
verifikatsiyadan keyin atomik almashtiriladi.

8/8 yangi test o'tdi: real OCIO LUT+media, real sahna detection, GL video,
loopback endpoint cheklovi, ComfyUI protocol mock, Qwen protocol/mock va vaqt
validatsiyasi, real Whisper tiny silence smoke, original media himoyasi.
Qwen/Comfy mock sinovi haqiqiy model yoki server inference sinovi emas.
O'zbekcha nutq aniqligi real materialda o'lchanmagan.

Qt: 12 engine paneli ochildi. Subtitr source trim/speed bo'yicha asosiy
historyga yozilishi va undo tekshirildi. Oyna yopilgach tugayotgan fon ishining
signaliga guard qo'shildi va tekshirildi.

GL_COMPILE.json faqat Linux EGL shader compile natijalari; Windows yoki
barcha visual effekt sifatini tasdiqlamaydi. Real-ESRGAN Vulkan/Windows,
frei0r Windows DLL, SAM/DeepFilterNet model inference sinalmagan.

Paketdagi vositalar: Whisper tiny, OCIO/ACES config, PySceneDetect, GL shaderlar,
frei0r DLL va FILTER host, Real-ESRGAN NCNN va modellar. Optional servislar:
Qwen/Ollama, ComfyUI; alohida Python talab qiluvchilar: SAM/DeepFilterNet.
OFX/Natron va MLT tashqi loyiha ko'priklari; ichki host/dvijok emas.
ProPainter non-commercial sharti sabab qo'shilmadi.

Haqiqiy Windows installer, playback, GPU, GL/Vulkan va uninstall sinovi hali
bajarilmagan. Python/Qt/FFmpeg/AI kutubxonalari official Windows wheel va
runtime'dan yig'ilgan. Paket unsigned alpha, yakuniy mahsulot emas.

## Birinchi native Windows CI (2026-11-16)

GitHub Actions Windows Server 2022, Python 3.11.9, FFmpeg 9.0.2:
22/23 montaj testi o'tdi. squeezev FFmpeg jarayonida 0xC0000005 bilan
quladi. Xfade zanjiri oldidan full-resolution yuv444p format majburiy qilindi;
4:2:0 chroma bilan to'g'ridan-to'g'ri ishlashdan keladigan muammo oldi olindi. Paketdagi
FFmpeg topish yo'li ham tuzatildi. Keyingi CI natijasi alohida tekshiriladi.

## 6.0.2 native Windows yangilanishi

24/24 montaj testi va 7/7 CPU integratsiya testi native Windows Server 2022,
CPython 3.11.9, FFmpeg 9.0.2 da o‘tdi. Qt oynasi ochilib-yopildi. Baza
resurslarini sinov egasi yopishi va oyna timerlari to‘xtashi tuzatildi.
Squeeze custom sampler + yuv444p bilan geometriya/piksel tekshiruvidan o‘tdi.
Backup nomlari eksklyuziv yaratiladi; clock bir xil vaqtni qaytarsa ham
versiyalar ustiga yozilmaydi. Autosave timestamp teng bo‘lsa mazmun bilan
solishtiriladi. Worker UTF-8 log va sozlama o‘qishi tuzatildi; yangi legacy
console testi qo‘shildi (CPU to‘plam endi 8 test).
Installer Windows native CI ichida yig‘iladi va silent install, private runtime
FFmpeg/Qt smoke, uninstall user-data preservation tekshiruvidan o‘tgandan
keyingina artifact sifatida chiqariladi. GPU/GL/Vulkan va to‘liq semantik AI
inference hali bu tekshiruv qamrovida emas.
