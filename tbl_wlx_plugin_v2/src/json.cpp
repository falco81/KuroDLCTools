#include "json.h"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace mj {

namespace {

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------
class Parser {
public:
    Parser(const char* p, const char* end) : p_(p), end_(end) {}

    Json ParseValue() {
        SkipWs();
        if (p_ >= end_) Fail("unexpected end");
        char c = *p_;
        if (c == '{') return ParseObject();
        if (c == '[') return ParseArray();
        if (c == '"') return Json::MakeStr(ParseString());
        if (c == 't' || c == 'f') return ParseBool();
        if (c == 'n') { Expect("null"); return Json::MakeNull(); }
        if (c == '-' || (c >= '0' && c <= '9')) return ParseNumber();
        Fail("expected value");
        return Json::MakeNull();
    }

    void RequireEof() {
        SkipWs();
        if (p_ != end_) Fail("trailing characters");
    }

private:
    const char* p_;
    const char* end_;

    [[noreturn]] void Fail(const char* msg) {
        size_t off = (size_t)(p_ - p0_());
        char buf[160];
        std::snprintf(buf, sizeof(buf), "JSON parse error at offset %zu: %s",
                      off, msg);
        throw JParseError(buf);
    }
    const char* p0_() {
        // We can't recover the original start without storing it; use a
        // best-effort offset in error messages.
        return nullptr;
    }

    void SkipWs() {
        while (p_ < end_) {
            char c = *p_;
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') ++p_;
            else break;
        }
    }
    void Expect(const char* lit) {
        size_t n = std::strlen(lit);
        if ((size_t)(end_ - p_) < n || std::memcmp(p_, lit, n) != 0) {
            Fail("expected literal");
        }
        p_ += n;
    }

    Json ParseObject() {
        Json out = Json::MakeObj();
        ++p_;            // consume '{'
        SkipWs();
        if (p_ < end_ && *p_ == '}') { ++p_; return out; }
        for (;;) {
            SkipWs();
            if (p_ >= end_ || *p_ != '"') Fail("expected string key");
            std::string key = ParseString();
            SkipWs();
            if (p_ >= end_ || *p_ != ':') Fail("expected ':'");
            ++p_;
            out.AsObj().push_back({std::move(key), ParseValue()});
            SkipWs();
            if (p_ >= end_) Fail("unterminated object");
            if (*p_ == ',') { ++p_; continue; }
            if (*p_ == '}') { ++p_; return out; }
            Fail("expected ',' or '}'");
        }
    }

    Json ParseArray() {
        Json out = Json::MakeArr();
        ++p_;            // consume '['
        SkipWs();
        if (p_ < end_ && *p_ == ']') { ++p_; return out; }
        for (;;) {
            out.AsArr().push_back(ParseValue());
            SkipWs();
            if (p_ >= end_) Fail("unterminated array");
            if (*p_ == ',') { ++p_; SkipWs(); continue; }
            if (*p_ == ']') { ++p_; return out; }
            Fail("expected ',' or ']'");
        }
    }

    std::string ParseString() {
        if (*p_ != '"') Fail("expected '\"'");
        ++p_;
        std::string s;
        while (p_ < end_) {
            unsigned char c = (unsigned char)*p_++;
            if (c == '"') return s;
            if (c == '\\') {
                if (p_ >= end_) Fail("dangling escape");
                char e = *p_++;
                switch (e) {
                    case '"':  s.push_back('"');  break;
                    case '\\': s.push_back('\\'); break;
                    case '/':  s.push_back('/');  break;
                    case 'b':  s.push_back('\b'); break;
                    case 'f':  s.push_back('\f'); break;
                    case 'n':  s.push_back('\n'); break;
                    case 'r':  s.push_back('\r'); break;
                    case 't':  s.push_back('\t'); break;
                    case 'u': {
                        if (p_ + 4 > end_) Fail("bad \\u");
                        unsigned cp = 0;
                        for (int i = 0; i < 4; ++i) {
                            char hc = *p_++;
                            cp <<= 4;
                            if (hc >= '0' && hc <= '9') cp |= (hc - '0');
                            else if (hc >= 'a' && hc <= 'f') cp |= (hc - 'a' + 10);
                            else if (hc >= 'A' && hc <= 'F') cp |= (hc - 'A' + 10);
                            else Fail("bad \\u hex");
                        }
                        // Surrogate pair?
                        if (cp >= 0xD800 && cp <= 0xDBFF
                            && p_ + 6 <= end_
                            && p_[0] == '\\' && p_[1] == 'u') {
                            unsigned low = 0;
                            const char* q = p_ + 2;
                            for (int i = 0; i < 4; ++i) {
                                char hc = *q++;
                                low <<= 4;
                                if (hc >= '0' && hc <= '9') low |= (hc - '0');
                                else if (hc >= 'a' && hc <= 'f') low |= (hc - 'a' + 10);
                                else if (hc >= 'A' && hc <= 'F') low |= (hc - 'A' + 10);
                                else { low = 0xFFFFFFFF; break; }
                            }
                            if (low != 0xFFFFFFFF && low >= 0xDC00 && low <= 0xDFFF) {
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
                                p_ += 6;
                            }
                        }
                        // Encode codepoint as UTF-8
                        if (cp < 0x80) {
                            s.push_back((char)cp);
                        } else if (cp < 0x800) {
                            s.push_back((char)(0xC0 | (cp >> 6)));
                            s.push_back((char)(0x80 | (cp & 0x3F)));
                        } else if (cp < 0x10000) {
                            s.push_back((char)(0xE0 | (cp >> 12)));
                            s.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
                            s.push_back((char)(0x80 | (cp & 0x3F)));
                        } else {
                            s.push_back((char)(0xF0 | (cp >> 18)));
                            s.push_back((char)(0x80 | ((cp >> 12) & 0x3F)));
                            s.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
                            s.push_back((char)(0x80 | (cp & 0x3F)));
                        }
                        break;
                    }
                    default: Fail("bad escape");
                }
            } else if (c < 0x20) {
                Fail("control char in string");
            } else {
                s.push_back((char)c);
            }
        }
        Fail("unterminated string");
    }

