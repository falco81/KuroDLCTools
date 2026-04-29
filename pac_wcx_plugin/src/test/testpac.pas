program testpac;
{$mode objfpc}{$H+}

uses SysUtils, paclib;

procedure ReadAndRoundtrip(const SrcPath, DstPath: AnsiString);
var
  Src, Dst: TPACArchive;
  W: TPACWriter;
  i, OK, Failed: Integer;
  Buf, Buf2: TBytes;
begin
  Src := TPACArchive.Create(SrcPath);
  try
    WriteLn('Source: ', SrcPath, ' -> ', Length(Src.Entries), ' entries');
    for i := 0 to 2 do
      if i < Length(Src.Entries) then
        WriteLn('  [', i, '] ', Src.Entries[i].Name,
                ' size=', Src.Entries[i].Size,
                ' offs=', Src.Entries[i].DataOffset,
                ' hash=', IntToHex(Src.Entries[i].Hash, 8));

    // Extract every entry (sanity)
    OK := 0; Failed := 0;
    for i := 0 to High(Src.Entries) do
    begin
      SetLength(Buf, Src.Entries[i].Size);
      if (Src.Entries[i].Size = 0) or
         Src.ExtractEntry(i, @Buf[0], Src.Entries[i].Size) then
        Inc(OK)
      else
        Inc(Failed);
    end;
    WriteLn('Extract: OK=', OK, ', Failed=', Failed);

    // Round-trip: read every entry, feed into writer in same order
    W := TPACWriter.Create;
    try
      for i := 0 to High(Src.Entries) do
      begin
        SetLength(Buf, Src.Entries[i].Size);
        if Src.Entries[i].Size > 0 then
          Src.ReadRawBytes(i, @Buf[0]);
        W.AddRaw(Src.Entries[i].Name, Buf);
      end;
      W.WriteToFile(DstPath);
      WriteLn('Wrote ', W.Count, ' entries to ', DstPath);
    finally
      W.Free;
    end;
  finally
    Src.Free;
  end;

  // Verify by re-reading the new archive
  Dst := TPACArchive.Create(DstPath);
  try
    WriteLn('Re-opened: ', Length(Dst.Entries), ' entries');
    OK := 0; Failed := 0;
    for i := 0 to High(Dst.Entries) do
    begin
      SetLength(Buf2, Dst.Entries[i].Size);
      if (Dst.Entries[i].Size = 0) or
         Dst.ExtractEntry(i, @Buf2[0], Dst.Entries[i].Size) then
        Inc(OK)
      else
        Inc(Failed);
    end;
    WriteLn('Round-trip extract: OK=', OK, ', Failed=', Failed);
  finally
    Dst.Free;
  end;
end;

begin
  if ParamCount < 2 then
  begin
    WriteLn('usage: testpac <src.pac> <dst.pac>');
    Halt(1);
  end;
  ReadAndRoundtrip(ParamStr(1), ParamStr(2));
end.
