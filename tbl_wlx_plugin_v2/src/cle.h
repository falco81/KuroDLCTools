// CLE wrapper for Falcom's Trails through Daybreak (Kuro 2 / Sora 1)
// file format. Files in those games may be:
//   F9BA <size:u32> <ciphertext>     blowfish-CTR encrypted
//   C9BA <size:u32> <ciphertext>     variant of F9BA (same key/IV)
//   D9BA <size:u32> <zstd payload>   zstd compressed
//
// Encryption and compression can stack. ProcessCLE peels them off
// until a non-CLE magic is reached.
#pragma once

#include <cstdint>
#include <vector>
#include <stdexcept>

namespace tbl {

class CLEError : public std::runtime_error {
public:
    explicit CLEError(const std::string& m) : std::runtime_error(m) {}
};

bool IsCLEWrapped(const std::vector<uint8_t>& input);

// Returns the unwrapped bytes. If the input doesn't start with a CLE
// magic, the input is returned unchanged. Throws on malformed input
// or zstd error.
std::vector<uint8_t> ProcessCLE(const std::vector<uint8_t>& input);

} // namespace tbl