    Json ParseBool() {
        if (*p_ == 't') { Expect("true");  return Json::MakeBool(true); }
        if (*p_ == 'f') { Expect("false"); return Json::MakeBool(false); }
        Fail("bad bool");
        return Json::MakeNull();
    }

    Json ParseNumber() {
        const char* start = p_;
        if (*p_ == '-') ++p_;
        while (p_ < end_ && *p_ >= '0' && *p_ <= '9') ++p_;
        bool isFloat = false;
        if (p_ < end_ && *p_ == '.') {
            isFloat = true;
            ++p_;
            while (p_ < end_ && *p_ >= '0' && *p_ <= '9') ++p_;
        }
        if (p_ < end_ && (*p_ == 'e' || *p_ == 'E')) {
            isFloat = true;
            ++p_;
            if (p_ < end_ && (*p_ == '+' || *p_ == '-')) ++p_;
            while (p_ < end_ && *p_ >= '0' && *p_ <= '9') ++p_;
        }
        std::string tok(start, p_);
        if (isFloat) {
            return Json::MakeReal(std::strtod(tok.c_str(), nullptr));
        }
        // Integer — fits in int64_t? Otherwise fall back to double so
        // we don't lose data silently for very wide values.
        char* endp = nullptr;
        long long v = std::strtoll(tok.c_str(), &endp, 10);
        if (endp == tok.c_str() + tok.size()) {
            return Json::MakeInt((int64_t)v);
        }
        return Json::MakeReal(std::strtod(tok.c_str(), nullptr));
    }
};

// ---------------------------------------------------------------------------
// Writer
// ---------------------------------------------------------------------------
void DumpString(std::string& out, const std::string& s) {
    out.push_back('"');
    for (unsigned char c : s) {
        switch (c) {
            case '"':  out.append("\\\""); break;
            case '\\': out.append("\\\\"); break;
            case '\b': out.append("\\b");  break;
            case '\f': out.append("\\f");  break;
            case '\n': out.append("\\n");  break;
            case '\r': out.append("\\r");  break;
            case '\t': out.append("\\t");  break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out.append(buf);
                } else {
                    out.push_back((char)c);
                }
        }
    }
    out.push_back('"');
}

void DumpInner(std::string& out, const Json& v, int indent, int level) {
    auto NL = [&]() {
        if (indent > 0) {
            out.push_back('\n');
            out.append((size_t)(indent * level), ' ');
        }
    };
    switch (v.Kind()) {
        case JKind::Null:  out.append("null"); break;
        case JKind::Bool:  out.append(v.AsBool() ? "true" : "false"); break;
        case JKind::Int: {
            char buf[32];
            std::snprintf(buf, sizeof(buf), "%lld", (long long)v.AsInt());
            out.append(buf);
            break;
        }
        case JKind::Real: {
            char buf[64];
            double d = v.AsReal();
            // Compact, deterministic %g — but ensure it round-trips through
            // a parser, by using %.17g if a short form loses info.
            std::snprintf(buf, sizeof(buf), "%.17g", d);
            out.append(buf);
            break;
        }
        case JKind::Str:  DumpString(out, v.AsStr()); break;
        case JKind::Arr: {
            const auto& a = v.AsArr();
            if (a.empty()) { out.append("[]"); break; }
            out.push_back('[');
            for (size_t i = 0; i < a.size(); ++i) {
                if (i > 0) out.push_back(',');
                if (indent > 0) {
                    out.push_back('\n');
                    out.append((size_t)(indent * (level + 1)), ' ');
                }
                DumpInner(out, a[i], indent, level + 1);
            }
            NL();
            out.push_back(']');
            break;
        }
        case JKind::Obj: {
            const auto& o = v.AsObj();
            if (o.empty()) { out.append("{}"); break; }
            out.push_back('{');
            for (size_t i = 0; i < o.size(); ++i) {
                if (i > 0) out.push_back(',');
                if (indent > 0) {
                    out.push_back('\n');
                    out.append((size_t)(indent * (level + 1)), ' ');
                }
                DumpString(out, o[i].first);
                out.push_back(':');
                if (indent > 0) out.push_back(' ');
                DumpInner(out, o[i].second, indent, level + 1);
            }
            NL();
            out.push_back('}');
            break;
        }
    }
}

} // namespace

Json Parse(const std::string& text) {
    Parser p(text.data(), text.data() + text.size());
    Json v = p.ParseValue();
    p.RequireEof();
    return v;
}

std::string Dump(const Json& v, int indentSpaces) {
    std::string out;
    DumpInner(out, v, indentSpaces, 0);
    return out;
}

} // namespace mj
