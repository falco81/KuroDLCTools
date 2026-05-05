#include "tbl_file.h"
#include "cle.h"
#include "crc32.h"

#include <windows.h>

#include <cstdio>
#include <cstring>

namespace tbl {

namespace {

bool LoadEntireFileW(const std::wstring& path, std::vector<uint8_t>* out) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ,
                           FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_EXISTING,
                           FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER sz;
    if (!GetFileSizeEx(h, &sz)) { CloseHandle(h); return false; }
    if (sz.QuadPart > (LONGLONG)(64 * 1024 * 1024)) {
        // 64 MB cap: TBL files in the wild are <2 MB; anything bigger
        // is almost certainly not a TBL.
        CloseHandle(h);
        return false;
    }
    out->resize((size_t)sz.QuadPart);
    DWORD got = 0;
    BOOL ok = ReadFile(h, out->data(), (DWORD)sz.QuadPart, &got, nullptr);
    CloseHandle(h);
    return ok && got == (DWORD)sz.QuadPart;
}

inline uint32_t RD32_LE(const std::vector<uint8_t>& b, size_t o) {
    if (o + 4 > b.size()) throw TblError("read past EOF");
    return (uint32_t)b[o]
         | ((uint32_t)b[o + 1] << 8)
         | ((uint32_t)b[o + 2] << 16)
         | ((uint32_t)b[o + 3] << 24);
}

std::string BaseNameNarrow(const std::wstring& path) {
    int n = WideCharToMultiByte(CP_UTF8, 0, path.c_str(), (int)path.size(),
                                nullptr, 0, nullptr, nullptr);
    std::string s(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, path.c_str(), (int)path.size(),
                        s.data(), n, nullptr, nullptr);
    size_t slash = s.find_last_of("/\\");
    return (slash == std::string::npos) ? s : s.substr(slash + 1);
}

} // namespace

void TblFile::ReadFromFile(const std::wstring& path,
                           const std::string& preferGame,
                           const std::string& tblHeaderHint) {
    sections_.clear();
    schemaWarnings_.clear();
    wasCLEWrapped_ = false;
    anyRawSection_ = false;
    origPlainBytes_.clear();

    std::vector<uint8_t> raw;
    if (!LoadEntireFileW(path, &raw)) {
        throw TblError("cannot open file");
    }

    std::vector<uint8_t> plain;
    if (IsCLEWrapped(raw)) {
        wasCLEWrapped_ = true;
        plain = ProcessCLE(raw);
    } else {
        plain = std::move(raw);
    }

    if (plain.size() < 8) throw TblError("TBL too short");
    if (plain[0] != '#' || plain[1] != 'T' || plain[2] != 'B' || plain[3] != 'L') {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "Bad TBL magic: %02X %02X %02X %02X",
                      plain[0], plain[1], plain[2], plain[3]);
        throw TblError(buf);
    }
    uint32_t numSections = RD32_LE(plain, 4);
    if (numSections > 1024) {
        throw TblError("Suspicious section count " + std::to_string(numSections));
    }

    std::string lookupName = !tblHeaderHint.empty()
        ? tblHeaderHint
        : BaseNameNarrow(path);

    sections_.resize(numSections);
    size_t hdrPos = 8;
    for (uint32_t j = 0; j < numSections; ++j) {
        if (hdrPos + 80 > plain.size()) {
            throw TblError("Section directory entry " + std::to_string(j)
                           + " extends past EOF");
        }
        // 64-byte NUL-padded name
        std::string hdrName;
        for (int k = 0; k < 64; ++k) {
            char c = (char)plain[hdrPos + k];
            if (c == 0) break;
            hdrName.push_back(c);
        }
        hdrPos += 64;
        // Skip CRC + read start/len/count.
        (void)RD32_LE(plain, hdrPos); hdrPos += 4;             // CRC
        uint32_t secStart = RD32_LE(plain, hdrPos); hdrPos += 4;
        uint32_t secLen   = RD32_LE(plain, hdrPos); hdrPos += 4;
        uint32_t secCount = RD32_LE(plain, hdrPos); hdrPos += 4;

        // Defensive bounds check (Int64 to avoid overflow).
        int64_t totalRowBytes = (int64_t)secLen * (int64_t)secCount;
        if (totalRowBytes > (int64_t)plain.size()
            || (int64_t)secStart + totalRowBytes > (int64_t)plain.size()) {
            throw TblError("Section \"" + hdrName +
                           "\": rows do not fit in file");
        }

        TblSection sect;
        sect.name        = hdrName;
        sect.entryLength = (int)secLen;

        const SchemaVariant* var = nullptr;
        if (schemaDb_) var = schemaDb_->FindVariant(hdrName, (int)secLen, preferGame);

        if (var && var->fields) {
            sect.mode        = TblSectionMode::Decoded;
            sect.gameTag     = var->gameTag;
            sect.platformKey = var->platformKey;
            sect.rows        = mj::Json::MakeArr();
            try {
                for (uint32_t r = 0; r < secCount; ++r) {
                    size_t rowOff = secStart + (size_t)r * secLen;
                    sect.rows.AsArr().push_back(
                        DecodeRow(plain, rowOff, *var->fields));
                }
            } catch (std::exception& e) {
                // Decoding failed mid-way — preserve raw bytes instead.
                sect.mode        = TblSectionMode::Raw;
                sect.gameTag.clear();
                sect.platformKey.clear();
                sect.rows = mj::Json{};
                if (totalRowBytes > 0) {
                    sect.rawBytes.assign(plain.begin() + secStart,
                                         plain.begin() + secStart + totalRowBytes);
                }
                schemaWarnings_.push_back(
                    BaseNameNarrow(path) + " [" + hdrName +
                    " len=" + std::to_string(secLen) + "]: " + e.what());
            }
        } else {
            sect.mode = TblSectionMode::Raw;
            if (totalRowBytes > 0) {
                sect.rawBytes.assign(plain.begin() + secStart,
                                     plain.begin() + secStart + totalRowBytes);
            }
            schemaWarnings_.push_back(
                BaseNameNarrow(path) + " [" + hdrName +
                " len=" + std::to_string(secLen) + "]: no matching schema");
        }
        sections_[j] = std::move(sect);
    }
    (void)lookupName; // (used in writer; kept for symmetry)

    // Decide whether writeback will need verbatim passthrough.
    for (const auto& s : sections_) {
        if (s.mode == TblSectionMode::Raw) { anyRawSection_ = true; break; }
    }
    // Snapshot the unwrapped plaintext so writeback can dump 1:1 in
    // the any-raw case.
    origPlainBytes_ = std::move(plain);
}

