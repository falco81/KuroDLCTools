#include "schemas.h"
#include "json.h"

#include <windows.h>

#include <fstream>
#include <sstream>

namespace tbl {

namespace {

// Slurp a whole file as bytes (UTF-8 expected for our schemas).
bool ReadFileAllW(const std::wstring& path, std::string* out) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ,
                           FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_EXISTING,
                           FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER sz;
    if (!GetFileSizeEx(h, &sz) || sz.QuadPart > (1 << 24)) {
        // Schemas are small (~few KB). Cap at 16 MB to keep us safe.
        CloseHandle(h);
        return false;
    }
    out->resize((size_t)sz.QuadPart);
    DWORD got = 0;
    BOOL ok = ReadFile(h, out->data(), (DWORD)sz.QuadPart, &got, nullptr);
    CloseHandle(h);
    if (!ok || got != (DWORD)sz.QuadPart) return false;
    return true;
}

// Some KuroTools schema files have the same platform key listed twice
// (e.g. ConditionInfoTableData.json has two FALCOM_PS4 entries).
// Python's json.load silently keeps the LAST one; we rename later
// occurrences to "<name>__dupN" so the JSON is parseable, and our
// schema layer treats them as additional variants.
std::string DedupJsonKeys(const std::string& src) {
    std::string out;
    out.reserve(src.size());

    int  depth = 0;
    bool inString = false;
    bool expectingKey = false;
    bool prevBackslash = false;
    size_t startIdx = 0;

    // Per-depth set of key names already seen.
    std::vector<std::vector<std::string>> levels;
    levels.resize(64);

    for (size_t i = 0; i < src.size(); ++i) {
        char ch = src[i];
        if (inString) {
            if (prevBackslash) {
                prevBackslash = false;
                out.push_back(ch);
                continue;
            }
            if (ch == '\\') {
                prevBackslash = true;
                out.push_back(ch);
                continue;
            }
            if (ch == '"') {
                inString = false;
                if (expectingKey) {
                    std::string cur(out, startIdx,
                                    out.size() - startIdx);
                    auto& names = levels[depth];
                    int dupCounter = 0;
                    std::string newKey = cur;
                    while (true) {
                        bool seen = false;
                        for (const auto& n : names) {
                            if (n == newKey) { seen = true; break; }
                        }
                        if (!seen) break;
                        ++dupCounter;
                        newKey = cur + "__dup" + std::to_string(dupCounter);
                    }
                    names.push_back(newKey);
                    if (newKey != cur) {
                        out.resize(startIdx);
                        out.append(newKey);
                    }
                    expectingKey = false;
                }
                out.push_back(ch);
                continue;
            }
            out.push_back(ch);
            continue;
        }
        // Outside any string.
        if (ch == '"') {
            // Decide whether this opens a key (next non-ws char will be ':').
            // We approximate: a string immediately preceded by '{' or ','
            // (after skipping whitespace) is a key.
            inString = true;
            // Peek backwards to find last non-ws / non-quote character.
            size_t k = out.size();
            while (k > 0) {
                char p = out[k - 1];
                if (p == ' ' || p == '\t' || p == '\n' || p == '\r') { --k; continue; }
                break;
            }
            char prev = (k > 0) ? out[k - 1] : '\0';
            expectingKey = (prev == '{' || prev == ',');
            startIdx = out.size() + 1;     // position right after the opening "
            out.push_back(ch);
            continue;
        }
        if (ch == '{') {
            ++depth;
            if ((int)levels.size() <= depth) levels.resize(depth + 8);
            levels[depth].clear();
        } else if (ch == '}') {
            if (depth > 0) levels[depth].clear();
            --depth;
            if (depth < 0) depth = 0;
        }
        out.push_back(ch);
    }
    return out;
}

// Convert UTF-8 path to wide for Win32.
[[maybe_unused]] std::wstring U8ToW(const std::string& s) {
    if (s.empty()) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                                 nullptr, 0);
    std::wstring w(n, 0);
    MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(),
                        w.data(), n);
    return w;
}

std::string WToU8(const std::wstring& w) {
    if (w.empty()) return "";
    int n = WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                                 nullptr, 0, nullptr, nullptr);
    std::string s(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, w.c_str(), (int)w.size(),
                        s.data(), n, nullptr, nullptr);
    return s;
}

// Strip "__dup<N>" suffix from a key.
std::string StripDupSuffix(const std::string& s) {
    auto p = s.find("__dup");
    if (p == std::string::npos) return s;
    return s.substr(0, p);
}

} // namespace

SchemaDB::SchemaDB() = default;

SchemaHeader* SchemaDB::GetOrCreateHeader(const std::string& name) {
    auto it = headers_.find(name);
    if (it != headers_.end()) return it->second.get();
    auto h = std::make_unique<SchemaHeader>();
    h->name = name;
    SchemaHeader* raw = h.get();
    headers_.emplace(name, std::move(h));
    return raw;
}

const SchemaHeader* SchemaDB::FindHeader(const std::string& name) const {
    auto it = headers_.find(name);
    return (it == headers_.end()) ? nullptr : it->second.get();
}

