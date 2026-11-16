# KADRGO Studio v0.1 (texnik prototip, Mac + Windows)

AI va professional montaj dasturi. **Hammasi kompyuteringizda ishlaydi**: loyiha, baza, kesh, AI tahlil.
Internet faqat o'rnatishda (kutubxonalar) kerak.

## 1. O'rnatish

**Windows 10/11:** papkani oching va `install_windows.bat` ni ikki marta bosing.
U Python va FFmpeg ni tekshiradi (yo'q bo'lsa o'zi yuklaydi), kutubxonalarni o'rnatadi, Desktop ga
"KADRGO Studio" yorlig'ini qo'yadi va haqiqiy o'z-o'zini tekshirishni ishga tushiradi.
Keyin Desktop dagi yorliqni yoki `run_kadrgo.bat` ni bosing.

**macOS:** Terminalda `./install_mac.command` (Homebrew kerak: https://brew.sh). Keyin Desktop dagi
`KADRGO Studio.command`.

**Linux:** `./install_linux.sh`.

Buyruq satri: `python -m kadrgo info | scan | library | export | selfcheck`

## 2. O'zingiz yig'adigan baza (Vault)

Dastur papka yaratadi (Windows: `D:\KadrgoStudio_Vault`, D: bo'lmasa `C:\Users\siz\KadrgoStudio_Vault`;
Mac: `~/Library/Application Support/KadrgoStudio`). Fayllaringizni shu yerga tashlang:

| Papka | Nima | Dastur nima qiladi |
|---|---|---|
| `Library\SFX`, `Library\Music` | wav, mp3, flac... | davomiylik, sample rate, bit chuqurligi tekshiriladi; qidiruv; bir bosishda timeline ga |
| `Library\Fonts` | ttf, otf | O', G', ʻ, kirill (Ў Ғ Қ Ҳ) va turkcha harflar qamrovi HAQIQATAN tekshiriladi; litsenziya matni o'qiladi |
| `Library\LUT` | .cube | tuzilishi tekshiriladi; klipga bir bosishda |
| `Library\Plugins` | OpenFX / VST3 / AU | topiladi va ro'yxatlanadi (pastdagi cheklovga qarang) |

Dastur: **Kutubxona > Skanerlash** (yoki `python -m kadrgo scan`). Natija `KadrgoVault.kadrdb` (SQLite) ga yoziladi.
Har yozuvda holat: `ok` / `qisman` / `xato` va sababi. Buzilgan fayl hech qachon "ok" deb belgilanmaydi.

Litsenziya: faqat huquqingiz bor fayllarni qo'ying. Pullik plaginlar, Envato/Artlist/Motion Array assetlari
dasturga qo'shilmagan va qayta tarqatilmaydi.

## 3. Hozir ISHLAYDIGAN narsalar (sinovdan o'tgan)

- Timeline: V1/V2 video, A1 dialog, A2 musiqa, A3 SFX. Siljitish, chetidan qirqish, bo'lish, ripple o'chirish,
  snap, marker, zoom, qulflash/mute, to'lqin shakli. Cheksiz undo/redo (Ctrl+Z / Ctrl+Y).
- 58 ta perexod (xfade: fade, slide, wipe, circle, pixelize, radial, zoom va boshqalar), ovozi ham kesishadi.
- Effektlar: rang sozlash, egri chiziq, 24 original look (Clean/Wedding/Drama/Music), LUT, kamera profili
  S-Log3 -> Rec.709 (Sony A7 III), glow, halation, film grain, vinyetka, kino chiziqlari, o'tkirlik,
  shovqin kamaytirish, xiralik, xromatik siljish, kamera titrashi, zoom/Ken Burns.
- **Retush:** chastota ajratish + dog'/husnbuzar tuzatish, yuz kuzatuvi, teksturani saqlash o'lchovi
  va ogohlantirish. Generativ emas: yuz shakli o'zgarmaydi.
- Subtitr: qo'lda, SRT import/eksport, videoga yozish (O', G', kirill saqlanadi), shriftni kutubxonadan tanlash.
- Ovoz: musiqa dialog ostida avtomatik pasayadi (ducking), limiter, Reels uchun -14 LUFS.
- AI (lokal): sukunatni kesish (jump-cut), beat/BPM markerlar, AI reja (JSON) tekshiruvi va qo'llash
  (bitta Ctrl+Z bilan qaytadi), ixtiyoriy faster-whisper transkripsiyasi.
- Eksport: H.264/HEVC (NVENC/QuickSync/AMF/VideoToolbox avtomatik), ProRes 422 HQ, bo'lak-bo'lak render,
  bekor qilish, yakuniy dekod tekshiruvi. Autosave 30 s, buzilgan fayldan oxirgi versiyaga tiklanish,
  SHA-256 checksumli loyiha jurnali.

Sinov: `python tests/test_engine.py` (23 ta test: piksel tekshiruvi, preview=eksport, fuzz, undo, retush...).

## 4. Hozircha YO'Q yoki cheklangan (halol ro'yxat)

- **Plagin ijrosi yo'q.** Sapphire, Neat Video, iZotope RX va boshqalar topiladi/ro'yxatlanadi, lekin ishga
  tushirilmaydi: OpenFX/VST3 host bu versiyada yo'q (alohida C++ modul kerak).
- Preview "render asosida": playhead bo'yicha kadr va 10 soniyalik qisqa ijro tayyorlanadi, real-time
  uzluksiz ijro emas. Bu i3-10100 uchun ataylab tanlangan yo'l; tezlik sizning kompyuteringizda o'lchanmagan.
- Effektlar FFmpeg filtrlari (CPU). GPU faqat kodlashda (NVENC) ishlatiladi. 4K, og'ir retush sekin bo'ladi.
- Multicam sinxron, to'y/klip avtomatik montaj, referens tahlili, generativ video yo'q (rejada).
- Mac va Windows o'rnatgichlari yozilgan, lekin men ularni faqat Linux da sinab ko'rdim.
- Retush Haar detektori bilan: yon tomondan/kichik yuzlar topilmasligi mumkin; natijani doim ko'zdan kechiring.

## 5. Tezkor tugmalar

Space ijro | S bo'lish | Delete o'chirish | Shift+Delete ripple | M marker | Chap/O'ng kadr (Shift = 10)
Ctrl+Z / Ctrl+Y undo/redo | Ctrl+S saqlash | Ctrl+I import | Ctrl+E eksport | Ctrl+g'ildirak zoom

## 6. Yuklangan "v4 Pack" haqida

`reference/pack_v4/` da asl fayllar saqlangan. Ulardan g'oyalar olindi (vault papkasi, plagin yo'llari,
checksumli jurnal, S-Log3 formulasi). Lekin pakdagi quyidagilar tasdiqlanmagan va olinmadi:
"30 kunlik sinov" (u aslida 1000 ta tez saqlash sikli), "100% yuz saqlanishi" (kod doim 100 yozadi, o'lchamaydi),
"96 kHz SFX / 32-bit ACES to'plam" (faqat jadval yozuvlari, fayllar yo'q), plagin versiyalari (2026.5, v6, RX 12
- tasdiqlanmagan), `.html` esa ishlaydigan dastur emas, dizayn maketi. C++ fayl esa tugallanmagan eskiz.
Dasturning haqiqiy sinovi: `python -m kadrgo selfcheck` va `tests/`.