mj::Json TblFile::DecodeRow(const std::vector<uint8_t>& buf, size_t rowOff,
                            const FieldList& fields) {
    mj::Json out = mj::Json::MakeObj();
    size_t cur = rowOff;
    for (const auto& f : fields.fields) {
        const auto& fname = f.name;
        const auto& ft    = f.dataType;
        switch (ft.kind) {
            case TblBaseKind::Byte:    case TblBaseKind::UByte:
            case TblBaseKind::Short:   case TblBaseKind::UShort:
            case TblBaseKind::Int:     case TblBaseKind::UInt:
            case TblBaseKind::Long:    case TblBaseKind::ULong:
            case TblBaseKind::Float: {
                out.AsObj().push_back({fname, ReadPrim(buf, cur, ft.kind)});
                cur += FieldTypeSize(ft);
                break;
            }
            case TblBaseKind::TOffset: {
                int64_t strOff = ReadPrimInt(buf, cur, TblBaseKind::ULong);
                cur += 8;
                std::string s;
                if (strOff > 0 && (size_t)strOff < buf.size()) {
                    s = ReadStringZ(buf, (size_t)strOff);
                }
                out.AsObj().push_back({fname, mj::Json::MakeStr(std::move(s))});
                break;
            }
            case TblBaseKind::U8Array:
            case TblBaseKind::U16Array:
            case TblBaseKind::U32Array: {
                int64_t arrOff = ReadPrimInt(buf, cur, TblBaseKind::ULong); cur += 8;
                int64_t arrCnt = ReadPrimInt(buf, cur, TblBaseKind::UInt);  cur += 4;
                int elemSize = (ft.kind == TblBaseKind::U8Array)  ? 1 :
                               (ft.kind == TblBaseKind::U16Array) ? 2 : 4;
                if (arrCnt < 0 || arrCnt > 1048576) {
                    throw BadType("array count " + std::to_string(arrCnt) +
                                  " out of range at field \"" + fname + "\"");
                }
                if (arrCnt > 0
                    && (arrOff < 0
                        || (size_t)(arrOff + arrCnt * elemSize) > buf.size())) {
                    throw BadType("array off=" + std::to_string(arrOff) +
                                  " cnt=" + std::to_string(arrCnt) +
                                  " step=" + std::to_string(elemSize) +
                                  " exceeds buffer at \"" + fname + "\"");
                }
                mj::Json arr = mj::Json::MakeArr();
                for (int64_t k = 0; k < arrCnt; ++k) {
                    int64_t v = 0;
                    size_t off = (size_t)(arrOff + k * elemSize);
                    switch (ft.kind) {
                        case TblBaseKind::U8Array:
                            v = buf[off]; break;
                        case TblBaseKind::U16Array:
                            v = ReadPrimInt(buf, off, TblBaseKind::UShort); break;
                        case TblBaseKind::U32Array:
                            v = ReadPrimInt(buf, off, TblBaseKind::UInt); break;
                        default: break;
                    }
                    arr.AsArr().push_back(mj::Json::MakeInt(v));
                }
                out.AsObj().push_back({fname, std::move(arr)});
                break;
            }
            case TblBaseKind::Nested: {
                if (!ft.nestedFields) throw BadType("nested missing fields");
                out.AsObj().push_back({
                    fname,
                    DecodeNested(buf, cur, ft.nestedSize, *ft.nestedFields)});
                cur += FieldTypeSize(ft);
                break;
            }
        }
    }
    return out;
}

