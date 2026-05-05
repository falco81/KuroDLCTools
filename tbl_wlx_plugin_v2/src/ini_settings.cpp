#include "ini_settings.h"

#include <windows.h>

#include <cstdio>
#include <cstdlib>

namespace tbl {

namespace {

constexpr const wchar_t* kSection = L"TBLViewer";

std::string WToUtf8(const wchar_t* w) {
    if (!w || !*w) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
    std::string s(n ? n - 1 : 0, 0);
    if (n) WideCharToMultiByte(CP_UTF8, 0, w, -1, s.data(), n, nullptr, nullptr);
    return s;
}

std::wstring U8ToW(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                                nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                        w.data(), n);
    return w;
}

bool ReadBool(const wchar_t* key, const wchar_t* def, const std::wstring& path) {
    wchar_t buf[16];
    GetPrivateProfileStringW(kSection, key, def, buf, 16, path.c_str());
    if (buf[0] == L'1' || buf[0] == L'y' || buf[0] == L'Y'
        || buf[0] == L't' || buf[0] == L'T') return true;
    return false;
}

int ReadInt(const wchar_t* key, int def, const std::wstring& path) {
    wchar_t buf[32];
    wchar_t defS[16];
    std::swprintf(defS, 16, L"%d", def);
    GetPrivateProfileStringW(kSection, key, defS, buf, 32, path.c_str());
    return (int)_wtoi(buf);
}

void WriteInt(const wchar_t* key, int v, const std::wstring& path) {
    wchar_t buf[32];
    std::swprintf(buf, 32, L"%d", v);
    WritePrivateProfileStringW(kSection, key, buf, path.c_str());
}

void WriteBool(const wchar_t* key, bool v, const std::wstring& path) {
    WritePrivateProfileStringW(kSection, key, v ? L"1" : L"0", path.c_str());
}

void WriteStr(const wchar_t* key, const std::wstring& v,
              const std::wstring& path) {
    WritePrivateProfileStringW(kSection, key, v.c_str(), path.c_str());
}

} // namespace

bool IsValidGameTag(const std::string& tag) {
    return tag.empty()
        || tag == "Kuro1" || tag == "Kuro2"
        || tag == "Sora1" || tag == "Ys_X" || tag == "Kai";
}

void IniSettings::Load(const std::wstring& iniPath) {
    if (iniPath.empty()) return;

    {
        wchar_t buf[64] = {};
        GetPrivateProfileStringW(kSection, L"PreferredGame", L"",
                                 buf, 64, iniPath.c_str());
        std::string g = WToUtf8(buf);
        if (IsValidGameTag(g)) preferredGame = g;
    }
    fontSize         = ReadInt (L"FontSize",           14,    iniPath);
    if (fontSize < 6 || fontSize > 64) fontSize = 14;
    defaultEditMode  = ReadBool(L"DefaultEditMode",    L"0",  iniPath);
    rememberWinSize  = ReadBool(L"RememberWindowSize", L"1",  iniPath);
    maximizeOnOpen   = ReadBool(L"MaximizeOnOpen",     L"0",  iniPath);

    lastWinX         = ReadInt (L"LastWinX",           -1,    iniPath);
    lastWinY         = ReadInt (L"LastWinY",           -1,    iniPath);
    lastWinW         = ReadInt (L"LastWinW",           -1,    iniPath);
    lastWinH         = ReadInt (L"LastWinH",           -1,    iniPath);
    lastWinMax       = ReadBool(L"LastWinMax",         L"0",  iniPath);

    lastSubX         = ReadInt (L"LastSubX",           -1,    iniPath);
    lastSubY         = ReadInt (L"LastSubY",           -1,    iniPath);
    lastSubW         = ReadInt (L"LastSubW",           -1,    iniPath);
    lastSubH         = ReadInt (L"LastSubH",           -1,    iniPath);
    lastSubMax       = ReadBool(L"LastSubMax",         L"0",  iniPath);
}

void IniSettings::SaveWindowState(const std::wstring& iniPath) const {
    if (iniPath.empty()) return;
    WriteInt (L"LastWinX",   lastWinX,   iniPath);
    WriteInt (L"LastWinY",   lastWinY,   iniPath);
    WriteInt (L"LastWinW",   lastWinW,   iniPath);
    WriteInt (L"LastWinH",   lastWinH,   iniPath);
    WriteBool(L"LastWinMax", lastWinMax, iniPath);
}

void IniSettings::SaveSubGridState(const std::wstring& iniPath) const {
    if (iniPath.empty()) return;
    WriteInt (L"LastSubX",   lastSubX,   iniPath);
    WriteInt (L"LastSubY",   lastSubY,   iniPath);
    WriteInt (L"LastSubW",   lastSubW,   iniPath);
    WriteInt (L"LastSubH",   lastSubH,   iniPath);
    WriteBool(L"LastSubMax", lastSubMax, iniPath);
}

void IniSettings::SaveOptions(const std::wstring& iniPath) const {
    if (iniPath.empty()) return;
    WriteStr (L"PreferredGame",      U8ToW(preferredGame), iniPath);
    WriteInt (L"FontSize",           fontSize,             iniPath);
    WriteBool(L"DefaultEditMode",    defaultEditMode,      iniPath);
    WriteBool(L"RememberWindowSize", rememberWinSize,      iniPath);
    WriteBool(L"MaximizeOnOpen",     maximizeOnOpen,       iniPath);
}

} // namespace tbl
