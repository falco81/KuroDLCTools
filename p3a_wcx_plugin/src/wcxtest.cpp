// Test harness: load p3a.wcx64 like Total Commander would and walk the
// API: OpenArchive -> ReadHeaderEx loop -> ProcessFile(extract) -> CloseArchive.
//
// Compile (mingw):
//   x86_64-w64-mingw32-g++ -O2 -o wcxtest.exe wcxtest.cpp
//
// Run under wine64:
//   wine64 wcxtest.exe p3a.wcx64 archive.p3a /tmp/extract_dir

#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/stat.h>

struct THeaderDataExA {
    char  ArcName[1024];
    char  FileName[1024];
    long  Flags;
    long  PackSize;
    long  PackSizeHigh;
    long  UnpSize;
    long  UnpSizeHigh;
    long  HostOS;
    long  FileCRC;
    long  FileTime;
    long  UnpVer;
    long  Method;
    long  FileAttr;
    char* CmtBuf;
    int   CmtBufSize;
    int   CmtSize;
    int   CmtState;
};

struct TOpenArchiveData {
    const char* ArcName;
    int   OpenMode;
    int   OpenResult;
    char* CmtBuf;
    int   CmtBufSize;
    int   CmtSize;
    int   CmtState;
};

typedef HANDLE (__stdcall *POpenArchive)(TOpenArchiveData*);
typedef int    (__stdcall *PReadHeaderEx)(HANDLE, THeaderDataExA*);
typedef int    (__stdcall *PProcessFile)(HANDLE, int, const char*, const char*);
typedef int    (__stdcall *PCloseArchive)(HANDLE);
typedef int    (__stdcall *PGetPackerCaps)(void);
typedef BOOL   (__stdcall *PCanYouHandleThisFile)(const char*);

static void ensure_dir(const char* p) {
    char tmp[2048]; size_t L = strlen(p);
    if (L >= sizeof(tmp)) return;
    strcpy(tmp, p);
    for (size_t i = 1; i < L; ++i) {
        if (tmp[i] == '/' || tmp[i] == '\\') {
            char c = tmp[i]; tmp[i] = 0;
            mkdir(tmp);
            tmp[i] = c;
        }
    }
    mkdir(tmp);
}

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <p3a.wcx64> <archive.p3a> <extract_dir>\n", argv[0]);
        return 1;
    }
    const char* dll  = argv[1];
    const char* arc  = argv[2];
    const char* dest = argv[3];

    HMODULE H = LoadLibraryA(dll);
    if (!H) { fprintf(stderr, "LoadLibrary failed\n"); return 1; }

    POpenArchive  OpenArchive  = (POpenArchive)  GetProcAddress(H, "OpenArchive");
    PReadHeaderEx ReadHeaderEx = (PReadHeaderEx) GetProcAddress(H, "ReadHeaderEx");
    PProcessFile  ProcessFile  = (PProcessFile)  GetProcAddress(H, "ProcessFile");
    PCloseArchive CloseArchive = (PCloseArchive) GetProcAddress(H, "CloseArchive");
    PGetPackerCaps GetPackerCaps = (PGetPackerCaps) GetProcAddress(H, "GetPackerCaps");
    PCanYouHandleThisFile Can = (PCanYouHandleThisFile) GetProcAddress(H, "CanYouHandleThisFile");

    if (!OpenArchive || !ReadHeaderEx || !ProcessFile || !CloseArchive
        || !GetPackerCaps || !Can) {
        fprintf(stderr, "missing exports\n"); return 1;
    }

    printf("GetPackerCaps()        = 0x%x\n", GetPackerCaps());
    printf("CanYouHandleThisFile() = %d\n",  Can(arc));

    TOpenArchiveData od = {};
    od.ArcName  = arc;
    od.OpenMode = 1; // PK_OM_EXTRACT
    HANDLE h = OpenArchive(&od);
    if (!h) { fprintf(stderr, "OpenArchive failed, OpenResult=%d\n", od.OpenResult); return 1; }
    printf("OpenArchive            = ok\n");

    int n_total = 0, n_ok = 0;
    THeaderDataExA hd = {};
    while (ReadHeaderEx(h, &hd) == 0) {
        ++n_total;
        char dpath[2048]; snprintf(dpath, sizeof(dpath), "%s\\", dest);
        ensure_dir(dest);
        int rc = ProcessFile(h, 2 /*PK_EXTRACT*/, dpath, hd.FileName);
        if (rc == 0) ++n_ok;
        else if (n_total <= 5)
            printf("  ProcessFile rc=%d for %s\n", rc, hd.FileName);
        memset(&hd, 0, sizeof(hd));
    }
    printf("entries: %d   extracted ok: %d\n", n_total, n_ok);

    CloseArchive(h);
    FreeLibrary(H);
    return (n_total == n_ok) ? 0 : 2;
}