mj::Json TblFile::DecodeNested(const std::vector<uint8_t>& buf, size_t rowOff,
                               int nestedSize, const FieldList& fields) {
    mj::Json arr = mj::Json::MakeArr();
    int childSize = FieldListSize(fields);
    if (childSize <= 0 || nestedSize <= 0) return arr;
    for (int i = 0; i < nestedSize; ++i) {
        size_t childOff = rowOff + (size_t)i * (size_t)childSize;
        arr.AsArr().push_back(DecodeRow(buf, childOff, fields));
    }
    return arr;
}

// ---------------------------------------------------------------------------
//  ToJson — emit KuroTools' { headers: [...], data: [...] } shape
// ---------------------------------------------------------------------------
static mj::Json BytesToHexArray(const std::vector<uint8_t>& b) {
    // Raw sections are emitted as a string of hex bytes so the user
    // can at least see them. KuroTools does the same.
    static const char* HEX = "0123456789abcdef";
    std::string s;
    s.reserve(b.size() * 2);
    for (uint8_t v : b) {
        s.push_back(HEX[v >> 4]);
        s.push_back(HEX[v & 0xF]);
    }
    return mj::Json::MakeStr(s);
}

mj::Json TblFile::ToJson() const {
    mj::Json out = mj::Json::MakeObj();
    mj::Json headers = mj::Json::MakeArr();
    mj::Json data    = mj::Json::MakeArr();

    for (const auto& s : sections_) {
        mj::Json hdr = mj::Json::MakeObj();
        hdr.At("name") = mj::Json::MakeStr(s.name);
        hdr.At("entry_length") = mj::Json::MakeInt(s.entryLength);
        if (!s.gameTag.empty())
            hdr.At("game") = mj::Json::MakeStr(s.gameTag);
        if (!s.platformKey.empty())
            hdr.At("platform") = mj::Json::MakeStr(s.platformKey);
        hdr.At("mode") = mj::Json::MakeStr(
            s.mode == TblSectionMode::Decoded ? "decoded" : "raw");
        headers.AsArr().push_back(std::move(hdr));

        mj::Json sec = mj::Json::MakeObj();
        sec.At("name") = mj::Json::MakeStr(s.name);
        if (s.mode == TblSectionMode::Decoded) {
            sec.At("data") = s.rows;
        } else {
            // Raw bytes -> hex string under "raw".
            sec.At("raw") = BytesToHexArray(s.rawBytes);
        }
        data.AsArr().push_back(std::move(sec));
    }
    out.At("headers") = std::move(headers);
    out.At("data")    = std::move(data);
    return out;
}

