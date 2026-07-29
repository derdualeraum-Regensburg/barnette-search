# Reproducible plantri 5.8 setup

The Python package never downloads or builds plantri. Obtain the official
`plantri58.tar.gz` release explicitly from:

<https://users.cecs.anu.edu.au/~bdm/plantri/>

The expected SHA-256 digest is:

```text
E78A944116FEC9F2C9F5E484206276CC2B0043BAE803E9815F4B2683614629B8
```

For example, the download and extraction can be performed explicitly on
Windows from the repository root:

```powershell
New-Item -ItemType Directory -Force .tools\plantri
Invoke-WebRequest https://users.cecs.anu.edu.au/~bdm/plantri/plantri58.tar.gz `
  -OutFile .tools\plantri\plantri58.tar.gz
Get-FileHash -Algorithm SHA256 .tools\plantri\plantri58.tar.gz
tar -xzf .tools\plantri\plantri58.tar.gz -C .tools\plantri
```

On Linux or WSL, extract it and run the command recommended by the guide:

```console
curl -O https://users.cecs.anu.edu.au/~bdm/plantri/plantri58.tar.gz
sha256sum plantri58.tar.gz
tar -xzf plantri58.tar.gz
cd plantri58
cc -O3 -std=c11 plantri.c -o plantri
```

Native Windows lacks `sys/times.h` and otherwise translates byte `0x0a` on
stdout to CRLF, which corrupts binary planar code. The included PowerShell
script copies the source, applies `windows-portability.patch` (disabling only
the internal CPU timer and setting stdout to binary mode), and builds with
Zig's C compiler:

```powershell
python -m pip install ziglang==0.15.2
.\tools\plantri\build_windows.ps1
```

Set `PLANTRI_EXECUTABLE` or pass `--plantri` to the enumeration CLI. The
executable is version-checked before generation.
