// Minimal JSON parser / serializer, just enough for the TBL plugin's
// needs. We need to:
//   - read 363 small schema files (maps of strings/objects/arrays)
//   - emit a single big "headers" + "data" object representing the
//     decoded TBL file
//
// Not goals: streaming, exotic numeric formats, comments.
//
// Public API is the Json struct (a variant-like value) plus the free
// functions Parse() and Dump().
#pragma once

#include <cstdint>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace mj {

enum class JKind {
    Null, Bool, Int, Real, Str, Arr, Obj
};

class Json {
public:
    using Object = std::vector<std::pair<std::string, Json>>;   // ordered
    using Array  = std::vector<Json>;

    Json() : kind_(JKind::Null) {}
    static Json MakeNull()                 { Json v; v.kind_ = JKind::Null; return v; }
    static Json MakeBool(bool b)           { Json v; v.kind_ = JKind::Bool; v.b_ = b; return v; }
    static Json MakeInt(int64_t i)         { Json v; v.kind_ = JKind::Int;  v.i_ = i; return v; }
    static Json MakeReal(double d)         { Json v; v.kind_ = JKind::Real; v.d_ = d; return v; }
    static Json MakeStr(std::string s)     { Json v; v.kind_ = JKind::Str;  v.s_ = std::move(s); return v; }
    static Json MakeArr()                  { Json v; v.kind_ = JKind::Arr;  v.arr_ = std::make_shared<Array>();  return v; }
    static Json MakeObj()                  { Json v; v.kind_ = JKind::Obj;  v.obj_ = std::make_shared<Object>(); return v; }

    JKind Kind() const { return kind_; }
    bool IsNull()   const { return kind_ == JKind::Null; }
    bool IsBool()   const { return kind_ == JKind::Bool; }
    bool IsInt()    const { return kind_ == JKind::Int; }
    bool IsReal()   const { return kind_ == JKind::Real; }
    bool IsNumber() const { return kind_ == JKind::Int || kind_ == JKind::Real; }
    bool IsStr()    const { return kind_ == JKind::Str; }
    bool IsArr()    const { return kind_ == JKind::Arr; }
    bool IsObj()    const { return kind_ == JKind::Obj; }

    bool        AsBool() const { return b_; }
    int64_t     AsInt()  const { return kind_ == JKind::Real ? (int64_t)d_ : i_; }
    double      AsReal() const { return kind_ == JKind::Int  ? (double)i_  : d_; }
    const std::string& AsStr() const { return s_; }
    Array&             AsArr()       { return *arr_; }
    const Array&       AsArr() const { return *arr_; }
    Object&            AsObj()       { return *obj_; }
    const Object&      AsObj() const { return *obj_; }

    // Convenience: object lookups; nullptr-safe in spirit (returns
    // pointer rather than throwing).
    const Json* Find(const std::string& key) const {
        if (kind_ != JKind::Obj) return nullptr;
        for (const auto& kv : *obj_) {
            if (kv.first == key) return &kv.second;
        }
        return nullptr;
    }
    Json& At(const std::string& key) {     // creates if missing
        if (kind_ != JKind::Obj) {
            kind_ = JKind::Obj;
            obj_  = std::make_shared<Object>();
        }
        for (auto& kv : *obj_) {
            if (kv.first == key) return kv.second;
        }
        obj_->push_back({key, Json{}});
        return obj_->back().second;
    }

    void Push(Json v) {
        if (kind_ != JKind::Arr) {
            kind_ = JKind::Arr;
            arr_  = std::make_shared<Array>();
        }
        arr_->push_back(std::move(v));
    }

private:
    JKind kind_ = JKind::Null;
    bool        b_ = false;
    int64_t     i_ = 0;
    double      d_ = 0.0;
    std::string s_;
    std::shared_ptr<Array>  arr_;
    std::shared_ptr<Object> obj_;
};

class JParseError : public std::runtime_error {
public:
    explicit JParseError(const std::string& m) : std::runtime_error(m) {}
};

// Parse a JSON document. Throws JParseError on malformed input.
Json Parse(const std::string& text);

// Serialise. indentSpaces == 0 emits compact JSON; otherwise it uses
// that many spaces per level with newlines (KuroTools-style with
// tab-based files round-trips fine through this).
std::string Dump(const Json& v, int indentSpaces = 0);

} // namespace mj