// ===========================================================================
//  Write path (Phase 2 — JSON edit -> repack -> file)
// ===========================================================================
namespace {

// Append-only byte buffer with simple little-endian writers.
struct ByteBuilder {
    std::vector<uint8_t> buf;
    void U8 (uint8_t v)  { buf.push_back(v); }
    void U16(uint16_t v) { buf.push_back((uint8_t)v); buf.push_back((uint8_t)(v >> 8)); }
    void U32(uint32_t v) { U16((uint16_t)v); U16((uint16_t)(v >> 16)); }
    void U64(uint64_t v) { U32((uint32_t)v); U32((uint32_t)(v >> 32)); }
    void F32(float v)    { uint32_t bits; std::memcpy(&bits, &v, 4); U32(bits); }
    void Pad(size_t n)   { buf.insert(buf.end(), n, 0); }
    void Bytes(const uint8_t* p, size_t n) { buf.insert(buf.end(), p, p + n); }
    size_t Size() const { return buf.size(); }
};

struct PackCtx {
    ByteBuilder* body;
    ByteBuilder* data2;
    int64_t      data2StartOffset;
};

// Robustly extract an integer from a Json value (Int, Real, or
// numeric String). Permissive on input because hand-edited JSON
// often round-trips through a string.
int64_t AsIntLike(const mj::Json* j) {
    if (!j) return 0;
    if (j->IsInt())  return j->AsInt();
    if (j->IsReal()) return (int64_t)j->AsReal();
    if (j->IsStr())  return std::strtoll(j->AsStr().c_str(), nullptr, 10);
    if (j->IsBool()) return j->AsBool() ? 1 : 0;
    return 0;
}
double AsRealLike(const mj::Json* j) {
    if (!j) return 0.0;
    if (j->IsReal()) return j->AsReal();
    if (j->IsInt())  return (double)j->AsInt();
    if (j->IsStr())  return std::strtod(j->AsStr().c_str(), nullptr);
    return 0.0;
}

void PackData(PackCtx& ctx, const TblDataType& ft, const mj::Json* j);

void PackPrim(PackCtx& ctx, const TblDataType& ft, const mj::Json* j) {
    if (ft.kind == TblBaseKind::Float) {
        ctx.body->F32((float)AsRealLike(j));
        return;
    }
    int64_t v = AsIntLike(j);
    switch (ft.kind) {
        case TblBaseKind::Byte:    case TblBaseKind::UByte:
            ctx.body->U8 ((uint8_t)v);  break;
        case TblBaseKind::Short:   case TblBaseKind::UShort:
            ctx.body->U16((uint16_t)v); break;
        case TblBaseKind::Int:     case TblBaseKind::UInt:
            ctx.body->U32((uint32_t)v); break;
        case TblBaseKind::Long:    case TblBaseKind::ULong:
            ctx.body->U64((uint64_t)v); break;
        default:
            throw BadType("PackPrim: bad kind");
    }
}

void PackTOffset(PackCtx& ctx, const TblDataType& /*ft*/, const mj::Json* j) {
    // data2 byte position is the absolute offset stored in the row.
    std::string s;
    if (j) {
        if (j->IsStr()) s = j->AsStr();
        else if (j->IsInt())  s = std::to_string(j->AsInt());
        else if (j->IsReal()) s = std::to_string(j->AsReal());
    }
    int64_t strOff = (int64_t)ctx.data2->Size() + ctx.data2StartOffset;
    ctx.body->U64((uint64_t)strOff);
    if (!s.empty()) {
        ctx.data2->Bytes((const uint8_t*)s.data(), s.size());
    }
    ctx.data2->U8(0);   // NUL terminator
}

void PackArray(PackCtx& ctx, const TblDataType& ft, const mj::Json* j) {
    int elemSize = (ft.kind == TblBaseKind::U8Array)  ? 1 :
                   (ft.kind == TblBaseKind::U16Array) ? 2 : 4;

    // KuroTools' packer aligns the data2 cursor to elemSize before
    // recording the array offset (even for empty arrays).
    size_t pad = ctx.data2->Size() % (size_t)elemSize;
    if (pad > 0) ctx.data2->Pad((size_t)elemSize - pad);

    int64_t arrOff = (int64_t)ctx.data2->Size() + ctx.data2StartOffset;
    ctx.body->U64((uint64_t)arrOff);

    if (j && j->IsArr()) {
        const auto& a = j->AsArr();
        ctx.body->U32((uint32_t)a.size());
        for (const auto& el : a) {
            int64_t v = AsIntLike(&el);
            switch (ft.kind) {
                case TblBaseKind::U8Array:  ctx.data2->U8 ((uint8_t)v);  break;
                case TblBaseKind::U16Array: ctx.data2->U16((uint16_t)v); break;
                case TblBaseKind::U32Array: ctx.data2->U32((uint32_t)v); break;
                default: break;
            }
        }
    } else {
        ctx.body->U32(0);
    }
}

void PackNested(PackCtx& ctx, const TblDataType& ft, const mj::Json* j) {
    if (!ft.nestedFields) throw BadType("PackNested: missing fields");
    if (!j || !j->IsArr()) {
        throw BadType("PackNested: expected JSON array of nested rows");
    }
    const auto& a = j->AsArr();
    if ((int)a.size() != ft.nestedSize) {
        throw BadType("PackNested: got " + std::to_string(a.size())
                      + " rows, schema requires " + std::to_string(ft.nestedSize));
    }
    for (int i = 0; i < ft.nestedSize; ++i) {
        if (!a[i].IsObj()) throw BadType("PackNested: row not an object");
        for (const auto& f : ft.nestedFields->fields) {
            const mj::Json* val = a[i].Find(f.name);
            PackData(ctx, f.dataType, val);
        }
    }
}

void PackData(PackCtx& ctx, const TblDataType& ft, const mj::Json* j) {
    switch (ft.kind) {
        case TblBaseKind::Byte:    case TblBaseKind::UByte:
        case TblBaseKind::Short:   case TblBaseKind::UShort:
        case TblBaseKind::Int:     case TblBaseKind::UInt:
        case TblBaseKind::Long:    case TblBaseKind::ULong:
        case TblBaseKind::Float:
            PackPrim(ctx, ft, j); break;
        case TblBaseKind::TOffset:
            PackTOffset(ctx, ft, j); break;
        case TblBaseKind::U8Array:
        case TblBaseKind::U16Array:
        case TblBaseKind::U32Array:
            PackArray(ctx, ft, j); break;
        case TblBaseKind::Nested:
            PackNested(ctx, ft, j); break;
    }
}

bool WriteAllFile(const std::wstring& path, const uint8_t* data, size_t len) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr,
                           CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD written = 0;
    BOOL ok = TRUE;
    if (len > 0) ok = WriteFile(h, data, (DWORD)len, &written, nullptr);
    CloseHandle(h);
    return ok && written == (DWORD)len;
}

} // namespace

