; Inno Setup Script for Digital Downloader
; Generates DigitalDownloader-Setup.exe installer

#define MyAppName "Digital Downloader"
#define MyAppVersion "2.1.0"
#define MyAppPublisher "Digital Takhleeq"
#define MyAppURL "https://github.com/HaronKhalid/Digital-Downloader"
#define MyAppExeName "DigitalDownloader.exe"

[Setup]
AppId={{5E3B8F20-80E2-4D9D-9F31-92D1F3507B92}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=DigitalDownloader-Setup
SetupIconFile=Assets\app_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
VersionInfoVersion=2.1.0.0
VersionInfoCompany=Digital Takhleeq
VersionInfoDescription=Digital Downloader Standalone App
VersionInfoCopyright=Copyright (C) 2026 Digital Takhleeq
VersionInfoProductName=Digital Downloader
VersionInfoProductVersion=2.1.0.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\DigitalDownloader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "extension\*"; DestDir: "{app}\extension"; Excludes: "test.mjs,*.md"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