int SchemaDB::VariantCount() const {
    int n = 0;
    for (const auto& kv : headers_) n += (int)kv.second->variants.size();
    return n;
}

const SchemaVariant* SchemaDB::FindVariant(const std::string& headerName,
                                           int entryLength,
                                           const std::string& preferGame) const {
    const SchemaHeader* h = FindHeader(headerName);
    if (!h) return nullptr;
    const SchemaVariant* firstMatch = nullptr;
    for (const auto& v : h->variants) {
        if (v.size != entryLength) continue;
        if (!preferGame.empty() && v.gameTag == preferGame) return &v;
        if (!firstMatch) firstMatch = &v;
    }
    return firstMatch;
}

const std::vector<std::string>*
SchemaDB::FindTblHeaders(const std::string& tblFileName) const {
    // Strip directory + extension to get the stem.
    std::string stem = tblFileName;
    size_t slash = stem.find_last_of("/\\");
    if (slash != std::string::npos) stem = stem.substr(slash + 1);
    size_t dot = stem.rfind('.');
    if (dot != std::string::npos) stem = stem.substr(0, dot);

    // Replace each digit with "%d".
    std::string norm;
    for (char c : stem) {
        if (c >= '0' && c <= '9') norm += "%d";
        else                      norm += c;
    }
    auto it = tblHeaderLists_.find(norm);
    if (it != tblHeaderLists_.end()) return &it->second;
    // Some schemas don't have digits; try the unnormalised stem too.
    it = tblHeaderLists_.find(stem);
    if (it != tblHeaderLists_.end()) return &it->second;
    return nullptr;
}

void SchemaDB::LoadFromDir(const std::wstring& dir,
                           std::vector<std::string>* errors) {
    auto pushErr = [&](const std::string& s) {
        if (errors) errors->push_back(s);
    };

    // ---- 1) Top-level t_*.json files: header-name lists -------------
    {
        std::wstring pat = dir + L"\\*.json";
        WIN32_FIND_DATAW fd;
        HANDLE h = FindFirstFileW(pat.c_str(), &fd);
        if (h != INVALID_HANDLE_VALUE) {
            do {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
                std::wstring fullPath = dir + L"\\" + fd.cFileName;
                std::string raw;
                if (!ReadFileAllW(fullPath, &raw)) continue;
                std::string text = DedupJsonKeys(raw);
                mj::Json root;
                try { root = mj::Parse(text); }
                catch (std::exception& e) {
                    pushErr(WToU8(fd.cFileName) + std::string(": ") + e.what());
                    continue;
                }
                if (!root.IsObj()) continue;
                const mj::Json* arr = root.Find("headers");
                if (!arr || !arr->IsArr()) continue;
                std::string baseName = WToU8(fd.cFileName);
                size_t dot = baseName.rfind('.');
                if (dot != std::string::npos) baseName = baseName.substr(0, dot);
                std::vector<std::string> names;
                for (const auto& it : arr->AsArr()) {
                    if (it.IsStr()) names.push_back(it.AsStr());
                }
                tblHeaderLists_.emplace(baseName, std::move(names));
            } while (FindNextFileW(h, &fd));
            FindClose(h);
        }
    }

    // ---- 2) headers/*.json files: actual field schemas ---------------
    std::wstring hdrDir = dir + L"\\headers";
    DWORD attr = GetFileAttributesW(hdrDir.c_str());
    if (attr == INVALID_FILE_ATTRIBUTES || !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
        return;
    }
    std::wstring pat2 = hdrDir + L"\\*.json";
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat2.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        std::wstring fullPath = hdrDir + L"\\" + fd.cFileName;
        std::string raw;
        if (!ReadFileAllW(fullPath, &raw)) continue;
        std::string text = DedupJsonKeys(raw);
        mj::Json root;
        try { root = mj::Parse(text); }
        catch (std::exception& e) {
            pushErr(WToU8(fd.cFileName) + std::string(": ") + e.what());
            continue;
        }
        if (!root.IsObj()) {
            pushErr(WToU8(fd.cFileName) + ": top-level JSON not an object");
            continue;
        }
        std::string baseName = WToU8(fd.cFileName);
        size_t dot = baseName.rfind('.');
        if (dot != std::string::npos) baseName = baseName.substr(0, dot);
        SchemaHeader* hdr = GetOrCreateHeader(baseName);

        for (const auto& kv : root.AsObj()) {
            const std::string& platformKey = kv.first;
            std::string realKey = StripDupSuffix(platformKey);
            const mj::Json& gameDef = kv.second;
            if (!gameDef.IsObj()) continue;

            std::string gameTag;
            if (auto* g = gameDef.Find("game"); g && g->IsStr()) gameTag = g->AsStr();
            const mj::Json* sch = gameDef.Find("schema");
            if (!sch || !sch->IsObj()) continue;

            try {
                SchemaVariant v;
                v.platformKey = realKey;
                v.gameTag     = gameTag;
                v.fields      = ParseFieldList(*sch);
                v.size        = FieldListSize(*v.fields);
                hdr->variants.push_back(std::move(v));
            } catch (std::exception& e) {
                pushErr(WToU8(fd.cFileName) + " [" + realKey + "]: " + e.what());
            }
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

} // namespace tbl
