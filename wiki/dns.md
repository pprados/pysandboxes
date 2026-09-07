# DNS and iptables
Configuring a firewall on Linux is done using iptables rules. These rules operate at the IP level and cannot handle domain names.

This makes it difficult to restrict access to a specific domain using these rules. Indeed, there are several complex scenarios to manage.

A DNS server will return a list of IP addresses for a domain name. From these addresses, it is possible to create rules to allow access only to these IP addresses.

**Py-sandboxes** works this way. For a rule like:
```text
net=ALLOW|tcp|www.google.com|443|OUT
```

It will resolve `www.google.com`. For example, retrieve 1.2.3.4 and 1.2.3.5. From this information, the program will generate `iptables` rules to allow access to these addresses.

However, there are some difficulties.

# Difficulties
It is possible that the IP addresses of sites change. This is why DNS records have a TTL (Time to live) parameter. Beyond that, it is relevant to resolve the domain name again to potentially retrieve new addresses. This will impact the `iptables` rules which cannot be updated from the sandbox (and fortunately so).
Therefore, it is possible that access will no longer be available from the sandbox if the addresses change.

Another difficulty can arise if the DNS server uses a "Round-robin" strategy. That is, it will return a different pair of addresses with each request. 1.2.3.4 and 1.2.3.5 for the first request, then 4.5.6.7 and 4.5.6.8 for the second, etc. In this situation, when **Py-sandboxes** resolves the domain name, it will create rules to allow access to 1.2.3.4 and 1.2.3.5. But when the program in the sandbox requests, in turn, the resolution of the domain name, IPs 4.5.6.7 and 4.5.6.8 would need to be used. **Py-sandboxes** does not provide addresses for these.

To solve this, when **Py-sandboxes** resolves the domain name, it will *pin* the resolution in the sandbox. It will communicate this resolution, so that subsequent requests in the sandbox always return these same authorized values. The Python code will resolve the domain name, always with 1.2.3.4 and 1.2.3.5. Thus, the Python code is properly limited to these addresses and continues to work.

A last difficulty is that this resolution happens when the configuration is *parsed*, before anything runs. A resolver that answers late — one still starting up in a container, or answering under load — would therefore turn a perfectly valid profile into a fatal configuration error claiming the rule does not resolve to any network. **Py-sandboxes** retries a *transient* failure (`EAI_AGAIN`, `EAI_SYSTEM`) twice, 0.2s then 0.4s, and does **not** retry a name that does not exist (`EAI_NONAME`, `EAI_FAIL`, `EAI_NODATA`): that one is the rule author's mistake and must surface at once. The budget is deliberately small, so that parsing never hangs on a resolver that is down; when it is exhausted, the error message names the resolver rather than the rule.

What happens once a name is declared unresolvable depends on what the rule was going to do, because the two directions are not symmetric. An `ALLOW` grants access, so a name that resolves to nothing grants nothing: the rule is dropped with a warning and the traffic it described falls through to the implicit default policy, which denies. A machine with no resolver at all — an offline build, a container without DNS — therefore still starts, and starts *more* restricted rather than less. A `DENY` is the mirror image: dropping it would lift a restriction its author wrote on purpose, and the connection would then be decided by whatever broader `ALLOW` sits next to it. That case stays a fatal configuration error, so the process refuses to start instead of running with limits its profile never described. Both branches are fail-closed; they differ only in whether failing closed is worth aborting over.

The consequence worth stating plainly: an unresolvable rule never widens anything. A profile parsed without a resolver is a subset of the profile its author wrote, never a superset.

# How to handle IP address changes
Your program can work without problems until the IP addresses change. If the previous addresses no longer work, the program will fail to communicate with the server. In this situation, there are several possible strategies.

## Partial scenario
In the case where part of the application is in a sandbox, the latter can identify connection failures and kill the Python instance. This will interrupt the process in the sandbox, then the sandbox itself. The parent application will detect this and restart a new sandbox instance with new IP address values. After this sandbox refresh, the application resumes its normal course.

## Complete scenario
In the case where the sandbox encapsulates the entire application, it can also detect the situation. If it is in a redundant architecture, it just needs to stop so that a new instance is launched in its place, with new values for the IP addresses.

## Use all possible IP addresses
Some sites provide files with all possible IP addresses. For example, the following script allows generating rules for GitHub without using a domain name.
```bash
#!/bin/bash
# Script: generate_github_iptables.sh
# Description: Fetches official GitHub IP ranges and generates iptables rules
#              to allow outgoing traffic to these ranges on standard ports (443/22).
# Usage: ./generate_github_iptables.sh >.py-sandbox-github

# --- Configuration Variables ---

# GitHub API URL to fetch IP meta information
GITHUB_META_URL="https://api.github.com/meta"
# Name of the custom iptables chain
IPTABLES_CHAIN="GITHUB_ACCESS"
# Ports to allow (HTTPS/SSH)
ALLOWED_PORTS="443,22"

# --- Functions ---

# Function to check for dependencies
check_dependencies() {
    if ! command -v jq &> /dev/null
    then
        echo "Error: 'jq' is not installed. Please install it (e.g., sudo apt install jq)." >&2
        exit
    fi
}

# Function to generate and print the iptables commands
generate_rules() {
    IPV4_RANGES=$(curl -s "$GITHUB_META_URL" | jq -r '.web[], .git[] | select(type == "string" and (contains(":") | not))')

    if [ -z "$IPV4_RANGES" ]; then
        echo "# Warning: No IPv4 ranges found or API error occurred."
    else
        echo "$IPV4_RANGES" | while read IP_RANGE; do
            # Add rule: Allow TCP traffic destined to the IP range on allowed ports.
            echo "net=ALLOW|tcp|$IP_RANGE|$ALLOWED_PORTS|OUT"
        done
    fi
}

# --- Main Execution ---

check_dependencies
generate_rules
```
You need to use it like this:
```bash
./github-range.sh >.py-sandbox-github
```
then add to your rule file:
```text
include ".py-sandbox-github"
```

## Proxy
Finally, a SOCKS5 or HTTP proxy can be the only exit point allowed by the application. It is responsible for filtering authorized or unauthorized sites.

In your architecture, add a proxy of this type and then set the associated environment variables.

```text
# For SOCKS5
env=HTTP_PROXY="socks5://192.168.1.10:9050"
env=HTTPS_PROXY="socks5://192.168.1.10:9050"

# For HTTP
env=HTTP_PROXY="http://user:password@192.168.1.10:8080"
env=HTTPS_PROXY="http://user:password@192.168.1.10:8080"
```
