#include "tbl_types.h"

#include <cstring>
#include <stdexcept>

namespace tbl {

namespace {

inline uint8_t  RD8 (const std::vector<uint8_t>& b, size_t o) {
    if (o >= b.size()) throw BadType("read past end");
    return b[o];
}
inline uint16_t RD16(const std::vector<uint8_t>& b, size_t o) {
    if (o + 2 > b.size()) throw BadType("read past end");
    return (uint16_t)b[o] | ((uint16_t)b[o + 1] << 8);
}
inline uint32_t RD32(const std::vector<uint8_t>& b, size_t o) {
    if (o + 4 > b.size()) throw BadType("read past end");
    return (uint32_t)b[o]
         | ((uint32_t)b[o + 1] << 8)
         | ((uint32_t)b[o + 2] << 16)
         | ((uint32_t)b[o + 3] << 24);
}
inline uint64_t RD64(const std::vector<uint8_t>& b, size_t o) {
    if (o + 8 > b.size()) throw BadType("read past end");
    uint64_t v = 0;
    for (int i = 0; i < 8; ++i) v |= ((uint64_t)b[o + i]) << (i * 8);
    return v;
}

} // namespace

// ---------------------------------------------------------------------
//   Schema-shape parsing
// ---------------------------------------------------------------------
TblDataType ParseFieldType(const mj::Json& v) {
    TblDataType ft;
    if (v.IsStr()) {
        const std::string& s = v.AsStr();
        if      (s == "byte")    ft.kind = TblBaseKind::Byte;
        else if (s == "ubyte")   ft.kind = TblBaseKind::UByte;
        else if (s == "short")   ft.kind = TblBaseKind::Short;
        else if (s == "ushort")  ft.kind = TblBaseKind::UShort;
        else if (s == "int")     ft.kind = TblBaseKind::Int;
        else if (s == "uint")    ft.kind = TblBaseKind::UInt;
        else if (s == "long")    ft.kind = TblBaseKind::Long;
        else if (s == "ulong")   ft.kind = TblBaseKind::ULong;
        else if (s == "float")   ft.kind = TblBaseKind::Float;
        else if (s == "u8array") ft.kind = TblBaseKind::U8Array;
        else if (s == "u16array")ft.kind = TblBaseKind::U16Array;
        else if (s == "u32array")ft.kind = TblBaseKind::U32Array;
        else if (s == "toffset") {
            ft.kind = TblBaseKind::TOffset;
            ft.encoding = "utf-8";
        } else if (s.size() > 7 && s.compare(0, 7, "toffset") == 0) {
            ft.kind = TblBaseKind::TOffset;
            ft.encoding = s.substr(7);
        } else {
            throw BadType("unsupported primitive type \"" + s + "\"");
        }
        return ft;
    }
    if (v.IsObj()) {
        ft.kind = TblBaseKind::Nested;
        const mj::Json* sz = v.Find("size");
        if (!sz || !sz->IsNumber()) throw BadType("nested record missing \"size\"");
        ft.nestedSize = (int)sz->AsInt();
        const mj::Json* sch = v.Find("schema");
        if (!sch || !sch->IsObj()) throw BadType("nested record missing \"schema\"");
        ft.nestedFields = ParseFieldList(*sch);
        return ft;
    }
    throw BadType("field type must be string or object");
}

std::shared_ptr<FieldList> ParseFieldList(const mj::Json& schemaObj) {
    if (!schemaObj.IsObj()) throw BadType("schema must be an object");
    auto fl = std::make_shared<FieldList>();
    for (const auto& kv : schemaObj.AsObj()) {
        NamedField nf;
        nf.name     = kv.first;
        nf.dataType = ParseFieldType(kv.second);
        fl->fields.push_back(std::move(nf));
    }
    return fl;
}

int FieldTypeSize(const TblDataType& ft) {
    switch (ft.kind) {
        case TblBaseKind::Byte:    case TblBaseKind::UByte:  return 1;
        case TblBaseKind::Short:   case TblBaseKind::UShort: return 2;
        case TblBaseKind::Int:     case TblBaseKind::UInt:
        case TblBaseKind::Float:                              return 4;
        case TblBaseKind::Long:    case TblBaseKind::ULong:
        case TblBaseKind::TOffset:                            return 8;
        case TblBaseKind::U8Array:
        case TblBaseKind::U16Array:
        case TblBaseKind::U32Array:                           return 12;
        case TblBaseKind::Nested:                             return ft.nestedSize;
    }
    return 0;
}

int FieldListSize(const FieldList& fl) {
    int total = 0;
    for (const auto& f : fl.fields) total += FieldTypeSize(f.dataType);
    return total;
}

// ---------------------------------------------------------------------
//   Primitive read helpers
// ---------------------------------------------------------------------
int64_t ReadPrimInt(const std::vector<uint8_t>& b, size_t off,
                    TblBaseKind kind) {
    switch (kind) {
        case TblBaseKind::Byte:    return (int8_t) RD8 (b, off);
        case TblBaseKind::UByte:   return            RD8 (b, off);
        case TblBaseKind::Short:   return (int16_t)RD16(b, off);
        case TblBaseKind::UShort:  return            RD16(b, off);
        case TblBaseKind::Int:     return (int32_t)RD32(b, off);
        case TblBaseKind::UInt:    return (int64_t)(uint64_t)RD32(b, off);
        case TblBaseKind::Long:    return (int64_t)RD64(b, off);
        case TblBaseKind::ULong: {
            // We do return a signed 64; values >=2^63 will look negative
            // in JSON, but that matches what KuroTools does.
            return (int64_t)RD64(b, off);
        }
        case TblBaseKind::TOffset: return (int64_t)RD64(b, off);
        default:
            throw BadType("ReadPrimInt: not an integer kind");
    }
}

float ReadPrimFloat(const std::vector<uint8_t>& b, size_t off) {
    uint32_t bits = RD32(b, off);
    float f;
    std::memcpy(&f, &bits, 4);
    return f;
}

mj::Json ReadPrim(const std::vector<uint8_t>& b, size_t off,
                  TblBaseKind kind) {
    if (kind == TblBaseKind::Float) {
        return mj::Json::MakeReal((double)ReadPrimFloat(b, off));
    }
    return mj::Json::MakeInt(ReadPrimInt(b, off, kind));
}

std::string ReadStringZ(const std::vector<uint8_t>& b, size_t off) {
    if (off >= b.size()) throw BadType("toffset out of range");
    std::string s;
    while (off < b.size() && b[off] != 0) {
        s.push_back((char)b[off]);
        ++off;
    }
    return s;
}

} // namespace tbl
