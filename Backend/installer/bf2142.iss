; Установщик Battlefield 2142: Project Remaster v17 для нашего сервера (Inno Setup 6).
; Собирается tools\build_release.py — он передаёт пути, адрес сервера и версию через /D.
;
; Что делает: копирует игру (уже с патчем Штаба), прописывает её в реестр (путь, язык, CD-ключ —
; как обычный установщик BF2142), делает BF2142_selfhost.exe с адресом сервера из мастера,
; выключает сглаживание в профилях и ставит ярлык «BF2142 Remaster» (запуск без PowerShell).
; Повторный запуск в ту же папку — смена адреса сервера (неизменённые файлы не перезаписываются).

#ifndef GameDir
  #define GameDir "C:\Games\BF2142 Remaster"
#endif
#ifndef OutDir
  #define OutDir "C:\Games\BF2142 Build"
#endif
#ifndef ServerAddress
  #define ServerAddress ""
#endif
#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#define GameArgs "+modPath mods/Project_Remaster_v17 +widescreen 1 +fullscreen 1"
#define RegKey "SOFTWARE\Electronic Arts\EA GAMES\Battlefield 2142"

[Setup]
AppId={{6B2C7E41-2142-4A7D-9E3B-5C0F21420017}
AppName=Battlefield 2142 Remaster
AppVersion={#AppVersion}
AppVerName=Battlefield 2142 Remaster {#AppVersion}
AppPublisher=Battlefield 2142 Remaster community
DefaultDirName=C:\Games\BF2142 Remaster
DefaultGroupName=Battlefield 2142 Remaster
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
OutputDir={#OutDir}
OutputBaseFilename=setup
SetupIconFile=bf2142.ico
UninstallDisplayIcon={app}\BF2142.exe
UninstallDisplayName=Battlefield 2142 Remaster
WizardStyle=modern
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage
PrivilegesRequired=admin
; Данные — 5+ ГБ: режем на части по 2 ГБ (setup-1.bin, setup-2.bin ...): файлообменники и FAT32 больше не берут.
DiskSpanning=yes
DiskSliceSize=2000000000
; Почти всё в игре — уже сжатые zip-архивы, их кладём как есть, остальное сжимаем.
Compression=lzma2/fast
SolidCompression=no
InfoBeforeFile=README.txt

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.LangTitle=Язык игры
ru.LangDesc=На каком языке будут меню и тексты игры?
ru.LangPrompt=Выбери язык (потом его можно поменять, запустив установку ещё раз):
ru.AddrTitle=Адрес сервера
ru.AddrDesc=Куда игра будет подключаться: вход, статистика, звания, список серверов.
ru.AddrPrompt=Впиши IP, который дал администратор сервера. Порт (через двоеточие) — только если его назвали.
ru.AddrLabel=Адрес (например 203.0.113.10):
ru.AddrBad=Неверный адрес. Нужен IPv4, например 203.0.113.10, или IPv4:порт.
ru.PatchFailed=Не удалось подготовить BF2142_selfhost.exe: %1%nИгра не сможет подключиться к серверу. Сообщи администратору.
ru.RunGame=Запустить Battlefield 2142 Remaster
ru.Readme=Памятка игроку
en.LangTitle=Game language
en.LangDesc=Which language should the game menus and texts use?
en.LangPrompt=Choose a language (you can change it later by running the setup again):
en.AddrTitle=Server address
en.AddrDesc=Where the game connects for login, stats, ranks and the server list.
en.AddrPrompt=Enter the IP given by the server admin. Add a port (after a colon) only if you were told to.
en.AddrLabel=Address (e.g. 203.0.113.10):
en.AddrBad=Invalid address. Use IPv4 like 203.0.113.10, or IPv4:port.
en.PatchFailed=Could not prepare BF2142_selfhost.exe: %1%nThe game will not be able to reach the server. Please tell the admin.
en.RunGame=Start Battlefield 2142 Remaster
en.Readme=Player notes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#GameDir}\*.zip"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs comparetimestamp nocompression
Source: "{#GameDir}\*"; DestDir: "{app}"; Excludes: "*.zip,BF2142_selfhost.exe,selfhost_kit.txt,launch_bf2142.ps1,gp.info,radial.cdb,*.log"; Flags: recursesubdirs createallsubdirs comparetimestamp
Source: "README.txt"; DestDir: "{app}"; DestName: "README_PLAYERS.txt"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "{#RegKey}"; Flags: uninsdeletekeyifempty
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Battlefield 2142"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "BuildNr"; ValueData: "1.10.77.0"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Version"; ValueData: "1.51"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "DisplayName"; ValueData: "Battlefield 2142"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "ProductName"; ValueData: "Battlefield 2142 Remaster"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "InstallDir"; ValueData: "{app}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Folder"; ValueData: "{app}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "CD Drive"; ValueData: "{app}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Installed From"; ValueData: "{app}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Product GUID"; ValueData: "{app}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Language"; ValueData: "{code:GameLanguage}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Locale"; ValueData: "{code:GameLocale}"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Suppression Exe"; ValueData: ""; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}"; ValueType: string; ValueName: "Registration"; ValueData: ""; Flags: uninsdeletevalue
Root: HKLM; Subkey: "{#RegKey}\1.0"; ValueType: string; ValueName: "DisplayName"; ValueData: "Battlefield 2142"; Flags: uninsdeletekey
Root: HKLM; Subkey: "{#RegKey}\1.0"; ValueType: dword; ValueName: "Language"; ValueData: "16"
Root: HKLM; Subkey: "{#RegKey}\1.0"; ValueType: string; ValueName: "LanguageName"; ValueData: "{code:GameLanguage}"
Root: HKLM; Subkey: "{#RegKey}\1.0"; ValueType: string; ValueName: "ProgramGroup"; ValueData: "{app}"
; CD-ключ: наш сервер его не проверяет, но игре он нужен в реестре. Свой ключ игрока не трогаем.
Root: HKLM; Subkey: "{#RegKey}\ergc"; ValueType: string; ValueName: ""; ValueData: "{code:CdKey}"; Flags: createvalueifdoesntexist uninsdeletekeyifempty

[Icons]
Name: "{autodesktop}\BF2142 Remaster"; Filename: "{app}\BF2142_selfhost.exe"; Parameters: "{#GameArgs}"; WorkingDir: "{app}"; IconFilename: "{app}\BF2142.exe"; Tasks: desktopicon
Name: "{group}\BF2142 Remaster"; Filename: "{app}\BF2142_selfhost.exe"; Parameters: "{#GameArgs}"; WorkingDir: "{app}"; IconFilename: "{app}\BF2142.exe"
Name: "{group}\{cm:Readme}"; Filename: "{app}\README_PLAYERS.txt"
Name: "{group}\{cm:UninstallProgram,Battlefield 2142 Remaster}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\BF2142_selfhost.exe"; Parameters: "{#GameArgs}"; WorkingDir: "{app}"; Description: "{cm:RunGame}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: files; Name: "{app}\BF2142_selfhost.exe"
Type: files; Name: "{app}\gp.info"
Type: files; Name: "{app}\radial.cdb"

[Code]
const
  SslCheckOffset = $45FE8D;   { снятая проверка SSL-сертификата: B8 15 00 00 00 }
  GpcmSlot = $607180;         { по этому слоту узнаём адрес, вшитый в исходный exe }
  DnsCheckOffset = $524824;   { проверка «есть ли интернет»: gethostbyname(<домен>) }
  DnsCheckHost = 'ea.com';

var
  LangPage: TInputOptionWizardPage;
  AddrPage: TInputQueryWizardPage;
  ServerIp: String;
  ServerPort: Integer;

{ --- мастер ------------------------------------------------------------------- }

procedure InitializeWizard;
var
  Saved: String;
begin
  LangPage := CreateInputOptionPage(wpSelectDir, CustomMessage('LangTitle'), CustomMessage('LangDesc'),
    CustomMessage('LangPrompt'), True, False);
  LangPage.Add('Русский');
  LangPage.Add('English');
  LangPage.Add('Deutsch');
  Saved := GetPreviousData('GameLanguage', '');
  if Saved <> '' then
    LangPage.SelectedValueIndex := StrToIntDef(Saved, 0)
  else if ActiveLanguage = 'ru' then
    LangPage.SelectedValueIndex := 0
  else
    LangPage.SelectedValueIndex := 1;

  AddrPage := CreateInputQueryPage(LangPage.ID, CustomMessage('AddrTitle'), CustomMessage('AddrDesc'),
    CustomMessage('AddrPrompt'));
  AddrPage.Add(CustomMessage('AddrLabel'), False);
  AddrPage.Values[0] := GetPreviousData('ServerAddress', '{#ServerAddress}');
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'GameLanguage', IntToStr(LangPage.SelectedValueIndex));
  SetPreviousData(PreviousDataKey, 'ServerAddress', AddrPage.Values[0]);
end;

{ IPv4 или IPv4:порт. }
function ParseAddress(S: String; var Ip: String; var Port: Integer): Boolean;
var
  I, Digits, Octets, Value, P: Integer;
  C: Char;
  HostPart: String;
begin
  Result := False;
  S := Trim(S);
  P := Pos(':', S);
  if P > 0 then begin
    HostPart := Copy(S, 1, P - 1);
    Port := StrToIntDef(Copy(S, P + 1, Length(S)), -1);
  end else begin
    HostPart := S;
    Port := 80;
  end;
  if (Port < 1) or (Port > 65535) then Exit;
  Octets := 0;
  Digits := 0;
  Value := 0;
  for I := 1 to Length(HostPart) + 1 do begin
    if I <= Length(HostPart) then C := HostPart[I] else C := '.';
    if (C >= '0') and (C <= '9') then begin
      Value := Value * 10 + Ord(C) - Ord('0');
      Digits := Digits + 1;
      if (Digits > 3) or (Value > 255) then Exit;
    end else if C = '.' then begin
      if Digits = 0 then Exit;
      Octets := Octets + 1;
      Digits := 0;
      Value := 0;
    end else
      Exit;
  end;
  if Octets <> 4 then Exit;
  Ip := HostPart;
  Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = AddrPage.ID then
    if not ParseAddress(AddrPage.Values[0], ServerIp, ServerPort) then begin
      MsgBox(CustomMessage('AddrBad'), mbError, MB_OK);
      Result := False;
    end;
end;

{ --- значения для [Registry] ---------------------------------------------------- }

function LangIndex: Integer;
var
  P: String;
begin
  P := Lowercase(ExpandConstant('{param:GAMELANG|}'));
  if P = 'ru' then Result := 0
  else if P = 'en' then Result := 1
  else if P = 'de' then Result := 2
  else Result := LangPage.SelectedValueIndex;
end;

function GameLanguage(Param: String): String;
begin
  case LangIndex of
    0: Result := 'Russian';
    2: Result := 'German';
  else
    Result := 'English';
  end;
end;

function GameLocale(Param: String): String;
begin
  case LangIndex of
    0: Result := 'ru';
    2: Result := 'de';
  else
    Result := 'en';
  end;
end;

function CdKey(Param: String): String;
var
  I: Integer;
  Chars: String;
begin
  Chars := 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  Result := '';
  for I := 1 to 25 do
    Result := Result + Chars[Random(Length(Chars)) + 1];
end;

{ --- BF2142_selfhost.exe: копия BF2142.exe с адресом сервера ------------------------- }
{ То же, что Backend\tools\patch_client.py. Offset — смещение в файле (с нуля). }

function ReadCStr(const Data: AnsiString; Off: Integer): String;
var
  I: Integer;
begin
  Result := '';
  I := Off + 1;
  while (I <= Length(Data)) and (Data[I] <> #0) do begin
    Result := Result + Chr(Ord(Data[I]));
    I := I + 1;
  end;
end;

{ Все склейки — только AnsiString с AnsiString: смесь с обычной (Unicode) строкой перекодировала бы
  весь exe через кодовую страницу и испортила байты >= $80. Text — только ASCII. }
procedure WriteCStr(var Data: AnsiString; Off: Integer; Text: String; Limit: Integer);
var
  Piece, Zero: AnsiString;
begin
  Piece := Text;
  Zero := #0;
  while Length(Piece) < Limit + 1 do
    Piece := Piece + Zero;
  Data := Copy(Data, 1, Off) + Piece + Copy(Data, Off + Limit + 2, Length(Data));
end;

function PatchSlot(var Data: AnsiString; Off, Cap: Integer; OldHost, HostPort: String): String;
var
  Old, NewStr: String;
  Limit, EndPos: Integer;
begin
  Result := '';
  Old := ReadCStr(Data, Off);
  if Pos(OldHost, Old) = 0 then begin
    Result := Format('slot %x', [Off]);
    Exit;
  end;
  NewStr := Old;
  if Pos('http://', Old) = 1 then
    StringChangeEx(NewStr, OldHost, HostPort, True)
  else
    StringChangeEx(NewStr, OldHost, ServerIp, True);
  EndPos := Off + Length(Old);
  while Data[EndPos + 1] = #0 do
    EndPos := EndPos + 1;
  Limit := Length(Old);
  if Cap > Limit then Limit := Cap;
  if EndPos - Off - 1 < Limit then Limit := EndPos - Off - 1;
  if Length(NewStr) > Limit then begin  { новости без порта — не критично }
    NewStr := Old;
    StringChangeEx(NewStr, OldHost, ServerIp, True);
  end;
  if Length(NewStr) > Limit then begin
    Result := Format('slot %x too small', [Off]);
    Exit;
  end;
  WriteCStr(Data, Off, NewStr, Limit);
end;

function PatchExe: String;
var
  Data: AnsiString;
  OldHost, HostPort, Dns, Err, Address: String;
  PeOff, Flags: Integer;
  FlagByte: AnsiString;
begin
  Result := '';
  Address := ExpandConstant('{param:ADDRESS|}');  { тихая установка: /ADDRESS=1.2.3.4 }
  if Address = '' then Address := AddrPage.Values[0];
  if not ParseAddress(Address, ServerIp, ServerPort) then begin
    Result := 'address "' + Address + '"';
    Exit;
  end;
  if not LoadStringFromFile(ExpandConstant('{app}\BF2142.exe'), Data) then begin
    Result := 'BF2142.exe';
    Exit;
  end;
  if (Ord(Data[SslCheckOffset + 1]) <> $B8) or (Ord(Data[SslCheckOffset + 2]) <> $15) then begin
    Result := 'unexpected BF2142.exe';
    Exit;
  end;
  OldHost := ReadCStr(Data, GpcmSlot);
  if (OldHost = '') or (Pos('%', OldHost) > 0) then begin
    Result := 'unexpected GPCM slot';
    Exit;
  end;
  if ServerPort = 80 then HostPort := ServerIp else HostPort := ServerIp + ':' + IntToStr(ServerPort);
  { смещение -> сколько символов можно писать (как SLOTS в patch_client.py) }
  Err := PatchSlot(Data, $5639A4, 31, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $5639C4, 23, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $563CC4, 0, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $59E6E8, 24, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $59E938, 37, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $59F608, 19, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $6067A0, 63, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $607180, 63, OldHost, HostPort);
  if Err = '' then Err := PatchSlot(Data, $6071C0, 63, OldHost, HostPort);
  if Err <> '' then begin
    Result := Err;
    Exit;
  end;
  { домен сборки в проверке интернета -> ea.com }
  Dns := ReadCStr(Data, DnsCheckOffset);
  if Dns <> DnsCheckHost then begin
    if (Length(Dns) < Length(DnsCheckHost)) or (Pos(Dns, OldHost) = 0) then begin
      Result := 'unexpected DNS check';
      Exit;
    end;
    WriteCStr(Data, DnsCheckOffset, DnsCheckHost, Length(Dns));
  end;
  { Large Address Aware: без него Remaster не помещается в 2 ГБ памяти }
  PeOff := Ord(Data[$3C + 1]) + Ord(Data[$3D + 1]) * 256 + Ord(Data[$3E + 1]) * 65536;
  Flags := Ord(Data[PeOff + 22 + 1]);
  if (Flags and $20) = 0 then begin
    Flags := Flags or $20;
    if Flags >= $80 then begin
      Result := 'PE flags';
      Exit;
    end;
    FlagByte := Chr(Flags);
    Data := Copy(Data, 1, PeOff + 22) + FlagByte + Copy(Data, PeOff + 24, Length(Data));
  end;
  if not SaveStringToFile(ExpandConstant('{app}\BF2142_selfhost.exe'), Data, False) then
    Result := 'BF2142_selfhost.exe (game running?)';
end;

{ --- сглаживание: с ним Remaster показывает чёрный мир ------------------------------- }

procedure DisableAntialiasing;
var
  Rec: TFindRec;
  Root, FileName: String;
  Lines: TArrayOfString;
  I: Integer;
  Changed: Boolean;
begin
  Root := ExpandConstant('{userdocs}\Battlefield 2142\Profiles\');
  if FindFirst(Root + '*', Rec) then begin
    try
      repeat
        FileName := Root + Rec.Name + '\Video.con';
        if (Rec.Name <> '.') and (Rec.Name <> '..') and FileExists(FileName) and
           LoadStringsFromFile(FileName, Lines) then begin
          Changed := False;
          for I := 0 to GetArrayLength(Lines) - 1 do
            if (Pos('VideoSettings.setAntialiasing', Lines[I]) = 1) and
               (Lines[I] <> 'VideoSettings.setAntialiasing Off') then begin
              Lines[I] := 'VideoSettings.setAntialiasing Off';
              Changed := True;
            end;
          if Changed then SaveStringsToFile(FileName, Lines, False);
        end;
      until not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Err: String;
begin
  if CurStep = ssPostInstall then begin
    Err := PatchExe;
    if Err <> '' then
      MsgBox(FmtMessage(CustomMessage('PatchFailed'), [Err]), mbError, MB_OK);
    DisableAntialiasing;
  end;
end;
