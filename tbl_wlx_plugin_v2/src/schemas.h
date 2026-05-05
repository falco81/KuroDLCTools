// Schema database for the TBL plugin. Loads everything from a
// `schemas/` directory that mirrors KuroTools' layout:
//
//   schemas/
//     t_dlc.json                       -> {"headers": ["DLCTableData", ...]}
//     t_npc_c%d%d%d%d.json             -> filename template (digit wildcards)
//     headers/
//       DLCTableData.json              -> {"FALCOM_PS4": {"game":..., "schema":...},
//                                          "CLE_PC":     {...}}
//       ItemTableData.json
//
// The plugin fetches a schema in two steps:
//   1. Take TBL filename without .tbl. Replace each ASCII digit with
//      "%d". Look for matching `schemas/<that>.json`. Its `headers`
//      array tells us which header *names* belong in the file.
//   2. For each header name encountered while parsing, look in
//      `schemas/headers/<HeaderName>.json`. That file lists every
//      known game/platform variant for that header along with field
//      definitions and total byte size. Match the variant whose size
//      equals the on-disk entry_length; if multiple tie, the
//      caller-supplied preferred-game tag wins.
#pragma once

#include "tbl_types.h"

#include <map>
#include <memory>
#include <string>
#include <vector>

namespace tbl {

// One game/platform variant of a single header.
struct SchemaVariant {
    std::string  platformKey;          // 'FALCOM_PS4', 'CLE_PC', 'NISA_PC', ...
    std::string  gameTag;              // 'Kuro1', 'Kuro2', 'Sora1', 'Ys_X', ...
    int          size = 0;             // byte size of one row (= sum of field sizes)
    std::shared_ptr<FieldList> fields; // owned by the schema cache
};

// All known variants for one header name.
struct SchemaHeader {
    std::string                 name;
    std::vector<SchemaVariant>  variants;
};

class SchemaDB {
public:
    SchemaDB();

    // Scan a `schemas/` directory and load everything inside it.
    // Errors are appended to `errors` (caller-owned) but loading
    // continues; partial schemas remain usable.
    void LoadFromDir(const std::wstring& dir, std::vector<std::string>* errors);

    // Find header schema by exact name. nullptr if unknown.
    const SchemaHeader* FindHeader(const std::string& name) const;

    // Find one specific variant of a header by entry length, with an
    // optional preferred game tag. Returns nullptr if none of the
    // variants match `entryLength`.
    const SchemaVariant* FindVariant(const std::string& headerName,
                                     int entryLength,
                                     const std::string& preferGame) const;

    // Look up the list of headers expected in a TBL file given its
    // filename (with or without .tbl extension). nullptr if no schema
    // file matches. The lookup normalises ASCII digits in the stem to
    // "%d" so e.g. "t_npc_c1234" matches "t_npc_c%d%d%d%d.json".
    const std::vector<std::string>* FindTblHeaders(const std::string& tblFileName) const;

    int HeaderCount()  const { return (int)headers_.size(); }
    int VariantCount() const;

private:
    // header name -> SchemaHeader (heap so pointers stay valid)
    std::map<std::string, std::unique_ptr<SchemaHeader>> headers_;
    // file-stem template -> list of header names
    std::map<std::string, std::vector<std::string>>      tblHeaderLists_;

    SchemaHeader* GetOrCreateHeader(const std::string& name);
};

} // namespace tbl
