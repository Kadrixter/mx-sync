; Instalator MX Sync (Inno Setup 6). Uwaga: libtorrent wymaga Pythona 3.12 przy budowaniu.
; Budowanie: najpierw PyInstaller --onedir (dist\MXSync\), potem:
;   ISCC.exe /DAppVersion=1.3.0 installer\MXSync.iss   ->  dist\installer\MXSync-Setup-1.3.0.exe
;
; Instaluje do Program Files (wymaga administratora), dodaje reguły zapory dla MXSync.exe
; (bez pytania Windowsa przy pierwszym uruchomieniu), skrót w menu Start i opcjonalnie na pulpicie.
; Aktualizacja = uruchomienie nowszego instalatora (aplikacja robi to sama z /SILENT) –
; instalator zamyka działający MX Sync, podmienia pliki i uruchamia go ponownie.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "MX Sync"
#define AppExe "MXSync.exe"
#define FwRule "MX Sync"

[Setup]
; AppId nie może się zmieniać – po nim instalator rozpoznaje poprzednią instalację
AppId={{6E4B2C1D-8F3A-4D5E-9B7C-2A1F0E9D8C7B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Kadrixter
AppPublisherURL=https://github.com/Kadrixter/mx-sync
AppSupportURL=https://github.com/Kadrixter/mx-sync/issues
AppUpdatesURL=https://github.com/Kadrixter/mx-sync/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} - instalator
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
PrivilegesRequired=admin
; /CURRENTUSER z linii poleceń – instalacja bez admina (do testów; zapora wtedy nieustawiona)
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=MXSync-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=force
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; przy aktualizacji usuń stare biblioteki – nowa wersja może mieć inny zestaw plików
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\MXSync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; zapora: najpierw usuń starą regułę (po aktualizacji), potem dodaj dla wszystkich profili –
; sieć Radmin VPN Windows zwykle traktuje jako publiczną
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FwRule}"""; \
  Flags: runhidden; Check: IsAdminInstallMode; StatusMsg: "Konfiguruję zaporę Windows…"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FwRule}"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=any"; \
  Flags: runhidden; Check: IsAdminInstallMode; StatusMsg: "Konfiguruję zaporę Windows…"
; uruchom po instalacji (przy aktualizacji z aplikacji – /SILENT – też, bez pytania)
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall runasoriginaluser

[Registry]
; autostart ustawiany w programie (Ustawienia) – przy odinstalowaniu usuwamy wpis
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "MX Sync"; Flags: uninsdeletevalue

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FwRule}"""; \
  Flags: runhidden; RunOnceId: "DelFirewallRule"; Check: IsAdminInstallMode
