; Inno Setup script for YT Downloader.
; Compile with:  iscc packaging\installer.iss
; (Install Inno Setup 6: https://jrsoftware.org/isdl.php)
;
; Produces packaging\dist_installer\YT-Downloader-Setup.exe — a single setup
; .exe that installs the bundled app (Python runtime, PyQt6, yt-dlp, and any
; vendored ffmpeg/aria2c) with Start-menu and optional desktop shortcuts.

#define AppName "YT Downloader"
#define AppVersion "2.1.0"
#define AppPublisher "YT Downloader"
#define AppExe "YT Downloader.exe"

[Setup]
AppId={{B7B6A2E4-2F4C-4C3E-9C1A-7D2E4F8A9B01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=YT-Downloader-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The whole PyInstaller onedir output. Run build.ps1 first to produce it.
Source: "..\dist\YT Downloader\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
