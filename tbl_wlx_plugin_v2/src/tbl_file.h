// Whole-file TBL reader matching KuroTools' on-disk format exactly.
//
// Wire format:
//   8 bytes        '#TBL' + uint32 num_sections (LE)
//   N x 80 bytes   per-section directory entry:
//                    64B  name  (NUL-padded UTF-8)
//                     4B  uint32  CRC32(name)
//                     4B  uint32  start_offset (absolute)
//                     4B  uint32  entry_length (bytes per row)
//                     4B  uint32  num_entries
//   ...rows...     each section's row data, packed back-to-back
//   ...data2...    variable-length payload area: NUL-term strings,
//                  array contents
//
// JSON serialization matches KuroTools' shape:
//   { "headers": [{"name": ..., "schema": ...}, ...],
//     "data":    [{"name": ..., "data": [...]}, ...] }
//
// This v2 plugin only implements the read path. Writeback / re-pack
// will land alongside the grid editor in a later release.
#pragma once

#include "json.h"
#include "schemas.h"
#include "tbl_types.h"

#include <stdexcept>
#include <string>
#include <vector>

namespace tbl {

class TblError : public std::runtime_error {
public:
    explicit TblError(const std::string& m) : std::runtime_error(m) {}
};

enum class TblSectionMode { Decoded, Raw };

struct TblSection {
    std::string         name;
    TblSectionMode      mode = TblSectionMode::Raw;
    int                 entryLength = 0;
    std::string         gameTag;
    std::string         platformKey;
    mj::Json            rows;          // arr of row-objects (decoded mode)
    std::vector<uint8_t> rawBytes;     // raw mode
};

class TblFile {
public:
    explicit TblFile(const SchemaDB* db) : schemaDb_(db) {}

    // Read a TBL file from disk. Auto-detects CLE-wrapped files (F9BA /
    // C9BA / D9BA magic) and unwraps them before parsing. PreferGame
    // guides schema variant selection when multiple variants share the
    // same entry_length (e.g. "Kuro1" vs "Kuro2").
    void ReadFromFile(const std::wstring& path,
                      const std::string& preferGame = "",
                      const std::string& tblHeaderHint = "");

    // Build the KuroTools-shaped JSON view (caller-owned).
    mj::Json ToJson() const;

    // Replace section data with what's in the JSON. Section structure
    // (count, names, entry_lengths) must match what was loaded.
    // Raw-mode sections are left alone; only Decoded sections get
    // their rows refreshed from `obj["data"][N]["data"]`.
    void FromJson(const mj::Json& obj);

    // Write the in-memory state back to disk as a plain (uncompressed,
    // unencrypted) #TBL file. If any section is in raw mode, falls
    // back to verbatim passthrough of the original plaintext bytes —
    // since raw sections may reference into the file-wide data2 area
    // we cannot safely re-emit without their schema. CLE re-wrap on
    // save is not done; the file lands as plain #TBL.
    void WriteToFile(const std::wstring& path);

    bool WasCLEWrapped() const { return wasCLEWrapped_; }
    bool AnyRawSection() const { return anyRawSection_; }
    const std::vector<std::string>& SchemaWarnings() const { return schemaWarnings_; }
    const std::vector<TblSection>&  Sections()       const { return sections_; }
    std::vector<TblSection>&        MutableSections()       { return sections_; }

private:
    const SchemaDB*           schemaDb_;
    std::vector<TblSection>   sections_;
    bool                      wasCLEWrapped_  = false;
    bool                      anyRawSection_  = false;
    std::vector<std::string>  schemaWarnings_;
    // Verbatim passthrough buffer for cases where any section is raw —
    // see WriteToFile. Captured at end of ReadFromFile.
    std::vector<uint8_t>      origPlainBytes_;

    mj::Json DecodeRow(const std::vector<uint8_t>& buf, size_t rowOff,
                       const FieldList& fields);
    mj::Json DecodeNested(const std::vector<uint8_t>& buf, size_t rowOff,
                          int nestedSize, const FieldList& fields);
};

} // namespace tbl
