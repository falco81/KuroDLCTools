// zlib-style CRC32, used by Falcom's FPAC archive entries (and by us
// as the section name CRC inside #TBL files). We don't actually need
// it for read-only viewing, but it's tiny and round-trips with the
// upstream Pascal version exactly.
#pragma once

#include <cstdint>
#include <cstddef>

namespace tbl {

uint32_t Crc32Pac(const void* buf, size_t len);

} // namespace tbl
