#include "cle.h"
#include "blowfish.h"
#include "zstd/zstd.h"

#include <cstring>

namespace tbl {

namespace {

// Publicly-known CLE blowfish key + CTR nonce. Shared by every known
// CLE-encrypted Falcom release.
const uint8_t CLE_KEY[16] = {
    0x16, 0x4B, 0x7D, 0x0F, 0x4F, 0xA7, 0x4C, 0xAC,
    0xD3, 0x7A, 0x06, 0xD9, 0xF8, 0x6D, 0x20, 0x94
};
const uint64_t CLE_NONCE = 0x9D8F9DA14960CC4Cull;

// 4-byte magic prefixes (raw ASCII bytes in file).
inline bool MagicAt(const uint8_t* p, size_t n, const char m[5]) {
    if (n < 4) return false;
    return std::memcmp(p, m, 4) == 0;
}

void DecryptOneLayer(const std::vector<uint8_t>& in,
                     std::vector<uint8_t>& out) {
    if (in.size() < 8) throw CLEError("CLE: encrypted block too short");
    Blowfish bf;
    BlowfishInit(bf, CLE_KEY, sizeof(CLE_KEY));
    std::vector<uint8_t> body(in.begin() + 8, in.end());
    BlowfishCTR(bf, CLE_NONCE, body, out, 0);
}

void DecompressOneLayer(const std::vector<uint8_t>& in,
                        std::vector<uint8_t>& out) {
    if (in.size() < 8) throw CLEError("CLE: compressed block too short");
    const uint8_t* payload = in.data() + 8;
    size_t  payloadLen = in.size() - 8;

    size_t frameLen = ZSTD_findFrameCompressedSize(payload, payloadLen);
    if (ZSTD_isError(frameLen)) {
        throw CLEError("CLE: zstd findFrameCompressedSize failed");
    }
    unsigned long long contentSize =
        ZSTD_getFrameContentSize(payload, payloadLen);
    if (contentSize == ZSTD_CONTENTSIZE_UNKNOWN
        || contentSize == ZSTD_CONTENTSIZE_ERROR) {
        throw CLEError("CLE: zstd frame content size unknown or error");
    }
    out.assign((size_t)contentSize, 0);
    size_t decoded = ZSTD_decompress(out.data(), out.size(), payload, frameLen);
    if (ZSTD_isError(decoded)) {
        throw CLEError("CLE: zstd decompression failed");
    }
    out.resize(decoded);
}

} // namespace

bool IsCLEWrapped(const std::vector<uint8_t>& in) {
    return MagicAt(in.data(), in.size(), "F9BA")
        || MagicAt(in.data(), in.size(), "C9BA")
        || MagicAt(in.data(), in.size(), "D9BA");
}

std::vector<uint8_t> ProcessCLE(const std::vector<uint8_t>& input) {
    std::vector<uint8_t> cur = input;
    std::vector<uint8_t> next;
    // Peel up to 8 layers — real files have at most 2 (compress + encrypt).
    for (int iter = 0; iter < 8; ++iter) {
        if (MagicAt(cur.data(), cur.size(), "F9BA")
         || MagicAt(cur.data(), cur.size(), "C9BA")) {
            DecryptOneLayer(cur, next);
        } else if (MagicAt(cur.data(), cur.size(), "D9BA")) {
            DecompressOneLayer(cur, next);
        } else {
            break;
        }
        cur.swap(next);
        next.clear();
    }
    return cur;
}

} // namespace tbl
