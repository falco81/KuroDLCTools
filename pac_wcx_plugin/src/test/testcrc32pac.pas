program testcrc32pac;
{$mode objfpc}{$H+}

uses SysUtils, crc32pac;

procedure Check(const Name: AnsiString; Expected: LongWord);
var Got: LongWord;
begin
  Got := CRC32_PAC_Str(Name);
  Write('  CRC32_PAC("', Name, '") = ', IntToHex(Got, 8));
  if Got = Expected then WriteLn('  OK')
  else                   WriteLn('  FAIL (expected ', IntToHex(Expected, 8), ')');
end;

begin
  // Hashes verified via reading the user's layout.pac directly:
  Check('layout/highspeed.lay',     $0025E574);
  Check('layout/minimap_menu.lay',  $0166F178);
  Check('layout/ui_mapname_effect.lay', $05279EA0);
  // From misc.pac:
  Check('system/clearicon_en.png',  $07D99E12);
  Check('system/systemicon_es.png', $09CC1734);
  Check('system/systemicon.png',    $124F3994);
end.