void TblFile::FromJson(const mj::Json& obj) {
    if (!obj.IsObj()) throw TblError("FromJson: top-level not an object");
    const mj::Json* dataArr = obj.Find("data");
    if (!dataArr || !dataArr->IsArr()) {
        throw TblError("FromJson: missing or non-array \"data\" field");
    }
    const auto& items = dataArr->AsArr();
    if (items.size() != sections_.size()) {
        throw TblError("FromJson: data has " + std::to_string(items.size())
                       + " sections, expected " + std::to_string(sections_.size()));
    }

    for (size_t i = 0; i < sections_.size(); ++i) {
        if (!items[i].IsObj()) {
            throw TblError("FromJson: data[" + std::to_string(i)
                           + "] is not an object");
        }
        const mj::Json* nameJ = items[i].Find("name");
        std::string itemName = (nameJ && nameJ->IsStr()) ? nameJ->AsStr() : "";
        if (itemName != sections_[i].name) {
            throw TblError("FromJson: data[" + std::to_string(i) + "].name=\""
                           + itemName + "\" does not match section \""
                           + sections_[i].name + "\"");
        }
        // Raw sections can't be edited via JSON — schema unknown.
        if (sections_[i].mode == TblSectionMode::Raw) continue;

        const mj::Json* rows = items[i].Find("data");
        if (!rows || !rows->IsArr()) {
            throw TblError("FromJson: data[" + std::to_string(i)
                           + "].data is not an array");
        }
        sections_[i].rows = *rows;
    }
}

