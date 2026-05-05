#include "crc32.h"

namespace tbl {

namespace {

constexpr uint32_t POLY = 0xEDB88320u;

struct Tab {
    uint32_t v[256];
    constexpr Tab() : v{} {
        for (int i = 0; i < 256; ++i) {
            uint32_t c = (uint32_t)i;
            for (int j = 0; j < 8; ++j) {
                c = (c & 1) ? ((c >> 1) ^ POLY) : (c >> 1);
            }
            v[i] = c;
        }
    }
};

constexpr Tab kTab;

} // namespace

uint32_t Crc32Pac(const void* buf, size_t len) {
    const uint8_t* p = (const uint8_t*)buf;
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; ++i) {
        c = (c >> 8) ^ kTab.v[(c ^ p[i]) & 0xFF];
    }
    // Match KuroTools / FPAC: return register state without final XOR
    // (= zlib_crc32 ^ 0xFFFFFFFF, which is what Python writes into the
    // FPAC entry table).
    return c;
}

} // namespace tbl
