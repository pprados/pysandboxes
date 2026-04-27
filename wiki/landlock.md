# LandLock

[LandLock](https://landlock.io/) is an OS-level sandboxing technology at the process level, requiring no special privileges to be activated. It has been available since Linux kernel version 5.3.

LandLock operates on a **"Whitelist"** approach, where all access is denied by default. It is capable of authorizing read and write access to directories and limiting listening or destination ports for network calls (TCP only).
As of the current version (ABI v5), it is not yet capable of controlling destination IP addresses.

Nevertheless, it offers the advantage of working everywhere without limitations. It requires no specific privileges to function. The process itself decides which restrictions it wishes to apply and activates them. Once activated, it cannot escape them. Child processes inherit the same constraints.

## Using with Docker/Podman
LandLock is compatible with Docker and Podman.

## Specific Parameters

There are no specific parameters available for *LandLock*.