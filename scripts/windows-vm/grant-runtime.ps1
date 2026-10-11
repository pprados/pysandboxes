$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class AppContainerCapabilitySid {
    [DllImport("KernelBase.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool DeriveCapabilitySidsFromName(
        string name,
        out IntPtr capabilityGroupSids,
        out uint capabilityGroupSidCount,
        out IntPtr capabilitySids,
        out uint capabilitySidCount);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool ConvertSidToStringSid(IntPtr sid, out IntPtr stringSid);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LocalFree(IntPtr memory);
}
'@

$groupSids = [IntPtr]::Zero
$groupSidCount = [uint32]0
$capabilitySids = [IntPtr]::Zero
$capabilitySidCount = [uint32]0
$result = [AppContainerCapabilitySid]::DeriveCapabilitySidsFromName(
    'pysandboxesRuntime',
    [ref]$groupSids,
    [ref]$groupSidCount,
    [ref]$capabilitySids,
    [ref]$capabilitySidCount)
if (-not $result -or $capabilitySidCount -lt 1) {
    throw "DeriveCapabilitySidsFromName failed with Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}

$sidText = [IntPtr]::Zero
try {
    $capabilitySid = [Runtime.InteropServices.Marshal]::ReadIntPtr($capabilitySids)
    if (-not [AppContainerCapabilitySid]::ConvertSidToStringSid($capabilitySid, [ref]$sidText)) {
        throw "ConvertSidToStringSid failed with Win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    $sid = [Runtime.InteropServices.Marshal]::PtrToStringUni($sidText)
} finally {
    if ($sidText -ne [IntPtr]::Zero) {
        [void][AppContainerCapabilitySid]::LocalFree($sidText)
    }
    for ($index = 0; $index -lt $groupSidCount; $index++) {
        [void][AppContainerCapabilitySid]::LocalFree([Runtime.InteropServices.Marshal]::ReadIntPtr($groupSids, $index * [IntPtr]::Size))
    }
    for ($index = 0; $index -lt $capabilitySidCount; $index++) {
        [void][AppContainerCapabilitySid]::LocalFree([Runtime.InteropServices.Marshal]::ReadIntPtr($capabilitySids, $index * [IntPtr]::Size))
    }
    [void][AppContainerCapabilitySid]::LocalFree($groupSids)
    [void][AppContainerCapabilitySid]::LocalFree($capabilitySids)
}

& icacls.exe 'C:\uv-python' /grant "*$($sid):(OI)(CI)RX" /T
if ($LASTEXITCODE -ne 0) {
    throw "icacls failed to grant read access to C:\uv-python for pysandboxesRuntime (exit $LASTEXITCODE)"
}
