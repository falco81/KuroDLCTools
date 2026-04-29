program testwrite;
{$mode objfpc}{$H+}
uses SysUtils, Classes, p3alib;

var
  W: TP3AWriter;
  S: AnsiString;
  Buf: array of Byte;
  i: Integer;
  F: TFileStream;
begin
  W := TP3AWriter.Create;
  try
    S := 'Hello, P3A!';
    W.AddFromBuffer('asset/text/hello.txt', PByte(@S[1]), Length(S));

    SetLength(Buf, 4096);
    for i := 0 to High(Buf) do Buf[i] := Byte((i * 13) and $FF);
    W.AddFromBuffer('asset/data/random.bin', @Buf[0], Length(Buf));

    SetLength(Buf, 8000);
    FillChar(Buf[0], Length(Buf), $42);
    W.AddFromBuffer('asset/common/model/test.mdl', @Buf[0], Length(Buf));

    W.WriteToFile('/tmp/written.p3a');
  finally
    W.Free;
  end;

  F := TFileStream.Create('/tmp/written.p3a', fmOpenRead);
  WriteLn('wrote /tmp/written.p3a, size=', F.Size);
  F.Free;
end.
