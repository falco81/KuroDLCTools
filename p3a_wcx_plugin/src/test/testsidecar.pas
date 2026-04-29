program testsidecar;
{$mode objfpc}{$H+}

// Simulates the sidecar logic that the WCX plugin uses for tracking
// "F7-created" empty folders. The sidecar lives next to the archive
// as <archive>.empty_dirs (plain text, one folder per line, lowercase
// forward-slashed paths).

uses SysUtils, Classes;

const SidecarSuffix = '.empty_dirs';

function NormalizeFolder(const S: AnsiString): AnsiString;
var i: Integer;
begin
  Result := LowerCase(Trim(S));
  for i := 1 to Length(Result) do
    if Result[i] = '\' then Result[i] := '/';
  while (Result <> '') and (Result[Length(Result)] = '/') do
    SetLength(Result, Length(Result) - 1);
end;

procedure SidecarAdd(var Dirs: TStringArray; const Path: AnsiString);
var i: Integer; N: AnsiString;
begin
  N := NormalizeFolder(Path);
  if N = '' then Exit;
  for i := 0 to High(Dirs) do
    if Dirs[i] = N then Exit;
  SetLength(Dirs, Length(Dirs) + 1);
  Dirs[High(Dirs)] := N;
end;

procedure SidecarRemoveExact(var Dirs: TStringArray; const Path: AnsiString);
var i: Integer; N: AnsiString;
begin
  N := NormalizeFolder(Path);
  for i := 0 to High(Dirs) do
    if Dirs[i] = N then
    begin
      Dirs[i] := Dirs[High(Dirs)];
      SetLength(Dirs, Length(Dirs) - 1);
      Exit;
    end;
end;

procedure SidecarRemoveAncestors(var Dirs: TStringArray; const FilePath: AnsiString);
var P: AnsiString; j: Integer;
begin
  P := NormalizeFolder(FilePath);
  while True do
  begin
    j := -1;
    for j := Length(P) downto 1 do
      if P[j] = '/' then Break;
    if j < 1 then Exit;
    P := Copy(P, 1, j - 1);
    if P = '' then Exit;
    SidecarRemoveExact(Dirs, P);
  end;
end;

procedure DumpDirs(const Title: AnsiString; const D: TStringArray);
var i: Integer;
begin
  Write('  ', Title, ': [');
  for i := 0 to High(D) do
  begin
    if i > 0 then Write(', ');
    Write('"', D[i], '"');
  end;
  WriteLn(']');
end;

var
  Dirs: TStringArray;
begin
  Dirs := nil;

  WriteLn('Test 1: F7 creates empty folders in sidecar');
  SidecarAdd(Dirs, 'asset\newfolder');
  SidecarAdd(Dirs, 'asset\foo\bar');
  SidecarAdd(Dirs, 'asset\newfolder');  // duplicate, should be ignored
  DumpDirs('after F7 x3', Dirs);
  if Length(Dirs) = 2 then WriteLn('  OK: dedup works')
  else                     WriteLn('  FAIL: expected 2 entries, got ', Length(Dirs));

  WriteLn;
  WriteLn('Test 2: Adding a file to an empty folder removes it from sidecar');
  SidecarRemoveAncestors(Dirs, 'asset\newfolder\file.txt');
  DumpDirs('after add file', Dirs);
  if Length(Dirs) = 1 then WriteLn('  OK: asset/newfolder removed (file added there)')
  else                     WriteLn('  FAIL: expected 1 entry, got ', Length(Dirs));

  WriteLn;
  WriteLn('Test 3: Adding a deeply-nested file cleans up all ancestor markers');
  SidecarAdd(Dirs, 'asset');
  SidecarAdd(Dirs, 'asset\foo');
  DumpDirs('before add deep file', Dirs);
  SidecarRemoveAncestors(Dirs, 'asset\foo\bar\baz.txt');
  DumpDirs('after add deep file', Dirs);
  // Should remove asset, asset/foo, asset/foo/bar (last not present anyway)
  if Length(Dirs) = 0 then WriteLn('  OK: all ancestors cleaned')
  else                     WriteLn('  FAIL: ', Length(Dirs), ' leftover');
end.
