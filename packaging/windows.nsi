Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
Name "KADRGO Studio 6 AI Alpha"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\KADRGO Studio 6 Alpha"
RequestExecutionLevel user
SetCompressor /SOLID zlib
Icon "${PAYLOAD}/KADRGO.ico"
BrandingText "KADRGO Studio | AI Integration Alpha"
VIProductVersion "6.0.2.0"
VIAddVersionKey "ProductName" "KADRGO Studio"
VIAddVersionKey "FileDescription" "KADRGO Studio 6 Windows x64 Alpha Setup"
VIAddVersionKey "FileVersion" "6.0.2.0"
VIAddVersionKey "LegalCopyright" "KADRGO Studio contributors"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "KADRGO Studio 6 AI Alpha"
!define MUI_WELCOMEPAGE_TEXT "Windows 10/11 x64. Python, Qt, FFmpeg and core AI libraries included.$\r$\n$\r$\nUnsigned alpha. See native Windows validation results for this build. Optional engines require local services or compatible environments. Read BOSHLASH.txt."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\BOSHLASH.txt"
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Function .onInit
 ${IfNot} ${RunningX64}
 MessageBox MB_ICONSTOP "64-bit Windows kerak."
 Abort
 ${EndIf}
 ${IfNot} ${AtLeastWin10}
 MessageBox MB_ICONSTOP "Windows 10/11 kerak."
 Abort
 ${EndIf}
FunctionEnd
Section
 SetShellVarContext current
 SetOutPath "$INSTDIR"
 !ifdef WINDOWS_BUILD
 File /r "${PAYLOAD}\*"
 !else
 File /r "${PAYLOAD}/*"
 !endif
 WriteUninstaller "$INSTDIR\Uninstall.exe"
 CreateDirectory "$SMPROGRAMS\KADRGO Studio 6"
 CreateShortcut "$SMPROGRAMS\KADRGO Studio 6\KADRGO Studio 6.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\bootstrap.py$\"' "$INSTDIR\KADRGO.ico"
 CreateShortcut "$DESKTOP\KADRGO Studio 6.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\bootstrap.py$\"' "$INSTDIR\KADRGO.ico"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KADRGOStudio6Alpha" "DisplayName" "KADRGO Studio 6 AI Alpha"
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KADRGOStudio6Alpha" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
 WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KADRGOStudio6Alpha" "DisplayVersion" "6.0.2"
SectionEnd
Section "Uninstall"
 SetShellVarContext current
 Delete "$DESKTOP\KADRGO Studio 6.lnk"
 Delete "$SMPROGRAMS\KADRGO Studio 6\KADRGO Studio 6.lnk"
 RMDir "$SMPROGRAMS\KADRGO Studio 6"
 RMDir /r "$INSTDIR\runtime"
 RMDir /r "$INSTDIR\kadrgo"
 RMDir /r "$INSTDIR\assets"
 RMDir /r "$INSTDIR\third_party"
 RMDir /r "$INSTDIR\bin"
 RMDir /r "$INSTDIR\licenses"
 Delete "$INSTDIR\bootstrap.py"
 Delete "$INSTDIR\engine_worker.py"
 Delete "$INSTDIR\README_UZ.md"
 Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
 Delete "$INSTDIR\BOSHLASH.txt"
 Delete "$INSTDIR\KADRGO.ico"
 Delete "$INSTDIR\BUILD_INPUTS.json"
 Delete "$INSTDIR\Uninstall.exe"
 RMDir "$INSTDIR"
 DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\KADRGOStudio6Alpha"
SectionEnd
