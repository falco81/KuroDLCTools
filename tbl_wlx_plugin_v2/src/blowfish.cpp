#include "blowfish.h"
#include "blowfish_const.h"

#include <cstring>

namespace tbl {

namespace {

inline uint32_t FeistelF(const uint32_t S[4][256], uint32_t W) {
    uint8_t a = (uint8_t)(W >> 24);
    uint8_t b = (uint8_t)((W >> 16) & 0xFF);
    uint8_t c = (uint8_t)((W >> 8)  & 0xFF);
    uint8_t d = (uint8_t)( W        & 0xFF);
    return ((S[0][a] + S[1][b]) ^ S[2][c]) + S[3][d];
}

inline void EncryptLR(const uint32_t P[18], const uint32_t S[4][256],
                      uint32_t& L, uint32_t& R) {
    // 8 Feistel iterations of 2 rounds each, consuming P[0..15] in pairs.
    for (int i = 0; i < 16; i += 2) {
        L ^= P[i];
        R ^= FeistelF(S, L);
        R ^= P[i + 1];
        L ^= FeistelF(S, R);
    }
    // Final P[16],P[17] XOR + swap.
    uint32_t T = R ^ P[17];
    R = L ^ P[16];
    L = T;
}

inline void DecryptLR(const uint32_t P[18], const uint32_t S[4][256],
                      uint32_t& L, uint32_t& R) {
    for (int i = 16; i >= 2; i -= 2) {
        L ^= P[i + 1];
        R ^= FeistelF(S, L);
        R ^= P[i];
        L ^= FeistelF(S, R);
    }
    uint32_t T = R ^ P[0];
    R = L ^ P[1];
    L = T;
}

inline void PackBE(uint64_t v, uint8_t out[8]) {
    out[0] = (uint8_t)(v >> 56); out[1] = (uint8_t)(v >> 48);
    out[2] = (uint8_t)(v >> 40); out[3] = (uint8_t)(v >> 32);
    out[4] = (uint8_t)(v >> 24); out[5] = (uint8_t)(v >> 16);
    out[6] = (uint8_t)(v >> 8);  out[7] = (uint8_t)(v);
}

} // namespace

// ---------------------------------------------------------------------------
//   Key schedule
// ---------------------------------------------------------------------------
void BlowfishInit(Blowfish& bf, const uint8_t* key, size_t keyLen) {
    if (keyLen < 4 || keyLen > 56) {
        throw BlowfishError("Blowfish key must be 4..56 bytes");
    }

    // P-array initialised from PI digits XOR'd with cyclic 32-bit
    // groups of the key.
    size_t keyIdx = 0;
    for (int i = 0; i < 18; ++i) {
        uint32_t k = 0;
        for (int j = 0; j < 4; ++j) {
            k = (k << 8) | key[keyIdx];
            keyIdx = (keyIdx + 1) % keyLen;
        }
        bf.P[i] = PI_P[i] ^ k;
    }

    // S-boxes initialised from PI digits.
    std::memcpy(bf.S[0], PI_S1, sizeof(PI_S1));
    std::memcpy(bf.S[1], PI_S2, sizeof(PI_S2));
    std::memcpy(bf.S[2], PI_S3, sizeof(PI_S3));
    std::memcpy(bf.S[3], PI_S4, sizeof(PI_S4));

    // Run the schedule: encrypt the all-zero block, replace P[0..1]
    // with the result, encrypt again, replace P[2..3], etc. Then do
    // the same for each S-box pair.
    uint32_t L = 0, R = 0;
    for (int i = 0; i < 9; ++i) {
        EncryptLR(bf.P, bf.S, L, R);
        bf.P[i * 2]     = L;
        bf.P[i * 2 + 1] = R;
    }
    for (int box = 0; box < 4; ++box) {
        for (int i = 0; i < 128; ++i) {
            EncryptLR(bf.P, bf.S, L, R);
            bf.S[box][i * 2]     = L;
            bf.S[box][i * 2 + 1] = R;
        }
    }
}

// ---------------------------------------------------------------------------
//   Public block API (big-endian I/O)
// ---------------------------------------------------------------------------
void BlowfishEncryptBlock(const Blowfish& bf, uint8_t block[8]) {
    uint32_t L = ((uint32_t)block[0] << 24) | ((uint32_t)block[1] << 16)
               | ((uint32_t)block[2] << 8)  |  (uint32_t)block[3];
    uint32_t R = ((uint32_t)block[4] << 24) | ((uint32_t)block[5] << 16)
               | ((uint32_t)block[6] << 8)  |  (uint32_t)block[7];
    EncryptLR(bf.P, bf.S, L, R);
    block[0] = (uint8_t)(L >> 24); block[1] = (uint8_t)(L >> 16);
    block[2] = (uint8_t)(L >> 8);  block[3] = (uint8_t)(L);
    block[4] = (uint8_t)(R >> 24); block[5] = (uint8_t)(R >> 16);
    block[6] = (uint8_t)(R >> 8);  block[7] = (uint8_t)(R);
}

void BlowfishDecryptBlock(const Blowfish& bf, uint8_t block[8]) {
    uint32_t L = ((uint32_t)block[0] << 24) | ((uint32_t)block[1] << 16)
               | ((uint32_t)block[2] << 8)  |  (uint32_t)block[3];
    uint32_t R = ((uint32_t)block[4] << 24) | ((uint32_t)block[5] << 16)
               | ((uint32_t)block[6] << 8)  |  (uint32_t)block[7];
    DecryptLR(bf.P, bf.S, L, R);
    block[0] = (uint8_t)(L >> 24); block[1] = (uint8_t)(L >> 16);
    block[2] = (uint8_t)(L >> 8);  block[3] = (uint8_t)(L);
    block[4] = (uint8_t)(R >> 24); block[5] = (uint8_t)(R >> 16);
    block[6] = (uint8_t)(R >> 8);  block[7] = (uint8_t)(R);
}

// ---------------------------------------------------------------------------
//   CTR mode
// ---------------------------------------------------------------------------
void BlowfishCTR(const Blowfish& bf, uint64_t nonce,
                 const std::vector<uint8_t>& input,
                 std::vector<uint8_t>& output,
                 uint64_t startCounter) {
    output.assign(input.size(), 0);
    if (input.empty()) return;

    size_t fullBlocks = input.size() / 8;
    size_t extra      = input.size() % 8;
    uint64_t ctr      = startCounter;
    uint8_t  ctrBlock[8];

    for (size_t i = 0; i < fullBlocks; ++i) {
        PackBE(nonce + ctr, ctrBlock);
        BlowfishEncryptBlock(bf, ctrBlock);
        for (int k = 0; k < 8; ++k) {
            output[i * 8 + k] = (uint8_t)(input[i * 8 + k] ^ ctrBlock[k]);
        }
        ++ctr;
    }
    if (extra > 0) {
        PackBE(nonce + ctr, ctrBlock);
        BlowfishEncryptBlock(bf, ctrBlock);
        for (size_t k = 0; k < extra; ++k) {
            output[fullBlocks * 8 + k] =
                (uint8_t)(input[fullBlocks * 8 + k] ^ ctrBlock[k]);
        }
    }
}

} // namespace tbl
