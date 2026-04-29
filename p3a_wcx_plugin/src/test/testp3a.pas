program testp3a;
{$mode objfpc}{$H+}
uses SysUtils, Math, p3alib, xxhash64;

var
  Arc: TP3AArchive;
  i, OkCount, ExtractCount: Integer;
  Buf: PByte;
  ComputedHash: QWord;
begin
  if ParamCount < 1 then begin WriteLn('usage: testp3a <file.p3a>'); Halt(1); end;

  Arc := TP3AArchive.Create(ParamStr(1));
  try
    WriteLn('P3A version  : ', Arc.Version);
    WriteLn('flags        : ', Arc.Flags);
    WriteLn('file count   : ', Length(Arc.Entries));
    WriteLn('--- first 5 entries ---');
    for i := 0 to Min(4, High(Arc.Entries)) do
      WriteLn('  [', i, ']  cmp=', Arc.Entries[i].CmpType,
              '  unc=', Arc.Entries[i].UncSize,
              '  ', Arc.Entries[i].Name);

    WriteLn('--- extracting all entries (lz4 only -- zstd skipped) ---');
    OkCount := 0;
    ExtractCount := 0;
    for i := 0 to High(Arc.Entries) do
    begin
      if not (Arc.Entries[i].CmpType in [0, 1]) then
      begin
        WriteLn('  [', i, '] SKIP (cmp=', Arc.Entries[i].CmpType, ')  ', Arc.Entries[i].Name);
        Continue;
      end;
      Inc(ExtractCount);
      GetMem(Buf, Arc.Entries[i].UncSize + 1);
      try
        if Arc.ExtractEntry(i, Buf, Arc.Entries[i].UncSize) then
          Inc(OkCount)
        else
          WriteLn('  [', i, '] FAIL  ', Arc.Entries[i].Name);
      finally
        FreeMem(Buf);
      end;
    end;
    WriteLn('attempted: ', ExtractCount, '   succeeded: ', OkCount);
  finally
    Arc.Free;
  end;
end.
