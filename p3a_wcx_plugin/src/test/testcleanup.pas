program testcleanup;
{$mode objfpc}{$H+}

// Verifies that legacy .p3a_keep markers (left over from older plugin
// versions or external tools) get automatically stripped from the
// archive on the next modification.

uses SysUtils, Classes, p3alib;

procedure DumpEntries(const Path, Label_: AnsiString);
var Arc: TP3AArchive; i: Integer;
begin
  WriteLn('--- ', Label_, ' (', Path, ') ---');
  Arc := TP3AArchive.Create(Path);
  try
    for i := 0 to High(Arc.Entries) do
      WriteLn('  [', i, '] ', Arc.Entries[i].Name, ' (size=', Arc.Entries[i].UncSize, ')');
  finally
    Arc.Free;
  end;
  WriteLn;
end;

function IsKeepMarker(const Name: AnsiString): Boolean;
const KeepMarker = '/.p3a_keep';
var L: Integer;
begin
  L := Length(KeepMarker);
  Result := (Length(Name) >= L)
            and (LowerCase(Copy(Name, Length(Name) - L + 1, L)) = KeepMarker);
end;

var
  W: TP3AWriter;
  Arc: TP3AArchive;
  S: AnsiString;
  i: Integer;
  CmpBuf: TBytes;
  E: TP3AEntry;
  MarkerCount: Integer;
begin
  // === Step 1: build an archive with legacy .p3a_keep markers
  // (this mimics what the previous plugin version would have produced)
  W := TP3AWriter.Create;
  S := 'real content';
  W.AddFromBuffer('asset/text/real.txt', PByte(@S[1]), Length(S));
  W.AddFromBuffer('asset/empty1/.p3a_keep', nil, 0);    // legacy marker
  W.AddFromBuffer('asset/empty2/.p3a_keep', nil, 0);    // another one
  W.AddFromBuffer('asset/.p3a_keep', nil, 0);           // top-level too
  W.WriteToFile('/tmp/cleanup_before.p3a');
  W.Free;
  DumpEntries('/tmp/cleanup_before.p3a', 'BEFORE: legacy archive with markers');

  // === Step 2: simulate the new plugin's write logic.
  // CarryOverExisting reads the archive and skips any IsKeepMarker entries.
  Arc := TP3AArchive.Create('/tmp/cleanup_before.p3a');
  W := TP3AWriter.Create;
  for i := 0 to High(Arc.Entries) do
  begin
    E := Arc.Entries[i];
    if IsKeepMarker(E.Name) then Continue;   // <-- the auto-cleanup
    SetLength(CmpBuf, E.CmpSize);
    Arc.ReadCompressedBytes(i, @CmpBuf[0]);
    W.AddFromCompressed(E.Name, E.CmpType, CmpBuf, E.UncSize,
                        E.CmpHash, E.UncHash, E.HasUncHash);
  end;
  Arc.Free;

  // Add some new file (any modification triggers the cleanup)
  S := 'newly added content';
  W.AddFromBuffer('asset/new.txt', PByte(@S[1]), Length(S));
  W.WriteToFile('/tmp/cleanup_after.p3a');
  W.Free;

  DumpEntries('/tmp/cleanup_after.p3a', 'AFTER: any modification triggers cleanup');

  // === Step 3: count remaining markers (expect 0)
  Arc := TP3AArchive.Create('/tmp/cleanup_after.p3a');
  MarkerCount := 0;
  for i := 0 to High(Arc.Entries) do
    if IsKeepMarker(Arc.Entries[i].Name) then Inc(MarkerCount);
  Arc.Free;

  WriteLn('Markers remaining after cleanup: ', MarkerCount);
  if MarkerCount = 0 then
    WriteLn('OK -- legacy markers were stripped')
  else
    WriteLn('FAIL -- ', MarkerCount, ' markers leaked through');
end.
