// Blowfish-64 cipher with the CLE key schedule used by Falcom's CLE
// engine (Trails through Daybreak / Kuro 2). Implements ECB block
// encrypt/decrypt and CTR mode.
//
// C++ port of the Pascal blowfish unit, which itself is a port of
// Jashandeep Sohi's pure-Python blowfish module (GPL-3+) as used by
// KuroTools' lib/blowfish.py. The cipher is byte-for-byte equivalent.
#pragma once

#include <cstdint>
#include <vector>
#include <stdexcept>

namespace tbl {

// Blowfish state after key schedule. Re-usable for many encrypt/decrypt
// calls.
struct Blowfish {
    uint32_t P[18];
    uint32_t S[4][256];
};

class BlowfishError : public std::runtime_error {
public:
    explicit BlowfishError(const std::string& m) : std::runtime_error(m) {}
};

// Initialise the cipher with a key (4..56 bytes). Performs the
// 521-iteration Blowfish key schedule. Cost is paid once per cipher
// instance — make sure to cache.
void BlowfishInit(Blowfish& bf, const uint8_t* key, size_t keyLen);

// Encrypt / decrypt a single 8-byte block in-place. Block is treated
// as big-endian (matches CLE's ">Q" struct format).
void BlowfishEncryptBlock(const Blowfish& bf, uint8_t block[8]);
void BlowfishDecryptBlock(const Blowfish& bf, uint8_t block[8]);

// CTR mode using the CLE counter convention:
//     keystream_block_i = E(nonce + i)  for i = 0, 1, 2, ...
// Output is XOR of plaintext with the concatenated keystream.
// `nonce` is a 64-bit big-endian integer; `startCounter` lets you
// resume mid-stream.
void BlowfishCTR(const Blowfish& bf, uint64_t nonce,
                 const std::vector<uint8_t>& input,
                 std::vector<uint8_t>& output,
                 uint64_t startCounter);

} // namespace tbl
