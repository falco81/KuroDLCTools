program testroundtrip;
{$mode objfpc}{$H+}
uses SysUtils, Classes, p3alib;

var
  Arc: TP3AArchive;
  W: TP3AWriter;
  i: Integer;
  CmpBuf: TBytes;
  E: TP3AEntry;
  Buf: array of Byte;
  S: AnsiString;
  Total: Int64;
begin
  // --- Step 1: open the user's actual archive and rebuild it,
  // copying every entry verbatim. The result should be smaller
  // (no padding overhead from the original) but functionally identical.
  Arc := TP3AArchive.Create('/home/claude/work/pyrixia.p3a');
  W := TP3AWriter.Create;
  Total := 0;
  for i := 0 to High(Arc.Entries) do
  begin
    E := Arc.Entries[i];
    SetLength(CmpBuf, E.CmpSize);
    if not Arc.ReadCompressedBytes(i, @CmpBuf[0]) then
    begin
      WriteLn('failed to read entry ', i);
      Halt(1);
    end;
    W.AddFromCompressed(E.Name, E.CmpType, CmpBuf, E.UncSize,
                        E.CmpHash, E.UncHash, E.HasUncHash);
    Inc(Total, E.CmpSize);
  end;
  Arc.Free;

  // --- Step 2: also add a new file (simulates "add to archive")
  S := 'Hello from the Pascal WCX plugin!';
  W.AddFromBuffer('asset/test/wcx_added.txt', PByte(@S[1]), Length(S));

  W.WriteToFile('/tmp/rebuilt.p3a');
  W.Free;

  WriteLn('rebuilt: copied ', Total, ' compressed bytes from 55 entries + 1 new entry');
end.
