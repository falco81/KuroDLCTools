program testmarker;
{$mode objfpc}{$H+}

const KeepMarker = '/.p3a_keep';

function IsKeepMarker(const Name: AnsiString): Boolean;
var L: Integer;
begin
  L := Length(KeepMarker);
  Result := (Length(Name) >= L)
            and (LowerCase(Copy(Name, Length(Name) - L + 1, L)) = KeepMarker);
end;

procedure TestCase(const Name: AnsiString; ExpectedMarker: Boolean);
var Got: Boolean;
begin
  Got := IsKeepMarker(Name);
  Write('  ', Name);
  if Got = ExpectedMarker then WriteLn('  -> ', Got, '  OK')
  else                          WriteLn('  -> ', Got, '  FAIL (expected ', ExpectedMarker, ')');
end;

begin
  TestCase('asset/empty1/.p3a_keep', True);
  TestCase('asset/foo/bar/.p3a_keep', True);
  TestCase('.p3a_keep', False);  // no leading slash
  TestCase('foo.p3a_keep', False);  // missing slash before .p3a_keep
  TestCase('asset/foo.p3a_keep', False);  // typo: not in subfolder
  TestCase('asset/foo/file.txt', False);
  TestCase('', False);
  TestCase('asset/.P3A_KEEP', True);  // case-insensitive
  TestCase('asset/.p3a_keep_v2', False); // suffix mismatch
end.