void TblFile::WriteToFile(const std::wstring& path) {
    // Verbatim passthrough mode: any raw section means we can't safely
    // re-emit, since raw rows may reference data2 offsets we'd move.
    if (anyRawSection_ && !origPlainBytes_.empty()) {
        if (!WriteAllFile(path, origPlainBytes_.data(), origPlainBytes_.size())) {
            throw TblError("WriteToFile: cannot create output file");
        }
        return;
    }

    // Phase 1: compute section start offsets.
    // Layout: 8-byte head + 80-byte directory entry per section + rows.
    uint32_t curOff = 8 + (uint32_t)(sections_.size() * 80);
    std::vector<uint32_t> sectionStarts(sections_.size());
    for (size_t i = 0; i < sections_.size(); ++i) {
        sectionStarts[i] = curOff;
        uint32_t rowCount = 0;
        if (sections_[i].mode == TblSectionMode::Decoded) {
            rowCount = (uint32_t)sections_[i].rows.AsArr().size();
        } else if (sections_[i].entryLength > 0) {
            rowCount = (uint32_t)(sections_[i].rawBytes.size()
                                  / (size_t)sections_[i].entryLength);
        }
        curOff += (uint32_t)sections_[i].entryLength * rowCount;
    }

    // Header + body + data2 builders.
    ByteBuilder header, body, data2;
    PackCtx ctx{ &body, &data2, (int64_t)curOff };

    // Phase 2: emit the file header (#TBL + count + N x 80-byte dir entry).
    header.U8('#'); header.U8('T'); header.U8('B'); header.U8('L');
    header.U32((uint32_t)sections_.size());

    for (size_t i = 0; i < sections_.size(); ++i) {
        const auto& s = sections_[i];
        // 64-byte NUL-padded name
        uint8_t nameBuf[64] = {};
        size_t nlen = (s.name.size() > 64) ? 64 : s.name.size();
        if (nlen > 0) std::memcpy(nameBuf, s.name.data(), nlen);
        header.Bytes(nameBuf, 64);

        // CRC32 of the section name (zlib-style, no final XOR).
        uint32_t crc = Crc32Pac(s.name.data(), s.name.size());
        header.U32(crc);
        header.U32(sectionStarts[i]);
        header.U32((uint32_t)s.entryLength);
        uint32_t rowCount = 0;
        if (s.mode == TblSectionMode::Decoded) {
            rowCount = (uint32_t)s.rows.AsArr().size();
        } else if (s.entryLength > 0) {
            rowCount = (uint32_t)(s.rawBytes.size() / (size_t)s.entryLength);
        }
        header.U32(rowCount);
    }

    // Phase 3: emit row data, accumulate data2.
    for (size_t i = 0; i < sections_.size(); ++i) {
        const auto& s = sections_[i];
        if (s.mode == TblSectionMode::Raw) {
            body.Bytes(s.rawBytes.data(), s.rawBytes.size());
            continue;
        }
        // Find the matching schema variant again. The user may have
        // edited rows but the schema must still resolve.
        const SchemaVariant* var = schemaDb_
            ? schemaDb_->FindVariant(s.name, s.entryLength, s.gameTag)
            : nullptr;
        if (!var || !var->fields) {
            throw TblError("WriteToFile: schema for \"" + s.name
                           + "\" len=" + std::to_string(s.entryLength)
                           + " disappeared between read and write");
        }
        for (size_t r = 0; r < s.rows.AsArr().size(); ++r) {
            const mj::Json& rowJ = s.rows.AsArr()[r];
            if (!rowJ.IsObj()) {
                throw TblError("WriteToFile: section \"" + s.name + "\" row "
                               + std::to_string(r) + " is not an object");
            }
            size_t before = body.Size();
            for (const auto& f : var->fields->fields) {
                const mj::Json* fld = rowJ.Find(f.name);
                PackData(ctx, f.dataType, fld);
            }
            // Sanity: emitted exactly entryLength bytes for this row.
            int64_t emitted = (int64_t)body.Size() - (int64_t)before;
            if (emitted != s.entryLength) {
                throw TblError("WriteToFile: section \"" + s.name + "\" row "
                               + std::to_string(r) + " emitted "
                               + std::to_string(emitted) + " bytes (expected "
                               + std::to_string(s.entryLength) + ")");
            }
        }
    }

    // Phase 4: concatenate + write to disk.
    std::vector<uint8_t> outBuf;
    outBuf.reserve(header.Size() + body.Size() + data2.Size());
    outBuf.insert(outBuf.end(), header.buf.begin(), header.buf.end());
    outBuf.insert(outBuf.end(), body.buf.begin(),   body.buf.end());
    outBuf.insert(outBuf.end(), data2.buf.begin(),  data2.buf.end());

    if (!WriteAllFile(path, outBuf.data(), outBuf.size())) {
        throw TblError("WriteToFile: cannot create output file");
    }
}

} // namespace tbl
