program testroundv1200;
{$mode objfpc}{$H+}

// Verifies that a v1200+dict archive survives a read→write→read cycle:
//   1) Open original
//   2) CarryOver-style: copy every entry verbatim into TP3AWriter
//   3) Save to new path
//   4) Open new archive, verify same entries + extract them all
//
// This exercises the writer's v1200 layout and dict-block emission.

uses SysUtils, p3alib;

procedure CopyAndVerify(const SrcPath, DstPath: AnsiString);
var
  Src, Dst: TP3AArchive;
  W: TP3AWriter;
  i: Integer;
  CmpBuf, OutBuf: TBytes;
  E: TP3AEntry;
  OK, Failed: Integer;
begin
  Src := TP3AArchive.Create(SrcPath);
  try
    WriteLn('Source: version=', Src.Version, ', flags=', Src.Flags,
            ', dict=', Length(Src.Dict), ' bytes, entries=', Length(Src.Entries));

    W := TP3AWriter.Create;
    try
      W.SourceVersion := Src.Version;
      if Length(Src.Dict) > 0 then W.SetDict(Src.Dict);

      for i := 0 to High(Src.Entries) do
      begin
        E := Src.Entries[i];
        SetLength(CmpBuf, E.CmpSize);
        Src.ReadCompressedBytes(i, @CmpBuf[0]);
        W.AddFromCompressed(E.Name, E.CmpType, CmpBuf, E.UncSize,
                            E.CmpHash, E.UncHash, E.HasUncHash);
      end;

      W.WriteToFile(DstPath, 0);  // 0 = use SourceVersion
      WriteLn('Wrote ', W.Count, ' entries to ', DstPath);
    finally
      W.Free;
    end;
  finally
    Src.Free;
  end;

  // Re-open the just-written archive and extract everything
  Dst := TP3AArchive.Create(DstPath);
  try
    WriteLn('Re-opened: version=', Dst.Version, ', flags=', Dst.Flags,
            ', dict=', Length(Dst.Dict), ' bytes, entries=', Length(Dst.Entries));

    OK := 0; Failed := 0;
    for i := 0 to High(Dst.Entries) do
    begin
      E := Dst.Entries[i];
      SetLength(OutBuf, E.UncSize);
      if E.UncSize = 0 then begin Inc(OK); Continue; end;
      if Dst.ExtractEntry(i, @OutBuf[0], E.UncSize) then
        Inc(OK)
      else
      begin
        Inc(Failed);
        if Failed <= 3 then
          WriteLn('  FAIL [', i, '] ', E.Name, ' cmp=', E.CmpType);
      end;
    end;
    WriteLn('Round-trip extract: OK=', OK, ', Failed=', Failed);
    if Failed > 0 then Halt(2);
  finally
    Dst.Free;
  end;
end;

begin
  if ParamCount < 2 then
  begin
    WriteLn('usage: testroundv1200 <src.p3a> <dst.p3a>');
    Halt(1);
  end;
  CopyAndVerify(ParamStr(1), ParamStr(2));
  WriteLn('SUCCESS');
end.
