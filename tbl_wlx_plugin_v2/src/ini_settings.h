// Persist user preferences across Lister sessions. TC hands us an
// INI path via ListSetDefaultParams. We mirror the Pascal upstream's
// schema so plugin INIs travel between versions:
//
//   [TBLViewer]
//     PreferredGame      = ""           ; "" / Kuro1 / Kuro2 / Sora1 / Ys_X / Kai
//     DefaultEditMode    = 0            ; 0 = read-only on F3 (default)
//     RememberWindowSize = 1            ; 1 = restore Lister parent size
//     MaximizeOnOpen     = 0            ; 1 = always maximize on open
//     FontSize           = 14           ; editor / grid point size
//     LastWinX / LastWinY / LastWinW / LastWinH / LastWinMax
//                                       ; auto-saved on close
//     LastSubX / LastSubY / LastSubW / LastSubH
//                                       ; sub-grid popup geometry
#pragma once

#include <string>

namespace tbl {

struct IniSettings {
    std::string preferredGame   = "";
    int         fontSize        = 14;
    bool        defaultEditMode = false;          // false = RO on F3
    bool        rememberWinSize = true;
    bool        maximizeOnOpen  = false;
    bool        autoSizeColumns = false;          // off by default —
                                                  // some users prefer
                                                  // their own widths

    int         lastWinX        = -1;             // -1 = unset
    int         lastWinY        = -1;
    int         lastWinW        = -1;
    int         lastWinH        = -1;
    bool        lastWinMax      = false;
    int         lastSubX        = -1;
    int         lastSubY        = -1;
    int         lastSubW        = -1;
    int         lastSubH        = -1;
    bool        lastSubMax      = false;

    void Load(const std::wstring& iniPath);

    // Persist just the window-geometry block on Lister close.
    void SaveWindowState(const std::wstring& iniPath) const;
    // Persist sub-grid popup geometry.
    void SaveSubGridState(const std::wstring& iniPath) const;
    // Persist user-editable options (Config tab Save button).
    void SaveOptions(const std::wstring& iniPath) const;
};

bool IsValidGameTag(const std::string& tag);

} // namespace tbl
