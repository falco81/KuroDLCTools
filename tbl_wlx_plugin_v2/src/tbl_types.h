// Type system used by KuroTools' TBL schemas. Schema fields are
// either:
//   - a primitive type name string:
//       byte,  short,  int,  long,  float    (signed integers + IEEE-754)
//       ubyte, ushort, uint, ulong            (unsigned integers)
//       toffset                                (8-byte offset to NUL-term UTF-8)
//       toffset<encoding>                      (e.g. "toffsetlatin-1")
//       u8array, u16array, u32array            (8-byte offset + 4-byte count)
//   - a nested record:
//       { "size": N, "schema": { key1: type1, ... } }
//
// This unit provides the parsed shape (TblDataType) and primitive read
// helpers; whole-file row decoding lives in tbl_file.cpp.
#pragma once

#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

#include "json.h"

namespace tbl {

enum class TblBaseKind : uint8_t {
    Byte, UByte,
    Short, UShort,
    Int, UInt,
    Long, ULong,
    Float,
    TOffset,
    U8Array, U16Array, U32Array,
    Nested
};

class FieldList;             // forward — defined below

// A parsed schema field shape. For nested records `nestedFields` is
// non-null; for `toffset<...>` `encoding` is filled.
struct TblDataType {
    TblBaseKind   kind = TblBaseKind::UInt;
    std::string   encoding;                       // tbkTOffset only ("" → "utf-8")
    int           nestedSize = 0;                 // tbkNested only
    std::shared_ptr<FieldList> nestedFields;      // tbkNested only
};

struct NamedField {
    std::string  name;
    TblDataType  dataType;
};

class FieldList {
public:
    std::vector<NamedField> fields;
};

class BadType : public std::runtime_error {
public:
    explicit BadType(const std::string& m) : std::runtime_error(m) {}
};

// Parse a JSON value (string or object) into a TblDataType.
TblDataType ParseFieldType(const mj::Json& v);

// Parse the top-level "schema" object (mapping name -> type) into a
// FieldList. Caller takes ownership.
std::shared_ptr<FieldList> ParseFieldList(const mj::Json& schemaObj);

// In-place byte size of a field. Primitive types return their fixed
// size; toffset/arrays return 8 / 12 (the offset+count cell);
// nested records return the explicit "size" attribute.
int FieldTypeSize(const TblDataType& ft);

// Sum of every field's in-place size in a FieldList.
int FieldListSize(const FieldList& fl);

// ---------------------------------------------------------------------
//  Primitive read helpers — fixed-width values, little-endian.
// ---------------------------------------------------------------------

// Read a single primitive value at byte offset off in buf and append
// it to out as a JSON value (number for int/float, etc.). For
// toffset / u*array the caller resolves the offset/count separately
// using the lower-level ReadPrimInt / ReadStringZ helpers.
mj::Json ReadPrim(const std::vector<uint8_t>& buf, size_t off,
                  TblBaseKind kind);

// Read a NUL-terminated byte string at off. The bytes are passed
// through without character-set conversion; callers attach an
// encoding tag in the schema if they care.
std::string ReadStringZ(const std::vector<uint8_t>& buf, size_t off);

// Read primitive integers / floats without allocating a Json node.
int64_t ReadPrimInt(const std::vector<uint8_t>& buf, size_t off,
                    TblBaseKind kind);
float   ReadPrimFloat(const std::vector<uint8_t>& buf, size_t off);

} // namespace tbl
